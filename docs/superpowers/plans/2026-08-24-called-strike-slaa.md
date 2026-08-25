# Expected Called Strikes, SLAA and SL+ — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the catching coach a per-pitch expected-called-strike model, and surface SLAA, SL+, and a by-location breakdown on the catching dashboard.

**Architecture:** One new isolated module, `app/data/called_strike.py`, holds a 2-D empirical lookup of P(called strike) keyed by binned plate location, built from all teams' taken pitches and smoothed exactly the way `app/data/xba.py` smooths its EV×LA lookup. `app/data/catching_caps.py` gains SLAA/SL+ aggregation over a catcher's pitches; the dashboard gains two sidebar tiles and one heat map. Nothing existing is removed.

**Tech Stack:** Python 3.12, pandas, numpy, SQLAlchemy (`app.db.query_df`), Dash + Plotly, pytest.

**Spec:** `docs/superpowers/specs/2026-08-24-called-strike-slaa-design.md`

## Global Constraints

- **Training population is ALL TEAMS' taken pitches** — `PitchCall IN ('StrikeCalled','BallCalled')` with both location columns populated. Do NOT filter to LMU. SLAA means "above average", so the baseline must be neutral.
- **Location-only conditioning.** No batter-side or count split in v1.
- **Lookup cells MUST be keyed by a tuple** whose arity can grow later (a batter-side dimension is a likely v2). Never key by a packed scalar or by two positional args that hard-assume 2-D.
- **Clip coordinates into the modelling window before binning. Do NOT copy `xba.py`'s global-rate fallback for out-of-range values.** A pitch 3 ft outside must get a near-zero probability, not the global 32.46%; otherwise catchers are credited free expected strikes on balls in the dirt.
- **Smoothing must guarantee no cell is ever exactly 0.0 or 1.0**, even at n=1.
- **SL+ sample-size floor is 100 taken pitches.** Below it, show `—`. SLAA is a difference, not a ratio, and is shown at any n.
- SL+ convention: `100 × actual / expected`; 100 is average, higher is better.
- Existing STRIKES / STRIKES LOST tiles and `add_framing_cols` are **unchanged**.
- The full suite must stay green: `python -m pytest -q --ignore=tests/test_precalc.py` (903 passing before this work).
- Use `python -m pytest`, not bare `pytest`. Windows; Git Bash available.

---

### Task 1: The called-strike probability model

**Files:**
- Create: `app/data/called_strike.py`
- Test: `tests/test_called_strike.py` (create)

**Interfaces:**
- Consumes: `app.data.cache.cached`, `app.db.query_df` (existing).
- Produces, relied on by Tasks 2 and 4:
  - `SIDE_BIN_SIZE: float = 0.15`, `HEIGHT_BIN_SIZE: float = 0.15`
  - `SIDE_MIN/-MAX = -2.0/2.0`, `HEIGHT_MIN/-MAX = 0.0/5.0`
  - `_Lookup` frozen dataclass with `.cell_rates: dict[tuple, float]` and `.fallback: float`
  - `_build_lookup_from_df(df: pd.DataFrame) -> _Lookup` — DB-free seam for tests
  - `p_called_strike(side, height, *, lookup: _Lookup | None = None) -> float`
  - `expected_called_strikes(df: pd.DataFrame, *, lookup=None) -> pd.Series` — indexed like `df`
  - `is_taken(df) -> pd.Series[bool]`, `is_called_strike(df) -> pd.Series[bool]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_called_strike.py`:

