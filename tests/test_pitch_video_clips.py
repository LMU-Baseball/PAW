"""scripts/pitch_video_clips.py: piecewise-linear correction, segment
discovery, and Trackman-CSV lookup -- the pure-logic pieces. No live SFTP
or ffmpeg calls here, matching this repo's existing ingest-loader test
convention (see app/ingest/connections.py's own docstring)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from scripts.pitch_video_clips import (
    Segment,
    build_corrector,
    confidence_flag,
    find_game_csv,
    locate_segment,
    safe_filename_part,
    segment_windows,
)


# ---------------------------------------------------------------------------
# build_corrector
# ---------------------------------------------------------------------------

def test_corrector_exact_at_anchors():
    f = build_corrector([(100.0, 110.0), (200.0, 195.0)])
    assert f(100.0) == pytest.approx(110.0)
    assert f(200.0) == pytest.approx(195.0)


def test_corrector_interpolates_between_two_anchors():
    f = build_corrector([(0.0, 0.0), (100.0, 200.0)])
    assert f(50.0) == pytest.approx(100.0)  # 2x slope, halfway


def test_corrector_piecewise_uses_local_slope_not_global():
    # Segment 1's real finding: drift swings +15.6 -> -8.2 -> +15.9 across
    # three real anchors -- not monotonic, not a single global rate.
    f = build_corrector([(658.57, 674.2), (717.19, 709.2), (812.08, 828.2)])
    # Between anchor 2 and 3, true time runs FASTER than nominal (positive
    # slope > 1); a naive single-slope fit across all three would get this
    # midpoint wrong.
    mid = f(760.0)
    assert 709.2 < mid < 828.2


def test_corrector_extrapolates_below_first_anchor_using_first_segment_slope():
    f = build_corrector([(100.0, 110.0), (200.0, 130.0)])  # slope 0.2
    assert f(50.0) == pytest.approx(110.0 + 0.2 * (50.0 - 100.0))


def test_corrector_extrapolates_above_last_anchor_using_last_segment_slope():
    f = build_corrector([(100.0, 110.0), (200.0, 130.0)])  # slope 0.2
    assert f(300.0) == pytest.approx(130.0 + 0.2 * (300.0 - 200.0))


def test_corrector_extrapolation_does_not_clamp_like_bare_np_interp():
    # The bug this was built to catch: two pitches past the last anchor
    # must NOT land on the same corrected position.
    f = build_corrector([(100.0, 110.0), (200.0, 130.0)])
    assert f(250.0) != f(300.0)


def test_corrector_requires_at_least_one_anchor():
    with pytest.raises(ValueError):
        build_corrector([])


def test_corrector_single_anchor_is_a_flat_constant_shift():
    # One anchor per segment is enough to run the whole tool -- this is
    # what makes that possible: apply that one pitch's drift everywhere
    # in the segment, not just at the anchor itself.
    f = build_corrector([(658.57, 674.2)])  # true - nominal = +15.63
    shift = 674.2 - 658.57
    assert f(658.57) == pytest.approx(674.2)
    assert f(0.0) == pytest.approx(0.0 + shift)
    assert f(1000.0) == pytest.approx(1000.0 + shift)


# ---------------------------------------------------------------------------
# segment_windows
# ---------------------------------------------------------------------------

def _touch(path, mtime_epoch):
    with open(path, "w") as fh:
        fh.write("x")
    os.utime(path, (mtime_epoch, mtime_epoch))


def test_segment_windows_chains_from_previous_segments_mtime(tmp_path):
    import datetime as dt

    day = dt.date.today()

    def at(h, m, s):
        return dt.datetime(day.year, day.month, day.day, h, m, s).timestamp()

    _touch(tmp_path / "Angle_01.mp4", at(18, 12, 36))
    _touch(tmp_path / "Angle_02.mp4", at(18, 30, 36))

    segs = segment_windows(str(tmp_path), "Angle_", duration_fn=lambda _p: 18 * 60)

    assert [s.filename for s in segs] == ["Angle_01.mp4", "Angle_02.mp4"]
    assert segs[0].end == pytest.approx(18 * 3600 + 12 * 60 + 36)
    assert segs[0].start == pytest.approx(segs[0].end - 18 * 60)
    # segment 2 starts exactly where segment 1's mtime says it ended --
    # this is the "naive" chain that locate_segment relies on for finding
    # which FILE a pitch is in (accurate); within-segment position needs
    # the anchors file (this chain is NOT accurate for that).
    assert segs[1].start == pytest.approx(segs[0].end)
    assert segs[1].end == pytest.approx(18 * 3600 + 30 * 60 + 36)


def test_segment_windows_raises_when_no_files_match(tmp_path):
    with pytest.raises(FileNotFoundError):
        segment_windows(str(tmp_path), "Nonexistent_")


# ---------------------------------------------------------------------------
# locate_segment
# ---------------------------------------------------------------------------

def test_locate_segment_finds_containing_window():
    segs = [Segment("a.mp4", 0.0, 100.0), Segment("b.mp4", 100.0, 200.0)]
    seg, nominal = locate_segment(150.0, segs)
    assert seg.filename == "b.mp4"
    assert nominal == pytest.approx(50.0)


def test_locate_segment_returns_none_outside_every_window():
    segs = [Segment("a.mp4", 0.0, 100.0)]
    seg, nominal = locate_segment(500.0, segs)
    assert seg is None
    assert nominal is None


# ---------------------------------------------------------------------------
# confidence_flag -- the "flag a couple errors" mechanism: confidence in
# the timing math, not after-the-fact pixel analysis of the cut clip (that
# was tried and rejected -- a known-wrong clip and a known-right one, a
# routine take with low visual contrast, scored nearly identically).
# ---------------------------------------------------------------------------

def test_confidence_flag_none_when_well_anchored_and_not_first_segment():
    anchors = [(100.0, 110.0), (200.0, 195.0)]
    assert confidence_flag(150.0, anchors, is_first_segment=False) is None


def test_confidence_flag_flags_zero_anchors():
    reason = confidence_flag(150.0, [], is_first_segment=False)
    assert reason is not None and "no anchor" in reason


def test_confidence_flag_flags_single_anchor_segment():
    reason = confidence_flag(150.0, [(100.0, 110.0)], is_first_segment=False)
    assert reason is not None and "1 anchor" in reason


def test_confidence_flag_flags_far_from_nearest_anchor():
    anchors = [(0.0, 10.0), (1000.0, 990.0)]
    reason = confidence_flag(500.0, anchors, is_first_segment=False, gap_threshold=60.0)
    assert reason is not None and "nearest anchor" in reason


def test_confidence_flag_single_anchor_never_gets_a_redundant_distance_flag():
    # Regression: a first cut of this function applied the "far from
    # nearest anchor" check even with only 1 anchor -- since most of an
    # 18-minute segment is trivially >60s from one point, that flagged
    # nearly the entire real game when smoke-tested. "1 anchor" alone is
    # the whole story for a single-anchor segment; a distance number on
    # top of it is noise, not signal.
    reason = confidence_flag(900.0, [(50.0, 60.0)], is_first_segment=False)
    assert "nearest anchor" not in reason
    assert reason == "only 1 anchor in this segment (flat constant-shift assumption)"


def test_confidence_flag_flags_first_segment_even_when_well_anchored():
    anchors = [(100.0, 110.0), (200.0, 195.0)]
    reason = confidence_flag(150.0, anchors, is_first_segment=True)
    assert reason is not None and "first segment" in reason


def test_confidence_flag_can_combine_multiple_reasons():
    reason = confidence_flag(150.0, [(100.0, 110.0)], is_first_segment=True)
    assert "1 anchor" in reason and "first segment" in reason


# ---------------------------------------------------------------------------
# safe_filename_part
# ---------------------------------------------------------------------------

def test_safe_filename_part_strips_unsafe_characters():
    assert safe_filename_part("Frize, Drake") == "Frize__Drake"
    assert safe_filename_part("O'Brien/Jr.") == "O_Brien_Jr_"


# ---------------------------------------------------------------------------
# find_game_csv -- pure string/path logic, fake sftp client (no network)
# ---------------------------------------------------------------------------

class _FakeSftp:
    def __init__(self, listings: dict):
        self._listings = listings

    def listdir(self, path):
        if path not in self._listings:
            raise OSError(f"no such directory: {path}")
        return self._listings[path]


def test_find_game_csv_matches_on_game_date_folder():
    sftp = _FakeSftp({"/v3/2026/05/15/CSV": ["20260515-UofSanDiego-2.csv"]})
    found = find_game_csv(sftp, "2026-05-15", "UofSanDiego", game_num=2)
    assert found == "/v3/2026/05/15/CSV/20260515-UofSanDiego-2.csv"


def test_find_game_csv_searches_forward_when_upload_lagged(monkeypatch=None):
    # Real-world case this guards: the 2026-05-15 game actually uploaded to
    # the 05-16 folder, one day late.
    sftp = _FakeSftp({"/v3/2026/05/16/CSV": ["20260515-UofSanDiego-2.csv"]})
    found = find_game_csv(sftp, "2026-05-15", "UofSanDiego", game_num=2)
    assert found == "/v3/2026/05/16/CSV/20260515-UofSanDiego-2.csv"


def test_find_game_csv_returns_none_when_not_found_in_window():
    sftp = _FakeSftp({"/v3/2026/05/15/CSV": ["some-other-game-1.csv"]})
    found = find_game_csv(sftp, "2026-05-15", "UofSanDiego", game_num=2)
    assert found is None
