"""SLAA / SL+ aggregation. DB-free: every test injects a lookup."""
import pandas as pd

from app.data import called_strike as cs
from app.data import catching_caps


def _frame(rows):
    return pd.DataFrame(rows, columns=["plate_loc_side", "plate_loc_height", "pitch_call"])


def _lookup_half():
    """Every populated cell sits at ~0.5 after smoothing."""
    rows = [(0.0, 2.5, "StrikeCalled")] * 50 + [(0.0, 2.5, "BallCalled")] * 50
    return cs._build_lookup_from_df(_frame(rows))


def test_average_catcher_scores_slaa_near_zero():
    lk = _lookup_half()
    rows = [(0.0, 2.5, "StrikeCalled")] * 50 + [(0.0, 2.5, "BallCalled")] * 50
    out = catching_caps.slaa_summary(_frame(rows), lookup=lk)
    assert out["taken"] == 100
    assert abs(out["slaa"]) < 1.0


def test_catcher_who_steals_everything_has_positive_slaa():
    lk = _lookup_half()
    out = catching_caps.slaa_summary(
        _frame([(0.0, 2.5, "StrikeCalled")] * 100), lookup=lk)
    assert out["slaa"] > 40
    assert out["sl_plus"] > 100


def test_catcher_who_loses_everything_has_negative_slaa():
    lk = _lookup_half()
    out = catching_caps.slaa_summary(
        _frame([(0.0, 2.5, "BallCalled")] * 100), lookup=lk)
    assert out["slaa"] < -40
    assert out["sl_plus"] < 100


def test_sl_plus_is_none_below_the_sample_floor():
    lk = _lookup_half()
    n = catching_caps.SL_PLUS_MIN_TAKEN - 1
    out = catching_caps.slaa_summary(_frame([(0.0, 2.5, "StrikeCalled")] * n), lookup=lk)
    assert out["sl_plus"] is None
    assert out["slaa"] is not None, "SLAA is a difference and must survive a small n"


def test_sl_plus_appears_at_exactly_the_floor():
    lk = _lookup_half()
    n = catching_caps.SL_PLUS_MIN_TAKEN
    out = catching_caps.slaa_summary(_frame([(0.0, 2.5, "StrikeCalled")] * n), lookup=lk)
    assert out["sl_plus"] is not None


def test_non_taken_pitches_are_excluded():
    lk = _lookup_half()
    rows = [(0.0, 2.5, "StrikeCalled")] * 10 + [(0.0, 2.5, "InPlay")] * 90
    out = catching_caps.slaa_summary(_frame(rows), lookup=lk)
    assert out["taken"] == 10


def test_taken_pitches_with_missing_location_are_excluded():
    """A taken pitch that can't be placed on the plate can't be scored by a
    location-conditioned model -- it must not silently count via the
    fallback rate (mirrors called_strike._raw_taken_pitches()'s own
    NOT NULL convention on the model's training data)."""
    lk = _lookup_half()
    rows = [(0.0, 2.5, "StrikeCalled")] * 50 + [(0.0, 2.5, "BallCalled")] * 50
    rows += [(None, 2.5, "StrikeCalled")] * 5
    rows += [(0.0, None, "BallCalled")] * 5
    rows += [(None, None, "StrikeCalled")] * 5
    out = catching_caps.slaa_summary(_frame(rows), lookup=lk)
    assert out["taken"] == 100
    assert out["actual"] == 50


def test_empty_frame_returns_zeroed_summary_without_raising():
    out = catching_caps.slaa_summary(_frame([]), lookup=_lookup_half())
    assert out["taken"] == 0
    assert out["sl_plus"] is None


def test_compute_slaa_season_rollup_shape(monkeypatch):
    """The precalc-bound rollup dict must carry catcher_id, catcher_name,
    slaa, sl_plus, taken, and season_label -- everything
    slaa_season_tiles needs to read back without a live compute."""
    import pandas as pd
    from app.data import catching_caps

    def fake_range_pitches_for(cid, start, end):
        return pd.DataFrame(
            [(0.0, 2.5, "StrikeCalled")] * 100,
            columns=["plate_loc_side", "plate_loc_height", "pitch_call"])
    monkeypatch.setattr(catching_caps, "range_pitches_for", fake_range_pitches_for)
    monkeypatch.setattr(catching_caps, "catcher_name", lambda cid: "Test Catcher")

    out = catching_caps._compute_slaa_season_rollup(1, season="2025/2026")
    assert out["catcher_id"] == 1
    assert out["catcher_name"] == "Test Catcher"
    assert out["season_label"] == "2025/2026"
    assert out["taken"] == 100
    assert "slaa" in out and "sl_plus" in out


def test_slaa_season_tiles_with_no_range_defaults_to_current_season_window(monkeypatch):
    """Fix-round-1: with season/start/end all None (the dashboard's initial
    paint), slaa_season_tiles must resolve the window via
    seasons.current_season()/season_bounds() -- same as framing_season_tiles
    -- NOT pass start=None, end=None straight through to range_pitches_for
    (which used to bind literal 'None' strings into the SQL BETWEEN clause
    and silently match zero rows).

    Task 5: `slaa_season_tiles` now reads precalc first for the season-
    default view, so `precalc.read_catching_season` is monkeypatched to
    return None here -- forcing the live-compute fallback this test is
    actually exercising."""
    from app.data import seasons, precalc
    monkeypatch.setattr(seasons, "current_season", lambda: "2025/2026")
    monkeypatch.setattr(precalc, "read_catching_season", lambda cid, season=None: None)
    calls = []

    def _fake_range_pitches_for(c, s, e):
        calls.append((c, s, e))
        return pd.DataFrame(columns=["plate_loc_side", "plate_loc_height", "pitch_call"])

    monkeypatch.setattr(catching_caps, "range_pitches_for", _fake_range_pitches_for)
    catching_caps.slaa_season_tiles(1)
    assert len(calls) == 1
    cid, start, end = calls[0]
    assert cid == 1
    assert (start, end) == seasons.season_bounds(seasons.current_season())
    assert "None" not in (str(start), str(end))