```python
"""Called-strike probability model. DB-free: every test injects a lookup."""
import numpy as np
import pandas as pd
import pytest

from app.data import called_strike as cs


def _frame(rows):
    """rows = [(side, height, pitch_call), ...] -> a taken-pitch frame."""
    return pd.DataFrame(rows, columns=["plate_loc_side", "plate_loc_height", "pitch_call"])


def _uniform_lookup(rate=0.5):
    """A lookup where every populated cell has the same rate."""
    df = _frame([(0.0, 2.5, "StrikeCalled"), (0.0, 2.5, "BallCalled")])
    lk = cs._build_lookup_from_df(df)
    return lk


def test_single_observation_cell_is_never_exactly_zero_or_one():
    """An n=1 all-strike cell must not read as a literal 100%."""
    lk = cs._build_lookup_from_df(_frame([
        (0.0, 2.5, "StrikeCalled"),
        (1.9, 0.2, "BallCalled"),
    ]))
    p = cs.p_called_strike(0.0, 2.5, lookup=lk)
    assert 0.0 < p < 1.0


def test_far_outside_pitch_gets_near_zero_not_global_rate():
    """REGRESSION GUARD for the clipping decision.

    xba.py falls back to the GLOBAL rate for out-of-range inputs. Doing that
    here would hand a catcher ~32% expected strike probability on a pitch in
    the dirt. Clipping must map it to the edge bin instead, whose empirical
    rate is near zero.
    """
    rows = [(0.0, 2.5, "StrikeCalled")] * 50          # heart of the zone
    rows += [(-1.95, 0.05, "BallCalled")] * 50        # extreme edge, all balls
    lk = cs._build_lookup_from_df(_frame(rows))
    p_far = cs.p_called_strike(-8.0, -4.0, lookup=lk)   # way outside, clipped to edge
    assert p_far < 0.10, f"far-outside pitch got {p_far}, expected near zero"
    assert p_far < lk.fallback


def test_clipping_maps_out_of_window_to_the_same_cell_as_the_edge():
    lk = cs._build_lookup_from_df(_frame([
        (0.0, 2.5, "StrikeCalled"), (1.9, 0.1, "BallCalled")]))
    assert cs.p_called_strike(50.0, 99.0, lookup=lk) == cs.p_called_strike(
        cs.SIDE_MAX, cs.HEIGHT_MAX, lookup=lk)


def test_empty_frame_builds_a_lookup_and_does_not_raise():
    lk = cs._build_lookup_from_df(_frame([]))
    assert 0.0 < cs.p_called_strike(0.0, 2.5, lookup=lk) < 1.0


def test_missing_location_falls_back_without_raising():
    lk = _uniform_lookup()
    assert 0.0 <= cs.p_called_strike(np.nan, 2.5, lookup=lk) <= 1.0
    assert 0.0 <= cs.p_called_strike(0.0, None, lookup=lk) <= 1.0


def test_cell_keys_are_tuples_so_a_dimension_can_be_added_later():
    lk = cs._build_lookup_from_df(_frame([(0.0, 2.5, "StrikeCalled")]))
    assert all(isinstance(k, tuple) and len(k) == 2 for k in lk.cell_rates)


def test_expected_called_strikes_is_indexed_like_the_input():
    lk = _uniform_lookup()
    df = _frame([(0.0, 2.5, "StrikeCalled"), (0.5, 2.0, "BallCalled")])
    df.index = [7, 9]
    out = cs.expected_called_strikes(df, lookup=lk)
    assert list(out.index) == [7, 9]
    assert ((out >= 0.0) & (out <= 1.0)).all()


def test_expected_called_strikes_on_empty_frame_is_empty():
    out = cs.expected_called_strikes(_frame([]), lookup=_uniform_lookup())
    assert out.empty


def test_is_taken_and_is_called_strike():
    df = _frame([(0, 2, "StrikeCalled"), (0, 2, "BallCalled"), (0, 2, "InPlay")])
    assert list(cs.is_taken(df)) == [True, True, False]
    assert list(cs.is_called_strike(df)) == [True, False, False]


def test_heart_of_zone_scores_higher_than_the_edge():
    rows = [(0.0, 2.5, "StrikeCalled")] * 80
    rows += [(1.8, 0.3, "BallCalled")] * 80
    lk = cs._build_lookup_from_df(_frame(rows))
    assert cs.p_called_strike(0.0, 2.5, lookup=lk) > cs.p_called_strike(1.8, 0.3, lookup=lk)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_called_strike.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.data.called_strike'`

- [ ] **Step 3: Implement `app/data/called_strike.py`**

