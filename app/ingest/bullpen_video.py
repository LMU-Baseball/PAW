"""Bullpen (practice) Edgertronic video loader: TrackMan Data API -> DB
BLOB + `bullpen_video_clips` index.

Orchestrates `app.ingest.trackman_video` (the pure API client) and
`app.data.bullpen_video` (the BLOB-storage + index layer): discover practice
sessions in a date range, pull each one's Edgertronic video metadata, skip
plays already downloaded (`BV.existing_play_ids` -- insert-only, like every
other loader here, never re-downloads an already-indexed play), fetch that
session's Azure SAS token once, list its container, and download each
remaining play's blob straight into the database (see `app.data.
bullpen_video`'s module docstring for why a DB BLOB and not local disk/S3 --
short version: this runs on the same disk-less GitHub Actions cron as the
other loaders).

`--dry-run` (default True, matching every other `flask ingest ...` command)
does everything EXCEPT writing the row (bytes never even downloaded), so a
coach/admin can see counts before committing to a real pull.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass

import requests

from app.data import bullpen_video as BV
from app.ingest import trackman_video as TV


class RemuxError(RuntimeError):
    """ffmpeg failed, or isn't installed, while remuxing a clip to MP4."""


@dataclass
class VideoLoadResult:
    sessions: int
    clips_found: int
    clips_downloaded: int
    clips_skipped_existing: int
    clips_missing_blob: int
    dry_run: bool
    sessions_errored: int = 0
    clips_errored: int = 0


def remux_to_mp4(data: bytes) -> bytes:
    """Rewrap Edgertronic's clip into a standard MP4 container Chrome will
    actually play. Confirmed live (2026-09-22): Edgertronic clips come back
    from TrackMan as QuickTime .mov (`ftyp` brand `qt  `) with plain H.264
    video inside, and Chrome's <video> element hangs forever on the raw
    bytes -- readyState stays 0 and neither `loadedmetadata` nor `error`
    ever fires, regardless of the declared MIME type on the <source> tag.
    The codec itself doesn't need to change, just the container, so this is
    a stream copy (`-c copy`, no re-encode -- fast, lossless), not a real
    transcode. `+faststart` moves the moov atom to the front so the clip is
    playable as soon as the browser has the first chunk of bytes, matching
    how every other MP4 in this app is served.

    Requires the `ffmpeg` binary on PATH -- preinstalled on GitHub Actions'
    `ubuntu-latest` runners, where this loader's cron job runs (see
    .github/workflows/pipeline-cron.yml's bullpen-video job); may not be
    present for a local `flask ingest bullpen-video` run on a dev machine.
    """
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.mov")
        dst = os.path.join(tmp, "out.mp4")
        with open(src, "wb") as f:
            f.write(data)
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", src, "-c", "copy", "-movflags", "+faststart",
                 "-f", "mp4", dst],
                check=True, capture_output=True,
            )
        except FileNotFoundError as e:
            raise RemuxError(
                "ffmpeg not found on PATH -- required to remux Edgertronic "
                ".mov clips to browser-playable MP4") from e
        except subprocess.CalledProcessError as e:
            raise RemuxError(
                f"ffmpeg remux failed (exit {e.returncode}): "
                f"{e.stderr.decode(errors='replace')[-500:]}") from e
        with open(dst, "rb") as f:
            return f.read()


def load_bullpen_video(session: TV.Session, date_from: str, date_to: str, *,
                       session_type: str = "Pitching", dry_run: bool = True,
                       limit: int | None = None) -> VideoLoadResult:
    """Load Edgertronic clips for practice sessions in [date_from, date_to]
    (ISO 8601 UTC, e.g. "2026-09-15T00:00:00Z" -- see `TV.discover_practice_
    sessions` for the 30-day span cap). `limit` bounds the total number of
    clips DOWNLOADED across every session (not files/sessions processed --
    matches this loader's own unit of work), mainly for a bounded dry-run
    or a first small real pull."""
    sessions = session.discover_practice_sessions(date_from, date_to, session_type=session_type)

    result = VideoLoadResult(sessions=len(sessions), clips_found=0, clips_downloaded=0,
                             clips_skipped_existing=0, clips_missing_blob=0, dry_run=dry_run)

    for s in sessions:
        if limit is not None and result.clips_downloaded >= limit:
            break
        session_id = s.get("sessionId")
        try:
            metadata = TV.edgertronic_clips(session.practice_video_metadata(session_id))
            if not metadata:
                continue
            result.clips_found += len(metadata)

            play_ids = [m["playId"] for m in metadata if m.get("playId")]
            already = BV.existing_play_ids(play_ids)
            pending = [m for m in metadata if m.get("playId") not in already]
            result.clips_skipped_existing += len(metadata) - len(pending)
            if not pending:
                continue

            tokens = session.practice_video_tokens(session_id)
            token_info = TV.edgertronic_token(tokens)
            if token_info is None:
                # Metadata says these clips exist, but this session has no
                # Edgertronic download token -- nothing to do about it here.
                continue
            blob_names = TV.list_container_blobs(token_info)
        except (TV.TrackmanAPIError, requests.exceptions.RequestException):
            # One session's API call failing (seen live 2026-09-22: a 404 on
            # video metadata for an otherwise-valid session, and separately a
            # raw connection reset partway through a multi-day pull -- the
            # `requests` layer raises its own exceptions for those, not
            # TrackmanAPIError, which only covers a non-2xx HTTP response)
            # must not sink every OTHER session in a batch pull -- count it
            # and move on, same spirit as the per-clip try/except below.
            result.sessions_errored += 1
            continue

        for clip in pending:
            if limit is not None and result.clips_downloaded >= limit:
                break
            play_id = clip["playId"]
            blob_name = TV.blob_for_play(blob_names, play_id)
            if blob_name is None:
                result.clips_missing_blob += 1
                continue
            if not dry_run:
                try:
                    data = TV.download_blob(token_info, blob_name)
                    data = remux_to_mp4(data)
                    BV.add_clip(play_id, session_id, data, mimetype="video/mp4",
                               duration_sec=clip.get("videoDurationInSeconds"),
                               width=clip.get("width"), height=clip.get("height"),
                               framerate=clip.get("framerate"))
                except (TV.TrackmanAPIError, RemuxError, requests.exceptions.RequestException):
                    result.clips_errored += 1
                    continue
            result.clips_downloaded += 1

    return result
