"""app.reports.bullpen_video_overlay: the pitch-data overlay PNG + ffmpeg
compositing for a downloadable Edgertronic clip. No live network and no
real ffmpeg for composite_overlay's failure-path tests (mocked subprocess,
same idiom as tests/test_ingest_bullpen_video_loader.py's remux_to_mp4
tests); build_overlay_png genuinely renders with matplotlib (Agg,
headless, fast) since that's the part worth actually exercising."""
import subprocess

import pandas as pd
import pytest
from PIL import Image

from app.reports import bullpen_video_overlay as overlay


def _session_df():
    return pd.DataFrame([
        {"play_id": "p1", "pitch_type": "Fastball", "velo": 91.7,
         "plate_loc_side": 0.2, "plate_loc_height": 2.0,
         "horz_break": 10.2, "vert_break": -24.1},
        {"play_id": "p2", "pitch_type": "Slider", "velo": 84.0,
         "plate_loc_side": -0.3, "plate_loc_height": 1.9,
         "horz_break": -3.0, "vert_break": -30.0},
    ])


def _pitch():
    df = _session_df()
    return df.iloc[0].to_dict()


def test_build_overlay_png_is_transparent_rgba_at_requested_size():
    png = overlay.build_overlay_png(
        _pitch(), _session_df(), player_name="Test Player", date="2026-09-17",
        pitch_index=1, pitch_count=2, width=640, height=480)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    img = Image.open(__import__("io").BytesIO(png))
    assert img.mode == "RGBA"
    assert img.size == (640, 480)
    # A background corner must be fully transparent (alpha=0) so the
    # overlay only draws its own elements onto the video, not a white box.
    assert img.getpixel((5, 5))[3] == 0


def test_build_overlay_png_handles_missing_location_and_break_gracefully():
    """A pitch with no located plate position (common -- not every pitch is
    tracked) must not crash the zone-box scatter or the metrics text."""
    pitch = {"play_id": "p1", "pitch_type": "Fastball", "velo": None,
            "plate_loc_side": None, "plate_loc_height": None,
            "horz_break": None, "vert_break": None}
    png = overlay.build_overlay_png(
        pitch, _session_df(), player_name="Test Player", date="2026-09-17",
        pitch_index=1, pitch_count=2, width=320, height=240)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_composite_overlay_raises_overlay_error_when_ffmpeg_missing(monkeypatch):
    def _raise(*a, **k):
        raise FileNotFoundError()

    monkeypatch.setattr(overlay.subprocess, "run", _raise)
    with pytest.raises(overlay.OverlayError, match="ffmpeg not found"):
        overlay.composite_overlay(b"fake-video", b"fake-png")


def test_composite_overlay_raises_overlay_error_on_ffmpeg_failure(monkeypatch):
    def _raise(*a, **k):
        raise subprocess.CalledProcessError(1, ["ffmpeg"], stderr=b"invalid data")

    monkeypatch.setattr(overlay.subprocess, "run", _raise)
    with pytest.raises(overlay.OverlayError, match="invalid data"):
        overlay.composite_overlay(b"fake-video", b"fake-png")


def test_composite_overlay_reads_ffmpegs_output_file(monkeypatch):
    def _fake_run(args, check, capture_output):
        out_path = args[-1]
        with open(out_path, "wb") as f:
            f.write(b"composited-mp4-bytes")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(overlay.subprocess, "run", _fake_run)
    assert overlay.composite_overlay(b"fake-video", b"fake-png") == b"composited-mp4-bytes"