```python
"""Expected called strikes: P(called strike) as a 2-D plate-location lookup.

Model
-----
A 2-D lookup keyed by (side_bin, height_bin), where each cell holds the
empirical P(called strike) among TAKEN pitches (`PitchCall` of
'StrikeCalled' or 'BallCalled') that landed in that cell. Source population
is ALL TEAMS' taken pitches, not just LMU's -- SLAA means "above average",
so the baseline has to be a neutral league/umpire-average zone rather than
LMU's own receivers. It is also far denser at the zone edge, which is
exactly where framing is decided.

Clipping (differs from xba.py ON PURPOSE -- do not "fix" this)
--------------------------------------------------------------
`xba.py` falls back to the GLOBAL rate for out-of-range inputs. Copying that
here would be a real bug: a pitch three feet outside, which no umpire has
ever called a strike, would be assigned the global ~32% probability. Summed
over a season that hands every catcher a pile of free expected strikes on
balls in the dirt and systematically deflates SLAA for good receivers.
Instead, coordinates are CLIPPED into the modelling window before binning,
so a wild pitch maps to an edge cell whose empirical rate is near zero.

Smoothing (two-level empirical-Bayes, mirroring xba.py)
-------------------------------------------------------
    cell_rate = (cell_strikes + k * band_marginal) / (cell_n + k)

where `band_marginal` is that height band's own rate, itself first smoothed
toward the global called-strike rate so a sparse one-sided band cannot
anchor a cell at exactly 0 or 1. This matters more here than for xBA: the
zone edge is simultaneously where framing is decided and where cells are
thinnest, so an unsmoothed 1-for-1 cell reading as a literal 100% would
corrupt precisely the pitches the metric exists to measure.

Cell keys are TUPLES so a batter-side dimension can be added later (see the
spec's "Accepted limitation") without restructuring this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.data.cache import cached
from app.db import query_df

# --- binning ---------------------------------------------------------------
# 0.15 ft = 1.8 in. Measured against the live data: 952 populated cells,
# median 56 taken pitches per cell, only 7% of cells below n=10 -- and still
# finer than a baseball's 2.9 in diameter, so the zone edge stays resolvable.
SIDE_BIN_SIZE = 0.15
HEIGHT_BIN_SIZE = 0.15

# Modelling window, in feet. Everything outside is CLIPPED to these bounds
# (see the module docstring).
SIDE_MIN, SIDE_MAX = -2.0, 2.0
HEIGHT_MIN, HEIGHT_MAX = 0.0, 5.0

# Cell shrinkage weight k, and the weight used to smooth a band marginal
# toward the global rate. Same roles as xba.py's MIN_SAMPLE / MARGINAL_SHRINK_K.
MIN_SAMPLE = 20
MARGINAL_SHRINK_K = MIN_SAMPLE

# Used only when an anchor would otherwise be exactly 0.0/1.0 (an empty or
# degenerate source frame). Keeps every shrinkage anchor strictly inside
# (0,1). The measured live global called-strike rate is 0.3246.
DEFAULT_FALLBACK_RATE = 0.3246

TAKEN_CALLS = ("StrikeCalled", "BallCalled")


@dataclass(frozen=True)
class _Lookup:
    """`cell_rates`: {(side_bin, height_bin): smoothed P(called strike)}.
    `fallback`: the global called-strike rate of the source rows, used only
    for missing/NaN coordinates."""
    cell_rates: dict = field(default_factory=dict)
    fallback: float = DEFAULT_FALLBACK_RATE


def _bin_start(value: float, size: float) -> float:
    """Bin-start edge for `value` in a `size`-wide grid, giving half-open
    [start, start+size) cells."""
    return float(np.floor(float(value) / size) * size)


def _cell_key(side: float, height: float) -> tuple:
    """Clip into the modelling window, then bin. Returns a TUPLE so the key
    can gain a dimension later."""
    s = min(SIDE_MAX, max(SIDE_MIN, float(side)))
    h = min(HEIGHT_MAX, max(HEIGHT_MIN, float(height)))
    return (_bin_start(s, SIDE_BIN_SIZE), _bin_start(h, HEIGHT_BIN_SIZE))


def is_taken(df: pd.DataFrame) -> pd.Series:
    """Rows whose pitch was taken (called strike or called ball)."""
    return df["pitch_call"].isin(TAKEN_CALLS)


def is_called_strike(df: pd.DataFrame) -> pd.Series:
    return df["pitch_call"].eq("StrikeCalled")


def _raw_taken_pitches() -> pd.DataFrame:
    """ALL TEAMS' taken pitches with both location columns populated.

    Deliberately NOT scoped to LMU -- see the module docstring.
    """
    return query_df(
        """
        SELECT PlateLocSide AS plate_loc_side,
               PlateLocHeight AS plate_loc_height,
               PitchCall AS pitch_call
          FROM GAMES
         WHERE PitchCall IN ('StrikeCalled', 'BallCalled')
           AND PlateLocSide IS NOT NULL
           AND PlateLocHeight IS NOT NULL
        """
    )


def _build_lookup_from_df(df: pd.DataFrame) -> _Lookup:
    """Pure lookup builder (no DB access) -- the DB-free seam for tests."""
    if df is None or df.empty:
        return _Lookup(cell_rates={}, fallback=DEFAULT_FALLBACK_RATE)

    d = df[df["plate_loc_side"].notna() & df["plate_loc_height"].notna()].copy()
    d = d[is_taken(d)]
    if d.empty:
        return _Lookup(cell_rates={}, fallback=DEFAULT_FALLBACK_RATE)

    d["_cs"] = is_called_strike(d).astype(float)
    keys = [_cell_key(s, h) for s, h in
            zip(d["plate_loc_side"], d["plate_loc_height"])]
    d["_side_bin"] = [k[0] for k in keys]
    d["_height_bin"] = [k[1] for k in keys]

    global_rate = float(d["_cs"].mean())
    anchor = global_rate if 0.0 < global_rate < 1.0 else DEFAULT_FALLBACK_RATE

    # Level 1: smooth each height band's marginal toward the global anchor.
    band = d.groupby("_height_bin")["_cs"].agg(["sum", "count"])
    band_marginal = {
        hb: (row["sum"] + MARGINAL_SHRINK_K * anchor) / (row["count"] + MARGINAL_SHRINK_K)
        for hb, row in band.iterrows()
    }

    # Level 2: smooth each cell toward its already-smoothed band marginal.
    # Because that marginal is strictly in (0,1) and k > 0, no cell can land
    # on exactly 0.0/1.0 for any n, including n=1.
    grouped = d.groupby(["_side_bin", "_height_bin"])["_cs"].agg(["sum", "count"])
    cell_rates: dict = {}
    for (sb, hb), row in grouped.iterrows():
        n = float(row["count"])
        strikes = float(row["sum"])
        marginal = band_marginal.get(hb, anchor)
        smoothed = (strikes + MIN_SAMPLE * marginal) / (n + MIN_SAMPLE)
        cell_rates[(sb, hb)] = float(min(1.0, max(0.0, smoothed)))

    # NOTE: returned from inside a @cached singleton, which only deep-copies
    # DataFrame return values. Treat cell_rates as read-only.
    return _Lookup(cell_rates=cell_rates, fallback=anchor)


@cached
def _get_lookup() -> _Lookup:
    """Process-wide lookup, built once from the live DB and memoized."""
    return _build_lookup_from_df(_raw_taken_pitches())


def p_called_strike(side, height, *, lookup: _Lookup | None = None) -> float:
    """P(called strike) for one taken pitch, clamped to [0,1].

    Coordinates are clipped into the modelling window, so a pitch far outside
    resolves to an edge cell (near-zero rate) rather than the global fallback.
    Only a missing/NaN coordinate uses `lookup.fallback`.
    """
    if lookup is None:
        lookup = _get_lookup()
    if pd.isna(side) or pd.isna(height):
        return float(min(1.0, max(0.0, lookup.fallback)))
    p = lookup.cell_rates.get(_cell_key(side, height), None)
    if p is None:
        # Cell never observed. Fall back to the same height band's average
        # rather than the global rate -- a never-seen cell at the extreme
        # edge should not inherit the (much higher) whole-zone average.
        hb = _cell_key(side, height)[1]
        same_band = [v for (s, h), v in lookup.cell_rates.items() if h == hb]
        p = float(np.mean(same_band)) if same_band else lookup.fallback
    return float(min(1.0, max(0.0, p)))


def expected_called_strikes(df: pd.DataFrame, *, lookup: _Lookup | None = None) -> pd.Series:
    """Per-row P(called strike), indexed like `df`.

    Expects the snake_case column names produced by
    `catching_caps._CATCHER_SELECT` (`plate_loc_side`, `plate_loc_height`).
    """
    if df is None or df.empty:
        return pd.Series(dtype=float)
    if lookup is None:
        lookup = _get_lookup()
    vals = [
        p_called_strike(s, h, lookup=lookup)
        for s, h in zip(df["plate_loc_side"], df["plate_loc_height"])
    ]
    return pd.Series(vals, index=df.index, dtype=float)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_called_strike.py -q`
