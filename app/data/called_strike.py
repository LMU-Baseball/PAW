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
