"""Turn an uploaded Forge video into a 720p H.264 MP4 + thumbnail.

Runs in its own long-lived process (scripts/forge_transcode.py), never inside
a web request. Every encode takes the same one-at-a-time slot as the bullpen
video download route, so the two can never stack up and freeze the 2 GB box
(the 2026-09-27 outage). iPhone HEVC becomes H.264 here, which is what lets it
play in Chrome on Windows.
"""
from __future__ import annotations

import contextlib
import logging
import os
import re
import subprocess
import tempfile
from datetime import timedelta

from app.data import forge as F
from app.data import forge_storage as S

log = logging.getLogger(__name__)

# Short side scaled to 720 (never upscaled), so portrait phone video stays
# portrait. Commas inside the expressions are escaped for the filtergraph.
_SCALE = ("scale='if(gt(iw,ih),-2,min(720\\,iw))':'if(gt(iw,ih),min(720\\,ih),-2)',"
          "format=yuv420p")
_ENCODE_TIMEOUT_SEC = 60 * 60
# Same lock file as app.reports.bullpen_video_overlay._encode_slot (not
# imported: that module drags in matplotlib and the reports blueprint).
_ENCODE_LOCK_PATH = os.path.join(tempfile.gettempdir(), "paw-clip-encode.lock")


@contextlib.contextmanager
def _encode_slot():
    try:
        import fcntl
    except ImportError:
        yield
        return
    with open(_ENCODE_LOCK_PATH, "a") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def _ffmpeg_path() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def probe(path: str) -> dict:
    """Duration and display size from ffmpeg's own banner (imageio-ffmpeg
    ships no ffprobe)."""
    proc = subprocess.run([_ffmpeg_path(), "-hide_banner", "-i", path],
                          capture_output=True, text=True, errors="replace")
    out = proc.stderr
    info: dict = {}
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", out)
    if m:
        info["duration"] = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    m = re.search(r"Stream #.*Video:.*?(\d{2,5})x(\d{2,5})", out)
    if m:
        info["width"], info["height"] = int(m[1]), int(m[2])
    return info


def encode(src: str, dst: str, thumb: str, strip_audio: bool = False) -> dict:
    ff = _ffmpeg_path()
    audio = ["-an"] if strip_audio else ["-c:a", "aac", "-b:a", "96k", "-ac", "1"]
    with _encode_slot():
        subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y", "-i", src,
                        "-vf", _SCALE, "-fpsmax", "60",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-threads", "2",
                        *audio, "-movflags", "+faststart", dst],
                       check=True, capture_output=True, timeout=_ENCODE_TIMEOUT_SEC)
    info = probe(dst)
    at = "1" if info.get("duration", 0) > 2 else "0"
    subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y", "-ss", at, "-i", dst,
                    "-frames:v", "1", "-vf", "scale=-2:360", "-q:v", "4", thumb],
                   check=True, capture_output=True, timeout=120)
    return info


def process(video: F.ForgeVideo) -> None:
    """Download, convert, upload, and mark one queued video ready (or failed)."""
    F.set_video(video, status="processing", error=None)
    with tempfile.TemporaryDirectory(prefix="forge-") as tmp:
        src = os.path.join(tmp, "src" + os.path.splitext(video.original_key)[1])
        dst = os.path.join(tmp, "720p.mp4")
        thumb = os.path.join(tmp, "thumb.jpg")
        try:
            S.download(video.original_key, src)
            src_info = probe(src)
            if src_info.get("duration", 0) > F.MAX_DURATION_SEC + 60:
                raise ValueError("longer than 20 minutes")
            if "width" not in src_info:
                raise ValueError("not a video file")
            info = encode(src, dst, thumb, strip_audio=bool(video.strip_audio))
            pkey = S.playback_key(video.channel_id, video.id)
            tkey = S.thumb_key(video.channel_id, video.id)
            S.upload(dst, pkey, "video/mp4")
            S.upload(thumb, tkey, "image/jpeg")
        except Exception as e:
            log.exception("forge: video %s failed", video.id)
            reason = str(e) if isinstance(e, ValueError) else "couldn't convert this file"
            F.set_video(video, status="failed", error=reason[:500])
            return
        F.set_video(video, status="ready", playback_key=pkey, thumb_key=tkey,
                    playback_size=os.path.getsize(dst), duration_sec=info.get("duration"),
                    width=info.get("width"), height=info.get("height"),
                    processed_at=F._now())
    # Only the 720p copy is kept (Brad, 2026-11-24): the original is ~10-20x
    # bigger and isn't needed once the playable copy exists.
    try:
        S.delete(video.original_key)
    except Exception:
        log.warning("forge: couldn't delete original for video %s", video.id, exc_info=True)


def expire_stale_uploads() -> int:
    """Give up on uploads abandoned mid-way (tab closed) so their S3 parts
    don't linger. The bucket's lifecycle rule is the backstop."""
    cutoff = F._now() - timedelta(hours=F.STALE_UPLOAD_HOURS)
    stale = F.ForgeVideo.query.filter(F.ForgeVideo.status == "uploading",
                                      F.ForgeVideo.created_at < cutoff).all()
    for v in stale:
        if v.upload_id and v.original_key:
            try:
                S.abort_multipart(v.original_key, v.upload_id)
            except Exception:
                log.warning("forge: abort failed for stale video %s", v.id, exc_info=True)
        F.set_video(v, status="failed", error="upload never finished", upload_id=None)
    return len(stale)


def reset_interrupted() -> int:
    """A worker killed mid-encode leaves its video 'processing' forever;
    requeue those at startup."""
    rows = F.ForgeVideo.query.filter_by(status="processing").all()
    for v in rows:
        F.set_video(v, status="queued")
    return len(rows)


def run_once() -> int:
    """Process every queued video, oldest first. Returns how many were handled."""
    expire_stale_uploads()
    n = 0
    while True:
        video = (F.ForgeVideo.query.filter_by(status="queued")
                 .order_by(F.ForgeVideo.id).first())
        if video is None:
            return n
        process(video)
        n += 1