Expected: 10 passed

- [ ] **Step 5: Sanity-check the model against live data**

Run:
```bash
PYTHONIOENCODING=utf-8 python -c "
from app.data.called_strike import _get_lookup, p_called_strike
lk = _get_lookup()
print('cells:', len(lk.cell_rates), '| fallback: %.4f' % lk.fallback)
print('heart  (0.0, 2.5): %.3f' % p_called_strike(0.0, 2.5, lookup=lk))
print('edge   (0.8, 2.5): %.3f' % p_called_strike(0.8, 2.5, lookup=lk))
print('way out(3.0, 0.2): %.3f' % p_called_strike(3.0, 0.2, lookup=lk))
"
```
Expected: heart-of-zone probability high (>0.8), edge middling, way-outside near zero. **If the way-outside value is anywhere near 0.32, the clipping is not working — stop and fix it.** Paste the real numbers into your report.

- [ ] **Step 6: Commit**

```bash
git add app/data/called_strike.py tests/test_called_strike.py
git commit -m "feat(catching): add the expected called-strike probability model"
```

---

### Task 2: SLAA and SL+ aggregation

**Files:**
- Modify: `app/data/catching_caps.py` (append a new function near `framing_season_tiles`)
- Test: `tests/test_called_strike_metrics.py` (create)

