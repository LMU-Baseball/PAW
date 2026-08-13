"""Home-grown xBA model (app/data/xba.py) — pure/DB-free tests.

The lookup is built from a tiny synthetic InPlay frame (never the live DB):
`_build_lookup_from_df` is pure, and `p_hit`/`xba_hit_prob_sum` accept an
optional `lookup=` override so callers can inject a lookup built from a
fixture instead of the process-cached, DB-backed one.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.data import xba


# --------------------------- fixtures -------------------------------------

def _bip_row(exit_speed, angle, hit):
    """One synthetic raw batted-ball row (ExitSpeed/Angle/PitchCall/PlayResult
    naming, matching the dedicated GAMES query `_raw_batted_balls` reads)."""
    return {
        "ExitSpeed": exit_speed,
        "Angle": angle,
        "PitchCall": "InPlay",
        "PlayResult": "Single" if hit else "Out",
    }


@pytest.fixture
def synthetic_raw_df():
    """A synthetic LMU InPlay frame with several EV x LA regions:

      - hard-hit line drives (~95-100 mph, ~10-20 deg): mostly hits (95%),
        large N.
      - weak grounders (~65-75 mph, ~-25..-15 deg): mostly outs, large N.
      - routine popups (~75-85 mph, ~55-65 deg): mostly outs, large N.
      - one tiny-sample cell (95-100 mph, 40-45 deg): 2 balls in play, both
        hits -- exercises the smoothing requirement (must not surface as a
        raw 100%).

    Every band has a large-N mix of hits/outs so no marginal used in
    smoothing is itself degenerate (exactly 0.0 or 1.0).
    """
    rows = []
    # Hard-hit line drives: 40 rows, 38 hits (95%).
    for i in range(40):
        rows.append(_bip_row(95 + (i % 5), 10 + (i % 10), hit=(i % 20 != 0)))
    # Weak grounders: 40 rows, 6 hits (15%).
    for i in range(40):
        rows.append(_bip_row(65 + (i % 10), -25 + (i % 10), hit=(i % 7 == 0)))
    # Routine popups: 40 rows, 4 hits (10%).
    for i in range(40):
        rows.append(_bip_row(75 + (i % 10), 55 + (i % 10), hit=(i % 10 == 0)))
    # Tiny-sample cell: 2 balls in play, both hits.
    rows.append(_bip_row(96, 41, hit=True))
    rows.append(_bip_row(97, 43, hit=True))
    return pd.DataFrame(rows)


@pytest.fixture
def lookup(synthetic_raw_df):
    return xba._build_lookup_from_df(synthetic_raw_df)


@pytest.fixture
def degenerate_edge_df():
    """A large, well-mixed background band (so the global rate is a real,
    interior mix, not 0/1) plus two single-ball EV bands at the high-EV
    tail -- each ball is the ONLY occupant of its EV band, so that band's
    raw (unsmoothed) marginal would be exactly 1.0 or 0.0. Exercises the
    Fix-round-1 requirement that a sparse/one-sided EV band can't drag a
    tiny cell to an exact 0.0/1.0 via level-1 shrinkage.
    """
    rows = []
    for i in range(60):
        rows.append(_bip_row(85 + (i % 10), i % 10, hit=(i % 3 == 0)))
    # Sole occupant of EV bin [115,120): a hit. Raw band marginal = 1.0.
    rows.append(_bip_row(118, 10, hit=True))
    # Sole occupant of EV bin [120,125): an out. Raw band marginal = 0.0.
    rows.append(_bip_row(123, 10, hit=False))
    return pd.DataFrame(rows)


@pytest.fixture
def edge_boundary_df():
    """Two adjacent EV bands with clearly different hit rates, straddling
    the 100.0 mph bin edge, to check which bin an exact-edge value keys
    into."""
    rows = []
    for i in range(30):  # [95,100): mostly outs
        rows.append(_bip_row(95 + (i % 5), 10, hit=(i % 10 == 0)))
    for i in range(30):  # [100,105): mostly hits
        rows.append(_bip_row(100 + (i % 5), 10, hit=(i % 10 != 0)))
    return pd.DataFrame(rows)


# --------------------------- _build_lookup_from_df -------------------------

def test_lookup_probabilities_all_in_unit_interval(lookup):
    assert 0.0 <= lookup.fallback <= 1.0
    for p in lookup.cell_rates.values():
        assert 0.0 <= p <= 1.0


def test_smoothing_tiny_sample_never_exactly_zero_or_one(lookup):
    key = (xba._bin_start(96, xba.EV_BIN_SIZE), xba._bin_start(41, xba.LA_BIN_SIZE))
    assert key in lookup.cell_rates
    p = lookup.cell_rates[key]
    assert p != 0.0
    assert p != 1.0
    # Shrunk off the raw 2-for-2 (100%), even though the EV-95 marginal is
    # itself high (that band is mostly hard-hit line drives).
    assert p < 0.99


def test_large_sample_cell_rate_close_to_raw_rate(lookup):
    # Hard-hit line-drive cell(s) should land near the ~85% raw hit rate,
    # not be dragged far off by shrinkage (n=40 dominates k=MIN_SAMPLE=20).
    key = (xba._bin_start(95, xba.EV_BIN_SIZE), xba._bin_start(10, xba.LA_BIN_SIZE))
    assert key in lookup.cell_rates
    assert lookup.cell_rates[key] > 0.6


def test_thin_ev_band_all_hit_cell_not_exactly_one(degenerate_edge_df):
    """Fix round 1: a single-ball, all-hit EV band's raw marginal is 1.0,
    but level-1 shrinkage must pull it (and the cell built from it) off the
    exact boundary before level-2 sees it."""
    lu = xba._build_lookup_from_df(degenerate_edge_df)
    key = (xba._bin_start(118, xba.EV_BIN_SIZE), xba._bin_start(10, xba.LA_BIN_SIZE))
    assert key in lu.cell_rates
    assert lu.cell_rates[key] < 1.0


def test_thin_ev_band_all_out_cell_not_exactly_zero(degenerate_edge_df):
    """Fix round 1: the mirror case -- a single-ball, all-out EV band's raw
    marginal is 0.0, must not propagate to an exact 0.0 cell rate."""
    lu = xba._build_lookup_from_df(degenerate_edge_df)
    key = (xba._bin_start(123, xba.EV_BIN_SIZE), xba._bin_start(10, xba.LA_BIN_SIZE))
    assert key in lu.cell_rates
    assert lu.cell_rates[key] > 0.0


def test_exact_bin_edge_value_falls_in_upper_bin(edge_boundary_df):
    """EV exactly 100.0 must key into [100,105), not [95,100)."""
    lu = xba._build_lookup_from_df(edge_boundary_df)
    lower_key = (95.0, xba._bin_start(10, xba.LA_BIN_SIZE))
    upper_key = (100.0, xba._bin_start(10, xba.LA_BIN_SIZE))
    assert lu.cell_rates[lower_key] < 0.5    # lower band mostly outs
    assert lu.cell_rates[upper_key] > 0.5    # upper band mostly hits
    assert xba._bin_start(100.0, xba.EV_BIN_SIZE) == 100.0
    edge_p = xba.p_hit(100.0, 10, lookup=lu)
    assert edge_p == pytest.approx(lu.cell_rates[upper_key])
    assert edge_p != pytest.approx(lu.cell_rates[lower_key])


# --------------------------- p_hit -----------------------------------------

def test_p_hit_ordering_sanity(lookup):
    hard_hit = xba.p_hit(100, 15, lookup=lookup)
    weak_grounder = xba.p_hit(70, -20, lookup=lookup)
    popup = xba.p_hit(80, 60, lookup=lookup)

    assert 0.0 <= hard_hit <= 1.0
    assert 0.0 <= weak_grounder <= 1.0
    assert 0.0 <= popup <= 1.0
    assert hard_hit > weak_grounder
    assert hard_hit > popup


def test_p_hit_missing_value_falls_back_to_global_rate(lookup):
    assert xba.p_hit(None, 15, lookup=lookup) == lookup.fallback
    assert xba.p_hit(95, None, lookup=lookup) == lookup.fallback
    assert xba.p_hit(np.nan, np.nan, lookup=lookup) == lookup.fallback


def test_p_hit_out_of_lookup_range_falls_back_to_global_rate(lookup):
    # Nothing near 250 mph / 89 deg exists in the synthetic fixture.
    assert xba.p_hit(250, 89, lookup=lookup) == lookup.fallback


def test_p_hit_clamped_to_unit_interval(lookup):
    assert 0.0 <= xba.p_hit(97, 12, lookup=lookup) <= 1.0


def test_empty_source_frame_uses_default_fallback():
    empty_df = pd.DataFrame({"ExitSpeed": [], "Angle": [], "PitchCall": [], "PlayResult": []})
    empty_lookup = xba._build_lookup_from_df(empty_df)
    assert empty_lookup.cell_rates == {}
    assert empty_lookup.fallback == xba.DEFAULT_FALLBACK_HIT_RATE
    assert xba.p_hit(100, 15, lookup=empty_lookup) == xba.DEFAULT_FALLBACK_HIT_RATE
    # Any input -- even in-range-looking EV/LA -- falls back since there are
    # no cells at all.
    assert xba.p_hit(70, -20, lookup=empty_lookup) == xba.DEFAULT_FALLBACK_HIT_RATE


# --------------------------- xba_hit_prob_sum -------------------------------

def test_xba_hit_prob_sum_matches_manual_sum(lookup):
    df = pd.DataFrame({
        "exit_speed": [100.0, 70.0, 80.0],
        "la": [15.0, -20.0, 60.0],
    })
    expected = sum(xba.p_hit(ev, la, lookup=lookup)
                    for ev, la in zip(df["exit_speed"], df["la"]))
    assert xba.xba_hit_prob_sum(df, lookup=lookup) == pytest.approx(expected)


def test_xba_hit_prob_sum_missing_ev_uses_fallback_not_dropped(lookup):
    df = pd.DataFrame({
        "exit_speed": [100.0, np.nan, 70.0],
        "la": [15.0, np.nan, -20.0],
    })
    total = xba.xba_hit_prob_sum(df, lookup=lookup)
    hard_hit = xba.p_hit(100.0, 15.0, lookup=lookup)
    weak = xba.p_hit(70.0, -20.0, lookup=lookup)
    expected = hard_hit + lookup.fallback + weak
    assert total == pytest.approx(expected)
    # Confirms the NaN row contributed the fallback rather than being skipped.
    assert total > hard_hit + weak


def test_xba_hit_prob_sum_empty_df_is_zero(lookup):
    df = pd.DataFrame({"exit_speed": [], "la": []})
    assert xba.xba_hit_prob_sum(df, lookup=lookup) == 0.0


# --------------------------- cached global lookup ---------------------------

def test_get_lookup_builds_once_and_is_cached(monkeypatch, synthetic_raw_df):
    calls = {"n": 0}

    def fake_raw():
        calls["n"] += 1
        return synthetic_raw_df

    monkeypatch.setattr(xba, "_raw_batted_balls", fake_raw)
    xba._get_lookup.cache_clear()
    try:
        first = xba._get_lookup()
        second = xba._get_lookup()
        assert calls["n"] == 1          # built once, served from cache on 2nd call
        assert first is second or first.cell_rates == second.cell_rates
    finally:
        xba._get_lookup.cache_clear()   # don't leak a fixture-built lookup


def test_p_hit_default_uses_cached_global_lookup(monkeypatch, synthetic_raw_df):
    monkeypatch.setattr(xba, "_raw_batted_balls", lambda: synthetic_raw_df)
    xba._get_lookup.cache_clear()
    try:
        assert xba.p_hit(100, 15) > xba.p_hit(70, -20)
    finally:
        xba._get_lookup.cache_clear()
