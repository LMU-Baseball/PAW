"""Home-grown expected batting average (xBA) model, built from LMU's own
batted balls (isolated module — Task 1 of the hitting-KPIs work; Task 2 wires
this into the hitting sidebar).

Model
-----
A 2-D lookup keyed by (exit velo bin, launch angle bin), where each cell holds
the empirical P(hit) among LMU InPlay batted balls that landed in that cell
(hit definition = `app.data.hitting._is_hit`: `PitchCall=='InPlay'` and
`PlayResult != 'Out'`). Source population: ALL LMU batted balls
(`BatterTeam='LOY_LIO'`, `PitchCall='InPlay'`) with both `ExitSpeed` and
`Angle` populated.

Smoothing (empirical-Bayes shrinkage)
--------------------------------------
A cell with few batted balls is noisy — e.g. 1-for-1 must not surface as a
"raw" 100%. Each cell's rate is shrunk toward a coarser marginal (that same
exit-velo band's rate across all launch angles) weighted by the cell's sample
count:

    smoothed = (hits + k * marginal_ev_rate) / (n + k)

with `k = MIN_SAMPLE` doing double duty as both "a cell needs at least this
many balls to be trusted" and the shrinkage strength. This is a weighted
average of two already-in-[0,1] rates, so `smoothed` is always in [0,1] with
no extra clamping needed; as `n` grows past `k` the raw rate dominates, and
as `n` shrinks toward 0 the cell converges to the marginal. If the exit-velo
band itself is unobserved (shouldn't happen once the DB has any data in that
band), the global InPlay hit rate is substituted for `marginal_ev_rate`.

Public API
----------
`p_hit(exit_speed, launch_angle)` and `xba_hit_prob_sum(batted_balls_df)` are
the two entry points Task 2 will call. Both accept an optional `lookup=`
override (a `_Lookup` from `_build_lookup_from_df`) purely so tests can inject
a synthetic lookup instead of hitting the live DB / process cache — real
callers should omit it and get the cached, DB-backed lookup.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.data.cache import cached
from app.data.hitting import _is_hit
from app.db import query_df

LMU_BATTER_TEAM = "LOY_LIO"

# --- bin sizes (named constants, per brief) --------------------------------
EV_BIN_SIZE = 5.0   # mph, exit velo bin width
LA_BIN_SIZE = 5.0   # degrees, launch angle bin width

# A cell needs at least this many batted balls to be mostly-trusted; also
# doubles as the empirical-Bayes shrinkage weight `k` (see module docstring).
MIN_SAMPLE = 20

# Used only if the DB ever returns zero qualifying batted balls (shouldn't
# happen in practice) so the lookup is still total rather than raising.
DEFAULT_FALLBACK_HIT_RATE = 0.3


@dataclass(frozen=True)
class _Lookup:
    """A built EV x LA hit-probability lookup.

    `cell_rates`: {(ev_bin_start, la_bin_start): smoothed P(hit)} for every
    populated (ev, la) bin. `fallback`: the global InPlay hit rate among the
    rows the lookup was built from — used for missing EV/LA and for any
    (ev, la) combination that never appeared in LMU's own batted balls.
    """
    cell_rates: dict = field(default_factory=dict)
    fallback: float = DEFAULT_FALLBACK_HIT_RATE


def _bin_start(value: float, size: float) -> float:
    """Bin-start edge for `value` in a `size`-wide grid (e.g. 12.3 with
    size=5 -> 10.0), so a raw value maps to a half-open [start, start+size)
    cell key."""
    return float(np.floor(float(value) / size) * size)


def _raw_batted_balls() -> pd.DataFrame:
    """ALL LMU InPlay batted balls with ExitSpeed AND Angle populated.

    League-wide (not per-batter, unlike `hitting_caps.bip_points`) — a
    dedicated small query, per the brief. Columns are the raw GAMES names
    (ExitSpeed/Angle/PitchCall/PlayResult) so `_is_hit` applies directly.
    """
    return query_df(
        """
        SELECT ExitSpeed, Angle, PitchCall, PlayResult
          FROM GAMES
         WHERE BatterTeam = :team
           AND PitchCall = 'InPlay'
           AND ExitSpeed IS NOT NULL
           AND Angle IS NOT NULL
        """,
        {"team": LMU_BATTER_TEAM},
    )


def _build_lookup_from_df(df: pd.DataFrame) -> _Lookup:
    """Pure lookup-table builder (no DB access) — the DB-free seam for tests.

    Bins `df` by exit velo x launch angle, computes each cell's empirical
    hit rate, and shrinks it toward that EV band's marginal rate (see module
    docstring for the smoothing formula).
    """
    d = df.copy()
    d = d[d["ExitSpeed"].notna() & d["Angle"].notna()]
    if d.empty:
        return _Lookup(cell_rates={}, fallback=DEFAULT_FALLBACK_HIT_RATE)

    d["_hit"] = _is_hit(d)
    d["_ev_bin"] = d["ExitSpeed"].apply(lambda v: _bin_start(v, EV_BIN_SIZE))
    d["_la_bin"] = d["Angle"].apply(lambda v: _bin_start(v, LA_BIN_SIZE))

    global_rate = float(d["_hit"].mean())

    ev_marginal = (
        d.groupby("_ev_bin")["_hit"].mean().to_dict()
    )

    cell_group = d.groupby(["_ev_bin", "_la_bin"])["_hit"].agg(["sum", "count"])
    cell_rates: dict = {}
    for (ev_bin, la_bin), row in cell_group.iterrows():
        n = float(row["count"])
        hits = float(row["sum"])
        marginal = ev_marginal.get(ev_bin, global_rate)
        smoothed = (hits + MIN_SAMPLE * marginal) / (n + MIN_SAMPLE)
        cell_rates[(ev_bin, la_bin)] = float(min(1.0, max(0.0, smoothed)))

    return _Lookup(cell_rates=cell_rates, fallback=global_rate)


@cached
def _get_lookup() -> _Lookup:
    """The process-wide lookup, built once from the live DB and memoized by
    the repo `@cached` util (zero-arg -> acts as a singleton cache)."""
    return _build_lookup_from_df(_raw_batted_balls())


def p_hit(exit_speed, launch_angle, lookup: _Lookup | None = None) -> float:
    """P(hit) for one batted ball, from the EV x LA lookup, clamped to [0,1].

    Missing/NaN EV or LA, or an (EV, LA) combination never seen in LMU's own
    batted balls (out of lookup range), falls back to the global InPlay hit
    rate — a ball is never silently dropped from an xBA sum because of this.

    `lookup` defaults to the cached, DB-backed lookup (`_get_lookup()`); pass
    an explicit `_Lookup` (e.g. from `_build_lookup_from_df`) to avoid the DB,
    as the tests do.
    """
    if lookup is None:
        lookup = _get_lookup()
    if pd.isna(exit_speed) or pd.isna(launch_angle):
        return float(min(1.0, max(0.0, lookup.fallback)))
    key = (_bin_start(exit_speed, EV_BIN_SIZE), _bin_start(launch_angle, LA_BIN_SIZE))
    p = lookup.cell_rates.get(key, lookup.fallback)
    return float(min(1.0, max(0.0, p)))


def xba_hit_prob_sum(batted_balls_df: pd.DataFrame, lookup: _Lookup | None = None) -> float:
    """Sum of p_hit over a player's batted-ball rows — the xBA NUMERATOR only
    (the caller divides by AB; see Task 2). Expects columns named like
    `hitting_caps.bip_points` output (`exit_speed`, `la`). Rows with missing
    EV/LA still contribute (via `p_hit`'s global fallback) so they count as
    batted balls rather than being dropped from the sum.
    """
    if batted_balls_df is None or batted_balls_df.empty:
        return 0.0
    if lookup is None:
        lookup = _get_lookup()
    total = sum(
        p_hit(ev, la, lookup=lookup)
        for ev, la in zip(batted_balls_df["exit_speed"], batted_balls_df["la"])
    )
    return float(total)