**Interfaces:**
- Consumes from Task 1: `expected_called_strikes(df, *, lookup=None)`, `is_taken(df)`, `is_called_strike(df)`, `_Lookup`, `_build_lookup_from_df`.
- Consumes existing: `catching_caps.range_pitches_for(catcher_id, start, end)`, which returns `_CATCHER_SELECT`'s snake_case columns including `plate_loc_side`, `plate_loc_height`, `pitch_call`.
- Produces, relied on by Tasks 3 and 4:
  - `SL_PLUS_MIN_TAKEN: int = 100`
  - `slaa_summary(df, *, lookup=None) -> dict` with keys `taken` (int), `actual` (int), `expected` (float), `slaa` (float), `sl_plus` (float | None)
  - `slaa_season_tiles(catcher_id, season=None, start=None, end=None) -> dict` with display-ready string keys `slaa`, `sl_plus`, `taken`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_called_strike_metrics.py`:

```python
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


def test_empty_frame_returns_zeroed_summary_without_raising():
    out = catching_caps.slaa_summary(_frame([]), lookup=_lookup_half())
    assert out["taken"] == 0
    assert out["sl_plus"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_called_strike_metrics.py -q`
Expected: FAIL — `AttributeError: module 'app.data.catching_caps' has no attribute 'slaa_summary'`

- [ ] **Step 3: Implement in `app/data/catching_caps.py`**

Add the import at the top of the file, alongside the existing imports:

```python
from app.data import called_strike as _cs
```

Then append these near `framing_season_tiles`:

```python
# SL+ is a ratio and is meaningless on a small denominator. Measured against
# the live data: LMU has 22,577 taken pitches across 24 catchers, so regular
# starters clear 100 within a handful of games while one-game cameo lines --
# exactly the noise this floor suppresses -- do not.
SL_PLUS_MIN_TAKEN = 100


def slaa_summary(df, *, lookup=None) -> dict:
    """SLAA / SL+ over a catcher's pitches.

    SLAA = actual called strikes - expected, in units of strikes: 0 is
    average, +12 means twelve strikes gained beyond what an average receiver
    gets on those same pitches. SL+ = 100 * actual / expected (100 = average,
    higher is better), suppressed to None below SL_PLUS_MIN_TAKEN because a
    ratio on a small denominator will be believed and should not be.

    `df` needs `plate_loc_side`, `plate_loc_height`, `pitch_call` -- i.e. the
    shape `range_pitches_for` already returns.
    """
    empty = {"taken": 0, "actual": 0, "expected": 0.0, "slaa": 0.0, "sl_plus": None}
    if df is None or df.empty:
        return empty
    taken = df[_cs.is_taken(df)]
    if taken.empty:
        return empty

    actual = int(_cs.is_called_strike(taken).sum())
    expected = float(_cs.expected_called_strikes(taken, lookup=lookup).sum())
    n = int(len(taken))
    sl_plus = None
    if n >= SL_PLUS_MIN_TAKEN and expected > 0:
        sl_plus = round(100.0 * actual / expected, 1)
    return {
        "taken": n,
        "actual": actual,
        "expected": round(expected, 1),
        "slaa": round(actual - expected, 1),
        "sl_plus": sl_plus,
    }


def slaa_season_tiles(catcher_id, season=None, start=None, end=None) -> dict:
    """Display-ready SLAA / SL+ / taken-pitch count for the sidebar.

    Mirrors `framing_season_tiles`' scoping so date-range selection behaves
    identically. Returns strings; "—" where a value is unavailable.
    """
    tiles = {"slaa": "—", "sl_plus": "—", "taken": "—"}
    if catcher_id is None:
        return tiles
    df = range_pitches_for(int(catcher_id), start, end)
    if df is None or df.empty:
        return tiles
    s = slaa_summary(df)
    tiles["taken"] = str(s["taken"])
    # Signed, because "+8" and "-8" mean opposite things and a bare "8" is
    # ambiguous at a glance on a tile.
    tiles["slaa"] = f"{s['slaa']:+.1f}"
    tiles["sl_plus"] = "—" if s["sl_plus"] is None else f"{s['sl_plus']:.0f}"
    return tiles
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_called_strike_metrics.py -q`
Expected: 7 passed

- [ ] **Step 5: Check the metric against a real catcher**

Run:
```bash
PYTHONIOENCODING=utf-8 python -c "
from app.data import catching_caps as cc
top = cc.lmu_catchers()
cid = int(top.iloc[0]['catcher_id'])
print('catcher', cid, cc.catcher_name(cid))
print(cc.slaa_summary(cc.range_pitches_for(cid, None, None)))
print(cc.slaa_season_tiles(cid))
"
```
Expected: a plausible line — `taken` in the hundreds or thousands, `slaa` a modest signed number, `sl_plus` near 100. **A |SL+| far from 100 (say 150) or an SLAA of thousands means the model or the join is wrong — stop and investigate.** Paste the real output into your report.

- [ ] **Step 6: Run the neighbouring suites**

Run: `python -m pytest tests/test_catching.py tests/test_catching_caps.py tests/test_catching_dash.py -q`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add app/data/catching_caps.py tests/test_called_strike_metrics.py
git commit -m "feat(catching): add SLAA and SL+ aggregation"
```

---

### Task 3: SLAA and SL+ sidebar tiles

**Files:**
- Modify: `app/dashboards/catching/layout.py` (the sidebar builder around lines 25-45)
- Test: `tests/test_catching_dash.py` (append)

**Interfaces:**
- Consumes from Task 2: `catching_caps.slaa_season_tiles(catcher_id, season, start, end) -> dict` with string keys `slaa`, `sl_plus`, `taken`.
- Produces: no new interface.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_catching_dash.py`, matching that file's existing app-construction fixture style:

```python
def test_sidebar_shows_slaa_and_sl_plus_tiles(monkeypatch):
    """The two new tiles render alongside the existing STRIKES tiles, which
    must survive unchanged."""
    from app.dashboards.catching import layout as cl
    from app.data import catching_caps

    monkeypatch.setattr(catching_caps, "catcher_profile", lambda cid: {
        "photo": None, "jersey": "12", "name": "Test Catcher",
        "class_year": "SR", "position": "C"})
    monkeypatch.setattr(catching_caps, "framing_season_tiles",
                        lambda *a, **k: {"games": "10", "strikes": "40",
                                         "strikes_lost": "12", "cs_pct": "30%"})
    monkeypatch.setattr(catching_caps, "slaa_season_tiles",
                        lambda *a, **k: {"slaa": "+8.4", "sl_plus": "112",
                                         "taken": "640"})
    tree = str(cl.sidebar(1, None, None, None))
    assert "SLAA" in tree
    assert "+8.4" in tree
    assert "SL+" in tree
    assert "112" in tree
    # the pre-existing tiles are untouched
    assert "STRIKES" in tree and "40" in tree
```

Note: check `layout.py` for the sidebar function's real name and signature before writing this — adjust the call to match, and say in your report what it actually is.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_catching_dash.py -k slaa -q`
Expected: FAIL — the tree contains no "SLAA"

- [ ] **Step 3: Wire the tiles into `app/dashboards/catching/layout.py`**

Add `slaa_season_tiles` to the existing `parallel.prefetch(...)` call so it is fetched concurrently with the other two sidebar reads rather than serialising a third DB round trip:

```python
    parallel.prefetch(
        lambda: catching_caps.catcher_profile(int(catcher_id)),
        lambda: catching_caps.framing_season_tiles(int(catcher_id), season, start, end),
        lambda: catching_caps.slaa_season_tiles(int(catcher_id), season, start, end),
    )
```

Then read it alongside the existing `summ`:

```python
    slaa = catching_caps.slaa_season_tiles(int(catcher_id), season, start, end)
```

And add two tiles to the tile row, using the file's existing `_tile` helper:

```python
        _tile("SLAA", slaa["slaa"]),
        _tile("SL+", slaa["sl_plus"]),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_catching_dash.py -k slaa -q`
Expected: PASS

- [ ] **Step 5: Verify the whole catching dashboard still renders**

Run: `python -m pytest tests/test_catching_dash.py tests/test_catching.py -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add app/dashboards/catching/layout.py tests/test_catching_dash.py
git commit -m "feat(catching): show SLAA and SL+ on the catcher sidebar"
```

---

### Task 4: By-location strikes-gained heat map

**Files:**
- Modify: `app/dashboards/catching/charts.py` (add the figure builder)
- Modify: `app/dashboards/catching/tabs/framing.py` (render it)
- Test: `tests/test_catching_dash.py` (append)

**Interfaces:**
- Consumes from Tasks 1-2: `called_strike.expected_called_strikes`, `called_strike.is_taken`, `called_strike.is_called_strike`.
- Produces: `charts.slaa_location_figure(df, *, lookup=None) -> plotly.graph_objects.Figure`

**Display grid (from the spec, deliberately coarser than the model grid).** The model bins at 0.15 ft for resolution; rendering 952 cells per catcher would be unreadable noise, since one catcher has nowhere near enough pitches to fill them. Aggregate into a **7 × 7** grid: a 5 × 5 over the nominal zone plus a one-cell shadow ring.

- Nominal zone: side `[-0.83, 0.83]` ft, height `[1.5, 3.5]` ft.
- Zone cell size: side `0.332` ft (1.66 / 5), height `0.4` ft (2.0 / 5).
- With the shadow ring: side `[-1.162, 1.162]`, height `[1.1, 3.9]`.
- Anything outside the ring is clamped into the outermost ring cell, so every taken pitch is counted somewhere and the cell totals reconcile exactly with the SLAA tile.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_catching_dash.py`:

```python
def test_slaa_location_figure_totals_reconcile_with_slaa():
    """Every taken pitch must land in exactly one display cell, so the grid
    sums to the same number the SLAA tile shows."""
    import pandas as pd
    from app.dashboards.catching import charts
    from app.data import called_strike as cs
    from app.data import catching_caps

    rows = [(0.0, 2.5, "StrikeCalled")] * 60 + [(0.0, 2.5, "BallCalled")] * 60
    rows += [(9.0, 9.0, "BallCalled")] * 10          # far outside, must still count
    df = pd.DataFrame(rows, columns=["plate_loc_side", "plate_loc_height", "pitch_call"])
    lk = cs._build_lookup_from_df(df)

    fig = charts.slaa_location_figure(df, lookup=lk)
    grid_total = float(pd.DataFrame(fig.data[0].z).fillna(0).values.sum())
    slaa = catching_caps.slaa_summary(df, lookup=lk)["slaa"]
    assert abs(grid_total - slaa) < 0.05, (
        f"grid sums to {grid_total} but SLAA is {slaa} -- pitches are being "
        "dropped or double-counted")


def test_slaa_location_figure_on_empty_frame_does_not_raise():
    import pandas as pd
    from app.dashboards.catching import charts
    df = pd.DataFrame(columns=["plate_loc_side", "plate_loc_height", "pitch_call"])
    fig = charts.slaa_location_figure(df)
    assert fig is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_catching_dash.py -k slaa_location -q`
Expected: FAIL — `AttributeError: module ... has no attribute 'slaa_location_figure'`

- [ ] **Step 3: Implement `slaa_location_figure` in `app/dashboards/catching/charts.py`**

Follow the file's existing figure conventions (its imports, colour constants, and `update_layout` style — read a neighbouring figure builder first and match it).

```python
# Display grid: 5x5 over the nominal zone plus a one-cell shadow ring (7x7).
# Deliberately coarser than called_strike's 0.15 ft model bins -- one catcher
# cannot fill 952 cells, so rendering them would be noise, not information.
ZONE_SIDE_HALF = 0.83
ZONE_H_LO, ZONE_H_HI = 1.5, 3.5
_CELL_W = (2 * ZONE_SIDE_HALF) / 5.0     # 0.332 ft
_CELL_H = (ZONE_H_HI - ZONE_H_LO) / 5.0  # 0.4 ft
_N = 7                                   # 5 zone cells + 1 ring each side


def _display_cell(side, height) -> tuple:
    """(col, row) in the 7x7 display grid. Out-of-grid pitches clamp into the
    outer ring so every taken pitch is counted exactly once and the grid
    reconciles with SLAA."""
    import math
    col = int(math.floor((float(side) - (-ZONE_SIDE_HALF - _CELL_W)) / _CELL_W))
    row = int(math.floor((float(height) - (ZONE_H_LO - _CELL_H)) / _CELL_H))
    return (min(_N - 1, max(0, col)), min(_N - 1, max(0, row)))


def slaa_location_figure(df, *, lookup=None):
    """Heat map of (actual - expected) called strikes by zone region.

    Diverging around zero: positive = strikes gained, negative = lost.
    """
    import numpy as np
    import pandas as pd
    import plotly.graph_objects as go

    from app.data import called_strike as cs

    z = np.zeros((_N, _N), dtype=float)
    if df is not None and not df.empty:
        taken = df[cs.is_taken(df)]
        taken = taken[taken["plate_loc_side"].notna()
                      & taken["plate_loc_height"].notna()]
        if not taken.empty:
            exp = cs.expected_called_strikes(taken, lookup=lookup)
            act = cs.is_called_strike(taken).astype(float)
            diff = act - exp
            for s, h, d in zip(taken["plate_loc_side"],
                               taken["plate_loc_height"], diff):
                c, r = _display_cell(s, h)
                z[r][c] += float(d)

    lim = float(max(1.0, np.abs(z).max()))
    fig = go.Figure(go.Heatmap(
        z=z, zmid=0, zmin=-lim, zmax=lim,
        colorscale="RdBu", reversescale=True,
        hovertemplate="strikes gained: %{z:.1f}<extra></extra>",
        colorbar=dict(title="+/- strikes"),
    ))
    # Outline the nominal strike zone: it spans display cells 1..5 inclusive,
    # so its edges sit at -0.5 and 5.5 in cell coordinates.
    fig.add_shape(type="rect", x0=0.5, x1=5.5, y0=0.5, y1=5.5,
                  line=dict(color="#1a1a1a", width=2))
    fig.update_layout(
        title="Strikes gained vs expected, by location (catcher's view)",
        xaxis=dict(showticklabels=False, title=None),
        yaxis=dict(showticklabels=False, title=None, scaleanchor="x"),
        margin=dict(l=10, r=10, t=40, b=10),
    )
    return fig
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_catching_dash.py -k slaa_location -q`
Expected: 2 passed

- [ ] **Step 5: Render it on the Framing tab**

In `app/dashboards/catching/tabs/framing.py`, add the figure below the existing framing content, following that file's existing `dcc.Graph` pattern (read how the neighbouring charts are wired — including whether figures are built in the tab or in a callback — and match it exactly).

- [ ] **Step 6: Verify the catching dashboard still renders**

Run: `python -m pytest tests/test_catching_dash.py tests/test_catching.py tests/test_catching_caps.py -q`
Expected: all pass

- [ ] **Step 7: Live visual check**

Run `PYTHONIOENCODING=utf-8 python run.py`, open http://127.0.0.1:8050, log in as the coach account, open the catching dashboard, and confirm: the SLAA and SL+ tiles show plausible values, and the Framing tab's heat map renders with the zone outline visible and readable. Report what you saw. If the heat map is unreadable or the tiles are misaligned, say so rather than shipping it.

- [ ] **Step 8: Commit**

```bash
git add app/dashboards/catching/charts.py app/dashboards/catching/tabs/framing.py tests/test_catching_dash.py
git commit -m "feat(catching): add the by-location strikes-gained heat map"
```

---

### Task 5: Full-suite verification

**Files:** none modified.

- [ ] **Step 1: Run the full suite**

Run: `python -m pytest -q --ignore=tests/test_precalc.py`
Expected: 903 + the new tests passing, 0 failures. Takes ~10 minutes.

- [ ] **Step 2: If anything fails, fix it before finishing**

Do not finish with failures. Record the failure and its cause.

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| §4 model, population, binning | 1 |
| §4 clipping (the xba.py divergence) | 1 (constant + regression test) |
| §4 two-level shrinkage | 1 |
| §4 entry points + `lookup=` seam | 1 |
| §4 caching via `@cached` | 1 |
| §5 expected / SLAA / SL+ | 2 |
| §5 sample-size floor of 100 | 2 |
| §6 sidebar tiles | 3 |
| §6 location heat map + 7×7 display grid | 4 |
| §7 testing | 1, 2, 3, 4 |
| §3 tuple keys for future batter-side split | 1 (constant + explicit test) |
| §3 existing tiles unchanged | 3 (asserted in the test) |
| Global constraint: suite stays green | 5 |

No gaps.

**Placeholder scan:** none. Two steps deliberately instruct the implementer to read a neighbouring file and match its conventions (Task 3 Step 1's sidebar signature, Task 4 Step 5's graph wiring) rather than guessing at code I have not read — each says exactly what to check and to report what it found.

**Type consistency:** `_Lookup`, `_build_lookup_from_df`, `p_called_strike`, `expected_called_strikes`, `is_taken`, `is_called_strike` are defined in Task 1 and used under those exact names in Tasks 2 and 4. `slaa_summary` / `slaa_season_tiles` / `SL_PLUS_MIN_TAKEN` are defined in Task 2 and used under those names in Tasks 3 and 4. `slaa_summary` returns `sl_plus: float | None`; Task 2's tile formatter and Task 3's test both handle the `None` case.
