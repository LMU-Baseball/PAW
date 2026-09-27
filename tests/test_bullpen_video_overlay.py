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
         "horz_break": 10.2, "ind_vert_break": -24.1},
        {"play_id": "p2", "pitch_type": "Slider", "velo": 84.0,
         "plate_loc_side": -0.3, "plate_loc_height": 1.9,
         "horz_break": -3.0, "ind_vert_break": -30.0},
    ])


def _pitch():
    df = _session_df()
    return df.iloc[0].to_dict()


def test_compute_layout_keeps_video_native_and_adds_banner_and_sidebar_around_it():
    """2026-09-27 redesign: the clip is never shrunk -- the banner and
    sidebar are added around it, so the output frame is larger."""
    layout = overlay.compute_layout(1280, 1008)
    assert (layout["video_w"], layout["video_h"]) == (1280, 1008)
    for key in ("width", "height", "top_h", "right_w"):
        assert layout[key] % 2 == 0
    assert layout["video_y"] == layout["top_h"]
    assert layout["video_x"] + layout["video_w"] == layout["width"] - layout["right_w"]
    assert layout["height"] == layout["top_h"] + layout["video_h"]
    assert abs(layout["right_w"] / layout["width"] - overlay.RIGHT_FRAC) < 0.01
    # Banner keeps the banner art's own aspect ratio (1456x176).
    assert abs(layout["width"] / layout["top_h"] - 1456 / 176) < 0.1


def test_build_overlay_png_is_opaque_on_bars_and_transparent_over_video():
    png = overlay.build_overlay_png(
        _pitch(), _session_df(), player_name="Test Player", date="2026-09-17",
        pitch_index=1, pitch_count=2, width=640, height=480)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    img = Image.open(__import__("io").BytesIO(png))
    layout = overlay.compute_layout(640, 480)
    assert img.mode == "RGBA"
    assert img.size == (layout["width"], layout["height"])
    # Over the footage: fully transparent, never covering the video.
    assert img.getpixel((50, layout["top_h"] + 240))[3] == 0
    # Banner and sidebar: opaque art.
    assert img.getpixel((5, 5))[3] == 255
    assert img.getpixel((layout["width"] - 5, layout["height"] - 5))[3] == 255


def test_build_overlay_png_fits_long_pitch_names():
    pitch = dict(_pitch(), pitch_type="Four-Seam Fastball Extra Long Name")
    png = overlay.build_overlay_png(
        pitch, _session_df(), player_name="Test Player", date="2026-09-17",
        pitch_index=1, pitch_count=2, width=1280, height=1008)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_build_overlay_png_handles_missing_location_and_break_gracefully():
    """A pitch with no located plate position (common -- not every pitch is
    tracked) must not crash the zone-box scatter or the metrics text."""
    pitch = {"play_id": "p1", "pitch_type": "Fastball", "velo": None,
            "plate_loc_side": None, "plate_loc_height": None,
            "horz_break": None, "ind_vert_break": None}
    png = overlay.build_overlay_png(
        pitch, _session_df(), player_name="Test Player", date="2026-09-17",
        pitch_index=1, pitch_count=2, width=320, height=240)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def _layout():
    return overlay.compute_layout(640, 480)


def test_composite_overlay_raises_overlay_error_when_ffmpeg_missing(monkeypatch):
    def _raise(*a, **k):
        raise FileNotFoundError()

    monkeypatch.setattr(overlay.subprocess, "run", _raise)
    with pytest.raises(overlay.OverlayError, match="ffmpeg not found"):
        overlay.composite_overlay(b"fake-video", b"fake-png", _layout())


def test_composite_overlay_raises_overlay_error_on_ffmpeg_failure(monkeypatch):
    def _raise(*a, **k):
        raise subprocess.CalledProcessError(1, ["ffmpeg"], stderr=b"invalid data")

    monkeypatch.setattr(overlay.subprocess, "run", _raise)
    with pytest.raises(overlay.OverlayError, match="invalid data"):
        overlay.composite_overlay(b"fake-video", b"fake-png", _layout())


def test_composite_overlay_reads_ffmpegs_output_file(monkeypatch):
    def _fake_run(args, check, capture_output):
        out_path = args[-1]
        with open(out_path, "wb") as f:
            f.write(b"composited-mp4-bytes")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(overlay.subprocess, "run", _fake_run)
    result = overlay.composite_overlay(b"fake-video", b"fake-png", _layout())
    assert result == b"composited-mp4-bytes"


def test_composite_overlay_filter_uses_the_layouts_own_scale_and_pad_values(monkeypatch):
    """The ffmpeg filter string must reflect the SAME layout passed in --
    otherwise the overlay PNG's element positions (sized against one
    layout) could land on a differently-scaled/padded video."""
    captured = {}

    def _fake_run(args, check, capture_output):
        captured["filter"] = args[args.index("-filter_complex") + 1]
        out_path = args[-1]
        with open(out_path, "wb") as f:
            f.write(b"x")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(overlay.subprocess, "run", _fake_run)
    layout = _layout()
    overlay.composite_overlay(b"fake-video", b"fake-png", layout)
    assert f"scale={layout['video_w']}:{layout['video_h']}" in captured["filter"]
    assert (f"pad={layout['width']}:{layout['height']}:"
           f"{layout['video_x']}:{layout['video_y']}:black") in captured["filter"]
