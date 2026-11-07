"""Bullpen Pitch Overlay: the render module (app.reports.bullpen_pitch_overlay),
the Overlay tab's pure helpers, and the route's query parsing. The render
tests use synthetic ffmpeg test-pattern clips, not real bullpen video."""
import subprocess

import numpy as np
import pytest

from app.dashboards.bullpen.tabs import overlay as tab
from app.reports import bullpen_pitch_overlay as PO

_FB = {"pitcher": "Doe, Jane", "date": "2026-11-05", "pitch_type": "Fastball", "velo": 90.1,
       "ind_vert_break": 16.0, "horz_break": 12.0, "spin": 2200, "extension": 6.2,
       "x0": -2.3, "y0": 50.0, "z0": 5.6, "vx0": 7.0, "vy0": -131.0, "vz0": -4.5,
       "ax0": -14.0, "ay0": 28.0, "az0": -15.0}


def _clip(seconds: float, size: str = "320x252") -> bytes:
    return subprocess.run(
        [PO._ffmpeg_path(), "-v", "error", "-f", "lavfi", "-i",
         f"testsrc2=size={size}:rate=240:duration={seconds}", "-c:v", "libx264",
         "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-f", "mp4",
         "-movflags", "frag_keyframe+empty_moov", "-"],
        capture_output=True, check=True).stdout


def test_detect_release_finds_the_motion_peak():
    energy = np.ones(360)
    energy[210:216] = 50
    assert abs(PO.detect_release(energy) - (213 + PO.REL_AFTER_PEAK)) <= 2


def test_detect_release_ignores_motion_at_the_clip_edges():
    energy = np.ones(300)
    energy[2:8] = 500
    energy[290:296] = 500
    energy[150] = 5
    assert 0.35 * 300 <= PO.detect_release(energy) <= 0.85 * 300 + PO.REL_AFTER_PEAK


def test_box_blur_matches_a_plain_mean_filter():
    rng = np.random.default_rng(0)
    a = rng.random((20, 30)).astype(np.float32)
    p = np.pad(a, 2, mode="edge")
    naive = np.array([[p[i:i + 5, j:j + 5].mean() for j in range(30)] for i in range(20)])
    assert np.allclose(PO.box_blur(a), naive, atol=1e-5)


def test_flight_path_runs_release_to_front_of_plate():
    t, x, y, z = PO.flight_path(_FB)
    assert t[0] == pytest.approx(0)
    assert y[0] == pytest.approx(60.5 - _FB["extension"], abs=1e-6)
    assert y[-1] == pytest.approx(17 / 12, abs=1e-6)
    assert 0.35 < t[-1] < 0.5
    assert x[0] < 0  # righty-style release lands on the catcher's left


def test_flight_path_none_without_a_trajectory_fit():
    assert PO.flight_path({**_FB, "vy0": None}) is None
    assert PO.flight_path({**_FB, "ay0": float("nan")}) is None


def test_separation_is_zero_against_itself_and_none_without_a_path():
    path = PO.flight_path(_FB)
    assert PO.separation_in(path, path, 23.8) == pytest.approx(0)
    assert PO.separation_in(path, None, 23.8) is None


def test_pitch_label():
    assert PO.pitch_label(_FB) == "11/05 Fastball 90.1"


@pytest.mark.parametrize("mode", PO.MODES)
def test_render_produces_a_full_length_video(mode):
    clips = [PO.OverlayClip(_FB, _clip(1.0)),
             PO.OverlayClip({**_FB, "date": "2026-11-03", "velo": 84.0}, _clip(1.4), nudge=3)]
    out = PO.render(clips, mode)
    assert out[4:8] == b"ftyp"
    probe = subprocess.run([PO._ffmpeg_path(), "-v", "error", "-i", "-", "-map", "0:v",
                            "-f", "null", "-", "-stats"], input=out, capture_output=True)
    assert probe.returncode == 0
    assert f"frame={PO.PRE + PO.POST + PO.HOLD}" in probe.stderr.decode().replace(" ", "")


def test_render_rejects_too_many_clips_and_unknown_mode():
    clip = PO.OverlayClip(_FB, b"")
    with pytest.raises(ValueError):
        PO.render([clip] * (PO.MAX_PITCHES + 1))
    with pytest.raises(ValueError):
        PO.render([clip], "sideways")


def test_merge_picks_keeps_click_order_and_caps_at_three():
    assert tab.merge_picks([], ["a", "b"]) == ["a", "b"]
    assert tab.merge_picks(["b"], ["a", "b"]) == ["b", "a"]
    assert tab.merge_picks(["a", "x"], ["x"]) == ["x"]
    assert tab.merge_picks(["a", "b", "c"], ["a", "b", "c", "d"]) == ["a", "b", "c"]


def test_filter_query():
    assert tab.filter_query(None, []) == ""
    assert tab.filter_query(["2026-11-05"], ["Fastball", "Sinker"]) == (
        '({date} = "2026-11-05") && ({pitch_type} = "Fastball" || {pitch_type} = "Sinker")')


def test_default_mode_is_side_by_side_across_bullpens():
    assert tab.default_mode(["2026-11-05", "2026-11-05"]) == "overlay"
    assert tab.default_mode(["2026-11-05", "2026-11-03"]) == "side"


def test_overlay_url():
    url = tab.overlay_url(["a", "b"], [0, None], "side", download=True)
    assert url == "/bullpen-overlay.mp4?ids=a%2Cb&nudge=0%2C0&mode=side&dl=1"


def test_overlay_params_parsing():
    from werkzeug.exceptions import BadRequest

    from app.main.routes import _overlay_params
    ids, nudges, mode = _overlay_params({"ids": "a,b,c,d", "nudge": "5,x,-99", "mode": "side"})
    assert ids == ["a", "b", "c"]
    assert nudges == [5, 0, -60]
    assert mode == "side"
    with pytest.raises(BadRequest):
        _overlay_params({"ids": "a", "mode": "sideways"})
    with pytest.raises(BadRequest):
        _overlay_params({"ids": ""})


def test_overlay_pitch_options_empty_for_unknown_pitcher():
    from app.data import bullpen_video as BV
    assert BV.overlay_pitch_options(-987654321, "2026-01-01", "2026-12-31").empty
    assert BV.overlay_pitches([]) == []
