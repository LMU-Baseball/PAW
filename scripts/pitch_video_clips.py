"""Cut per-pitch video clips from segmented game-day camera footage, matched
to Trackman pitch timestamps recovered from the FileZilla SFTP server.

Why FileZilla and not the DB: GAMES.Time/UTCDateTime/LocalDateTime are NULL
for at least some games -- the games ingest loader drops them -- so the raw
per-pitch CSV (still sitting on the Trackman SFTP server) is the only source
of real per-pitch timestamps.

Why this isn't fully automatic: these cameras split recording into
fixed-size segment files (observed: ~18 minutes each, ~4GB, consistent with
a FAT32-formatted card). A segment file's mtime does NOT reliably mark its
true start -- there's a real, variable gap at every file rollover
(unpredictable in both size and direction, confirmed by comparing a
segment's last frame to the next segment's first frame -- real game time
passes that isn't captured on either file). So naive "elapsed nominal
seconds since segment start" math lands anywhere from 0 to 25+ seconds off
actual pitch content, and the error is NOT constant within a segment --
piecewise-linear correction from real anchor points is required. See
docs/pitch-video-clipping.md for the full story, and — importantly — a
checklist for picking anchor points that won't waste your time.

Two-step workflow:
  1. `fetch-csv` -- pull the raw per-pitch CSV for a game from FileZilla.
  2. `clip`      -- given that CSV, a folder of segment video files for one
     camera angle, and a small hand-built JSON anchors file (real per-pitch
     timestamps a human has verified against the actual video), cut a clip
     per pitch using piecewise-linear interpolation between anchors within
     each segment.

Anchors file format -- a JSON object keyed by segment filename, each value a
list of [nominal_offset_seconds, true_offset_seconds] pairs, sorted by
nominal_offset (at least 2 pairs per segment you want clips from):
    {
      "USD_5.15.2026_HomeRight_01.mp4": [[658.57, 674.2], [717.19, 709.2]],
      "USD_5.15.2026_HomeRight_02.mp4": [[163.2, 184.3], [970.5, 972.9]]
    }
`nominal_offset` = a pitch's real Trackman timestamp minus that segment's
naive start time (see `segment_windows`). `true_offset` = that same pitch's
verified real position within the segment file, in seconds -- found by
watching the video (front-foot landing is the most reliable cue: it works
on every pitch, take or swing, unlike waiting for contact) and reading off
the timestamp.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import posixpath
import subprocess
import sys
from dataclasses import dataclass

import click
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ingest.config import trackman_cfg  # noqa: E402
from app.ingest.connections import open_sftp  # noqa: E402


def _ffmpeg_path() -> str:
    """Portable ffmpeg binary bundled with imageio-ffmpeg -- no system
    install required."""
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


# ---------------------------------------------------------------------------
# Step 1: fetch the raw per-pitch CSV (with real timestamps) from FileZilla
# ---------------------------------------------------------------------------

def find_game_csv(sftp, game_date: str, opponent_slug: str, game_num: int = 1,
                  search_days: int = 3) -> str | None:
    """Search `/v3/<upload-date>/CSV` for a file named
    "<game_date>-<opponent_slug>-<game_num>.csv". The folder is keyed by
    UPLOAD date, not game date (can lag by a day or two -- confirmed on the
    2026-05-15 game, which uploaded to the 05-16 folder), so this checks
    game_date through game_date + search_days. Returns the remote path, or
    None if no match was found in that window."""
    target = f"{game_date.replace('-', '')}-{opponent_slug}-{game_num}.csv"
    base = dt.datetime.strptime(game_date, "%Y-%m-%d")
    for offset in range(search_days + 1):
        day = base + dt.timedelta(days=offset)
        remote_dir = f"/v3/{day.year}/{day.month:02d}/{day.day:02d}/CSV"
        try:
            names = sftp.listdir(remote_dir)
        except OSError:
            continue
        if target in names:
            return posixpath.join(remote_dir, target)
    return None


def fetch_game_csv(game_date: str, opponent_slug: str, game_num: int, out_path: str) -> str:
    """Download the raw per-pitch CSV for a game to `out_path`. Raises
    FileNotFoundError if no matching file turns up in the search window."""
    with open_sftp(trackman_cfg()) as sftp:
        remote = find_game_csv(sftp, game_date, opponent_slug, game_num)
        if remote is None:
            raise FileNotFoundError(
                f"No CSV found for {game_date} vs {opponent_slug} game {game_num} "
                f"under /v3/<upload-date>/CSV (searched game_date through +3 days)")
        sftp.get(remote, out_path)
    return out_path


# ---------------------------------------------------------------------------
# Step 2: segment discovery + piecewise-corrected clip generation
# ---------------------------------------------------------------------------

@dataclass
class Segment:
    filename: str
    start: float  # seconds-of-day, real local time (naive -- see module docstring)
    end: float


def ffprobe_duration(path: str) -> float:
    """A video file's exact declared duration, in seconds. Uses ffmpeg -i
    and parses stderr (imageio-ffmpeg ships ffmpeg only, not ffprobe)."""
    out = subprocess.run([_ffmpeg_path(), "-i", path], capture_output=True, text=True).stderr
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("Duration:"):
            h, m, s = line.split(",")[0].split(":")[1:]
            return int(h) * 3600 + int(m) * 60 + float(s)
    raise ValueError(f"could not parse a Duration line from ffmpeg output for {path}")


def segment_windows(video_dir: str, angle_prefix: str,
                    duration_fn=ffprobe_duration) -> list[Segment]:
    """Discover one camera angle's segment files (matched by filename
    prefix) in `video_dir`, sorted by filesystem mtime, and compute each
    one's naive (start, end) in seconds-of-day real local time.

    end[i]   = file i's mtime (verified reliable as a segment CLOSE marker
               -- see module docstring)
    start[0] = end[0] - file 0's own duration (no earlier segment to chain
               from)
    start[i] = end[i-1] for i > 0 (chained from the previous segment's close
               time)

    This locates which segment a pitch falls in accurately. It does NOT
    give an accurate WITHIN-segment position -- that's what the anchors
    file in `generate_clips` corrects for.
    """
    files = sorted(
        (f for f in os.listdir(video_dir) if f.startswith(angle_prefix) and f.endswith(".mp4")),
        key=lambda f: os.path.getmtime(os.path.join(video_dir, f)),
    )
    if not files:
        raise FileNotFoundError(f"no files matching '{angle_prefix}*.mp4' in {video_dir}")

    segments: list[Segment] = []
    prev_end: float | None = None
    for f in files:
        path = os.path.join(video_dir, f)
        mtime = dt.datetime.fromtimestamp(os.path.getmtime(path))
        end = mtime.hour * 3600 + mtime.minute * 60 + mtime.second + mtime.microsecond / 1e6
        start = prev_end if prev_end is not None else end - duration_fn(path)
        segments.append(Segment(f, start, end))
        prev_end = end
    return segments


def locate_segment(real_seconds: float,
                   segments: list[Segment]) -> tuple[Segment | None, float | None]:
    """Which segment `real_seconds` (seconds-of-day, real local time) falls
    in, and its naive nominal offset within that segment. (None, None) if
    it's outside every segment's window."""
    for seg in segments:
        if seg.start <= real_seconds <= seg.end:
            return seg, real_seconds - seg.start
    return None, None


def build_corrector(anchors: list[tuple[float, float]]):
    """A piecewise-linear function `nominal_offset -> corrected_offset`,
    given sorted (nominal, true) anchor pairs (at least 2). EXTRAPOLATES
    using the boundary segment's slope outside the anchor range -- plain
    `np.interp` clamps outside its range instead, which silently produces
    identical (wrong) positions for every pitch past the last anchor. Caught
    that the hard way building this the first time; see
    docs/pitch-video-clipping.md."""
    if len(anchors) < 2:
        raise ValueError("need at least 2 anchors to interpolate/extrapolate")
    noms = np.array([a[0] for a in anchors])
    trues = np.array([a[1] for a in anchors])

    def corrected(nominal: float) -> float:
        if nominal <= noms[0]:
            slope = (trues[1] - trues[0]) / (noms[1] - noms[0])
            return float(trues[0] + slope * (nominal - noms[0]))
        if nominal >= noms[-1]:
            slope = (trues[-1] - trues[-2]) / (noms[-1] - noms[-2])
            return float(trues[-1] + slope * (nominal - noms[-1]))
        return float(np.interp(nominal, noms, trues))
    return corrected


def safe_filename_part(s) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in str(s))


def cut_clip(video_path: str, center: float, pad_before: float, pad_after: float,
            out_path: str) -> None:
    """Cut [center-pad_before, center+pad_after] from `video_path` to
    `out_path`. Re-encodes rather than stream-copying: `-c copy` seeks snap
    to the nearest keyframe, silently shifting the clip start by up to a
    couple of seconds -- not acceptable when timing accuracy is the whole
    point. Audio is dropped -- these cameras' audio tracks were checked and
    found to be silent (flat zero) throughout."""
    start = max(0.0, center - pad_before)
    duration = pad_before + pad_after
    cmd = [_ffmpeg_path(), "-y", "-ss", f"{start:.2f}", "-i", video_path,
           "-t", f"{duration:.2f}", "-an", "-c:v", "libx264",
           "-preset", "veryfast", "-crf", "26", out_path]
    subprocess.run(cmd, check=True, capture_output=True)


def generate_clips(video_dir: str, angle_prefix: str, csv_path: str, game_id: str,
                   anchors_path: str, out_dir: str, pad_before: float = 2.0,
                   pad_after: float = 3.0, gap_pad_before: float = 8.0,
                   gap_pad_after: float = 10.0, gap_threshold: float = 60.0) -> dict:
    """Cut one clip per pitch for `game_id`, for the camera angle whose
    segment files live in `video_dir` matching `angle_prefix`.

    Pitches whose segment has fewer than 2 anchors, or that fall outside
    every segment's window, are skipped and reported rather than guessed
    at -- an unanchored segment gets no clips at all instead of clips
    built on a made-up correction.

    A pitch more than `gap_threshold` seconds (nominal) from its nearest
    anchor gets the wider `gap_pad_before`/`gap_pad_after` padding instead
    of `pad_before`/`pad_after`, as a safety margin against interpolation
    error in sparsely-anchored stretches of a segment.

    Returns {"made": int, "skipped_no_anchors": [PitchNo, ...],
             "skipped_out_of_range": [PitchNo, ...]}.
    """
    from app.db import query_df

    segments = segment_windows(video_dir, angle_prefix)
    with open(anchors_path) as fh:
        anchors_by_file: dict = json.load(fh)

    raw = pd.read_csv(csv_path, usecols=["PitchUID", "LocalDateTime"])
    raw["local_dt"] = pd.to_datetime(raw["LocalDateTime"])
    raw["sec"] = (raw["local_dt"].dt.hour * 3600 + raw["local_dt"].dt.minute * 60
                  + raw["local_dt"].dt.second + raw["local_dt"].dt.microsecond / 1e6)

    meta = query_df(
        "SELECT PitchUID, PitchNo, Inning, Pitcher, Batter, Balls, Strikes, "
        "TaggedPitchType, PitchCall, PlayResult FROM GAMES WHERE GameID=:g ORDER BY PitchNo",
        {"g": game_id},
    )
    df = meta.merge(raw[["PitchUID", "sec"]], on="PitchUID", how="inner")

    os.makedirs(out_dir, exist_ok=True)
    made = 0
    skipped_no_anchors: list[int] = []
    skipped_out_of_range: list[int] = []
    correctors = {f: build_corrector([tuple(a) for a in pts])
                 for f, pts in anchors_by_file.items() if len(pts) >= 2}

    for _, r in df.iterrows():
        seg, nominal = locate_segment(r["sec"], segments)
        if seg is None:
            skipped_out_of_range.append(int(r["PitchNo"]))
            continue
        if seg.filename not in correctors:
            skipped_no_anchors.append(int(r["PitchNo"]))
            continue

        center = correctors[seg.filename](nominal)
        noms = [a[0] for a in anchors_by_file[seg.filename]]
        nearest_gap = min(abs(nominal - n) for n in noms)
        pb, pa = ((gap_pad_before, gap_pad_after) if nearest_gap > gap_threshold
                 else (pad_before, pad_after))

        result = (r["PlayResult"] if r["PlayResult"] and r["PlayResult"] != "Undefined"
                 else r["PitchCall"])
        fname = (f"{int(r['PitchNo']):03d}_Inn{int(r['Inning'])}_"
                 f"{safe_filename_part(r['Pitcher'])}_vs_{safe_filename_part(r['Batter'])}_"
                 f"{r['Balls']:.0f}-{r['Strikes']:.0f}_{safe_filename_part(r['TaggedPitchType'])}_"
                 f"{safe_filename_part(result)}.mp4")
        cut_clip(os.path.join(video_dir, seg.filename), center, pb, pa,
                os.path.join(out_dir, fname))
        made += 1

    return {"made": made, "skipped_no_anchors": skipped_no_anchors,
            "skipped_out_of_range": skipped_out_of_range}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.group()
def cli():
    """Per-pitch video clipping tools. See the module docstring (top of this
    file) and docs/pitch-video-clipping.md before running either command."""


@cli.command("fetch-csv")
@click.option("--date", required=True, help="Game date, YYYY-MM-DD")
@click.option("--opponent", required=True,
             help="Opponent slug exactly as it appears in the CSV filename, e.g. UofSanDiego")
@click.option("--game-num", default=1, show_default=True,
             help="Game number, for a series/doubleheader")
@click.option("--out", "out_path", required=True, help="Local path to save the CSV to")
def fetch_csv_cmd(date, opponent, game_num, out_path):
    """Download the raw per-pitch CSV (with real timestamps) for a game."""
    path = fetch_game_csv(date, opponent, game_num, out_path)
    click.echo(f"saved {path}")


@cli.command("clip")
@click.option("--video-dir", required=True, help="Folder containing this angle's segment .mp4 files")
@click.option("--angle-prefix", required=True,
             help="Filename prefix identifying this camera angle's segment files")
@click.option("--csv", "csv_path", required=True, help="Path to the CSV from fetch-csv")
@click.option("--game-id", required=True, help="GAMES.GameID for this game")
@click.option("--anchors", "anchors_path", required=True, help="Path to the anchors JSON file")
@click.option("--out-dir", required=True)
@click.option("--pad-before", default=2.0, show_default=True)
@click.option("--pad-after", default=3.0, show_default=True)
def clip_cmd(video_dir, angle_prefix, csv_path, game_id, anchors_path, out_dir,
            pad_before, pad_after):
    """Cut one clip per pitch using the anchors file's piecewise correction."""
    result = generate_clips(video_dir, angle_prefix, csv_path, game_id, anchors_path,
                            out_dir, pad_before, pad_after)
    click.echo(f"made {result['made']} clips in {out_dir}")
    if result["skipped_no_anchors"]:
        click.echo(f"skipped {len(result['skipped_no_anchors'])} pitches "
                   f"(segment has fewer than 2 anchors): {result['skipped_no_anchors']}")
    if result["skipped_out_of_range"]:
        click.echo(f"skipped {len(result['skipped_out_of_range'])} pitches "
                   f"(outside every segment's window): {result['skipped_out_of_range']}")


if __name__ == "__main__":
    cli()
