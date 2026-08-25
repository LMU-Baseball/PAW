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

Smoothing (two-level empirical-Bayes, LOCAL anchor -- fix round 1)
-------------------------------------------------------------------
    cell_rate = (cell_strikes + k * local_anchor) / (cell_n + k)

`local_anchor` is a pooled rate over the cell's 8 grid neighbours (pooled
sum/count of adjacent (side_bin, height_bin) cells), itself first smoothed
toward the global called-strike rate so a sparse or one-sided neighbourhood
cannot anchor a cell at exactly 0 or 1.

Fix round 1 replaced the original anchor -- an entire height band's marginal
rate -- with this local 8-neighbour pool. A height band is NOT a local
neighbourhood: within one band, side runs the full -2.0..+2.0 window and the
true rate runs ~0.99 down to ~0.00, so the band marginal (e.g. ~0.61 at a
mid height) dragged every cell in that row toward it regardless of how far
off the plate the cell actually was. That reintroduced, in miniature, the
exact bug the clipping exists to prevent: well-sampled off-plate cells
(n=55-115, plenty of data) were pulled up by 0.10-0.16 absolute, and summed
over the season the model over-predicted total called strikes by +2.15%
versus the raw, unsmoothed cell rates (which reproduce the actual count
exactly -- 100% of that surplus was shrinkage bias). An 8-neighbour pool is
local: adjacent cells are close in both side and height, so pooling them
does not smuggle in the zone's opposite edge.

`k = MIN_SAMPLE = 5` (dropped from 20, inherited from xba.py's much thinner
cells -- here the median cell is n=56 and only 7% are below n=10, so k=20
bought smoothness this data doesn't need and paid for it in bias).

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

# Cell shrinkage weight k, and the weight used to smooth the local 8-neighbour
# anchor toward the global rate. Same roles as xba.py's MIN_SAMPLE /
# MARGINAL_SHRINK_K. Fix round 1: dropped from 20 -- see module docstring.
MIN_SAMPLE = 5
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
    [start, start+size) cells.

    Rounded to 6 decimals so a bin-start computed via floor-division always
    equals the same value computed by stepping from a neighbouring bin by
    +-size (needed for the local 8-neighbour anchor's dict lookups below to
    hit, despite 0.15 not being exactly representable in binary floats).
    """
    return round(float(np.floor(float(value) / size) * size), 6)


# The 8 grid-adjacent (side, height) offsets around a cell, used to pool a
# local anchor for smoothing (see module docstring, "fix round 1").
_NEIGHBOR_OFFSETS = tuple(
    (round(ds, 6), round(dh, 6))
    for ds in (-SIDE_BIN_SIZE, 0.0, SIDE_BIN_SIZE)
    for dh in (-HEIGHT_BIN_SIZE, 0.0, HEIGHT_BIN_SIZE)
    if not (ds == 0.0 and dh == 0.0)
)


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

    grouped = d.groupby(["_side_bin", "_height_bin"])["_cs"].agg(["sum", "count"])
    cell_sums = {key: float(row["sum"]) for key, row in grouped.iterrows()}
    cell_counts = {key: float(row["count"]) for key, row in grouped.iterrows()}

    # Level 1: for each populated cell, pool the (sum, count) of its 8 grid
    # neighbours and smooth that pooled rate toward the global anchor. A
    # neighbourhood is LOCAL (adjacent in both side and height), unlike an
    # entire height band -- see module docstring for why that distinction is
    # the whole fix.
    def _local_anchor(sb: float, hb: float) -> float:
        pooled_sum = 0.0
        pooled_n = 0.0
        for ds, dh in _NEIGHBOR_OFFSETS:
            nk = (round(sb + ds, 6), round(hb + dh, 6))
            if nk in cell_counts:
                pooled_sum += cell_sums[nk]
                pooled_n += cell_counts[nk]
        # pooled_n == 0 (all 8 neighbours unpopulated) falls straight through
        # to the global `anchor` -- unreachable against the current, fully
        # populated live grid (952/952 cells, verified), but would matter if
        # a future batter-side split (planned v2, see spec Sec.3) increases
        # sparsity enough to leave a cell with no populated neighbours.
        return (pooled_sum + MARGINAL_SHRINK_K * anchor) / (pooled_n + MARGINAL_SHRINK_K)

    # Level 2: smooth each cell toward its own (already-smoothed) local
    # anchor. Because that anchor is strictly in (0,1) and k > 0, no cell can
    # land on exactly 0.0/1.0 for any n, including n=1.
    cell_rates: dict = {}
    for (sb, hb) in cell_counts:
        n = cell_counts[(sb, hb)]
        strikes = cell_sums[(sb, hb)]
        local_anchor = _local_anchor(sb, hb)
        smoothed = (strikes + MIN_SAMPLE * local_anchor) / (n + MIN_SAMPLE)
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
    key = _cell_key(side, height)
    p = lookup.cell_rates.get(key)
    if p is None:
        p = _nearest_neighbor_rate(key, lookup)
    return float(min(1.0, max(0.0, p)))


def _nearest_neighbor_rate(key: tuple, lookup: "_Lookup") -> float:
    """Fallback for a cell key never observed in training: the rate of the
    nearest populated cell by grid distance -- not a whole-row/whole-band
    average. A coarse row average would reintroduce exactly the bias the
    local 8-neighbour anchor (see module docstring) exists to avoid: an
    unpopulated cell deep off the plate should inherit its immediate
    neighbours' near-zero rate, not an average spanning all the way back to
    the heart of the zone. In practice this path is close to unreachable --
    the live grid is fully populated (952/952 cells) -- but it matters for
    any sparser or filtered training population. Falls back to the lookup's
    global rate only when there are no populated cells at all."""
    if not lookup.cell_rates:
        return lookup.fallback
    sb, hb = key
    best_rate = lookup.fallback
    best_dist = None
    for (s, h), rate in lookup.cell_rates.items():
        dist = ((s - sb) / SIDE_BIN_SIZE) ** 2 + ((h - hb) / HEIGHT_BIN_SIZE) ** 2
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best_rate = rate
    return best_rate


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
