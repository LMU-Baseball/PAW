"""Season-over-season pitcher development: the data behind the "did he get
better?" callout and the year-over-year movement comparison.

This lives in its own module rather than in `pitching.py` (pure transforms +
figures, no SQL) or `pitching_caps.py` (already the largest data module in the
app) because it is a *composition* layer: it owns no queries of its own and
instead stitches together three things that already exist --

  * `pitching_caps._season_pitch_df`     -- the season-scoped pitch read
  * `pitching_caps._compute_season_rollup` -- K% / BB% / Barrel% for a season
  * the Fastball/Sinker velo definition shared by `velo_board` and
    `pitching_caps._pitcher_velo_appearances`

-- into the exact shapes the pitching dashboard wants. Keeping it separate
means the next person looking for "where does the development card get its
numbers" finds one small file instead of grepping two large ones.

Two gotchas worth knowing before you edit this:

1. **"Previous season" is not "last year."** A redshirt year, a season lost to
   injury, or simply a fall with no tracked outings all produce an academic
   year in which the pitcher threw zero pitches. Diffing against that gives a
   bogus "-8.0 mph" headline. So the previous season is found by walking
   `seasons.available_seasons()` backwards and taking the first one in which
   THIS pitcher actually has pitches -- see `previous_season_with_data`.

2. **"Velo" has exactly one definition in this codebase** and it is not
   "mean rel_speed." It is Fastball/Sinker rel_speed only, matching the
   warehouse view `vw_pitcher_appearance_velo` that `pitching_caps.
   _pitcher_velo_appearances` mirrors and that `velo_board` reads off. An
   off-speed-heavy outing would otherwise drag the "average velo" down and
   read as a lost tick of fastball. `VELO_PITCH_TYPES` is derived from
   `velo_board._VELO_PITCH_TYPES` rather than re-typed here, so the two can
   never drift apart.
"""
from __future__ import annotations

import pandas as pd

from app.data import pitching, pitching_caps, seasons, velo_board
from app.data.cache import cached

# ("Fastball", "Sinker"), parsed out of velo_board's SQL-fragment constant so
# there is literally one place in the repo that decides what counts as velo.
# Parsing beats re-declaring: if a coach ever adds Cutter to the board's
# definition, this follows automatically instead of silently disagreeing.
VELO_PITCH_TYPES: tuple[str, ...] = velo_board.VELO_PITCH_TYPES

# The metrics the callout diffs. Order is display order for the UI (velo
# headline first, then the rate stats), so keep it meaningful.
# NOTE for the UI layer: delta POLARITY is per-metric -- up is good for
# avg_velo/max_velo/k_pct, up is BAD for bb_pct/barrel_pct. This module
# deliberately returns raw signed differences and leaves "is that an
# improvement?" to the renderer; a data module shouldn't encode colour rules.
DELTA_METRICS: tuple[str, ...] = ("avg_velo", "max_velo", "k_pct", "bb_pct",
                                  "barrel_pct")


def _as_float(value):
    """Parse a rollup tile back to a float, or None.

    `pitching_caps._compute_season_rollup` returns DISPLAY strings -- "23.4%"
    for a real value and the em-dash placeholder "—" when the season has no
    data -- because its primary consumer is the sidebar tile block. The
    callout needs numbers to subtract, so strip the '%' and hand back None for
    anything unparseable. None (rather than 0.0) matters: a missing metric must
    produce NO delta, not a delta against zero.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return None if pd.isna(value) else float(value)
    text = str(value).strip().rstrip("%").strip()
    try:
        return float(text)
    except ValueError:
        return None


@cached
def season_movement(pitcher_id, season) -> pd.DataFrame:
    """The pitch dataframe for one (pitcher, season), ready for
    `pitching.fig_movement`.

    Delegates straight to `pitching_caps._season_pitch_df`, which already does
    the sibling-Trackman-id union and the academic-year Date bounding and
    aliases GAMES's CamelCase columns to the snake_case names the figure
    builders read. Writing a second season query here would be a second thing
    to keep in sync for no gain.

    Always a DataFrame, never None -- the year-over-year panel decides whether
    to render by asking `.empty`, and so does `previous_season_with_data`.
    Cached because the previous-season walk calls it once per candidate season
    and the UI then calls it again for the two panels it draws.
    """
    df = pitching_caps._season_pitch_df(int(pitcher_id), season)
    if df is None:
        return pd.DataFrame()
    return df


def previous_season_with_data(pitcher_id, season) -> str | None:
    """The most recent season strictly BEFORE `season` in which this pitcher
    actually threw, or None.

    Deliberately NOT "the prior academic year": walking
    `seasons.available_seasons()` (already newest-first) and testing each
    candidate for pitches is what lets a redshirt or injury year be skipped
    over instead of surfacing as an empty comparison. Season labels are
    "YYYY/YYYY+1", so a lexicographic `<` is also a chronological one -- which
    keeps this correct even when `season` isn't itself in the available list
    (e.g. a caller asking about a season with no LMU games at all).
    """
    earlier = [s for s in seasons.available_seasons() if str(s) < str(season)]
    for candidate in earlier:  # already newest-first
        if not season_movement(pitcher_id, candidate).empty:
            return candidate
    return None


def _season_velo(pitcher_id, season) -> tuple[float | None, float | None]:
    """(avg, max) Fastball/Sinker velo for a season, or (None, None).

    Filters on the RAW `tagged_pitch_type` column -- not `pitching.pitch_type`,
    which falls back to `auto_pitch_type` -- because the velo definition being
    mirrored (`TaggedPitchType IN ('Fastball','Sinker')` in
    `pitching_caps._pitcher_velo_appearances` and `velo_board`) is a SQL filter
    on the tagged column only. Using the auto-fallback here would quietly make
    this a THIRD definition of velo.

    Outlier-clipped through `velo_board._clip_velo_outliers` for the same
    reason the Top Gun board clips: a single sensor/calibration glitch (a real
    ~93 mph arm reading 99.98) would otherwise become the max-velo headline
    and, year over year, a fictional +7 mph jump. The clip is a no-op on small
    samples, so a pitcher with a handful of tracked fastballs is unaffected.

    Games only -- bullpen sessions are excluded, matching
    `_pitcher_velo_appearances` (the board mixes BULLPEN in for its weekly
    grid; a season development card is about competition velo).
    """
    df = season_movement(pitcher_id, season)
    if df.empty or not {pitching.PITCH_TYPE_COL, "rel_speed"} <= set(df.columns):
        return None, None
    fb = df[df[pitching.PITCH_TYPE_COL].isin(VELO_PITCH_TYPES)]
    fb = velo_board._clip_velo_outliers(fb.dropna(subset=["rel_speed"]))
    if fb is None or fb.empty:
        return None, None
    return float(fb["rel_speed"].mean()), float(fb["rel_speed"].max())


def season_metrics(pitcher_id, season) -> dict:
    """One season's development numbers: label + velo + the three rate stats.

    The rate stats are read back off `pitching_caps._compute_season_rollup`
    rather than recomputed -- that function is the single definition of this
    app's K% / BB% / Barrel% (it routes through `pitching.k_pct` etc.), and a
    parallel computation here would be a slow-motion divergence waiting to
    happen. Its values arrive as display strings, so `_as_float` converts.
    """
    rollup = pitching_caps._compute_season_rollup(int(pitcher_id), season) or {}
    avg_velo, max_velo = _season_velo(pitcher_id, season)
    return {
        "label": season,
        "avg_velo": avg_velo,
        "max_velo": max_velo,
        "k_pct": _as_float(rollup.get("k_pct")),
        "bb_pct": _as_float(rollup.get("bb_pct")),
        "barrel_pct": _as_float(rollup.get("barrel_pct")),
    }


def _deltas(current: dict, previous: dict | None) -> dict:
    """current - previous, per metric, skipping any metric that is missing on
    either side. A skipped metric is ABSENT from the dict (not present-as-None)
    so the UI's `if metric in deltas` renders no arrow at all rather than an
    arrow pointing at nothing."""
    if not previous:
        return {}
    out = {}
    for metric in DELTA_METRICS:
        cur, prev = current.get(metric), previous.get(metric)
        if cur is None or prev is None:
            continue
        out[metric] = cur - prev
    return out


@cached
def season_comparison(pitcher_id, season=None) -> dict:
    """Season-over-season development numbers for the sidebar callout.

    Returns::

        {"current":  {"label", "avg_velo", "max_velo",
                      "k_pct", "bb_pct", "barrel_pct"},
         "previous": {...same keys...} | None,
         "deltas":   {metric: current - previous, ...} | {}}

    `season` defaults to `seasons.current_season()`. `previous` is the most
    recent EARLIER season in which the pitcher actually threw (see
    `previous_season_with_data`), so a redshirt year is stepped over rather
    than reported as a collapse to zero.

    Everything is None-safe by construction: a true first-year pitcher gets
    `previous=None` and `deltas={}`, and any single metric that is missing on
    either side simply has no entry in `deltas`. Nothing here raises on thin
    data -- the callout renders above the fold and must never be the reason a
    dashboard 500s.
    """
    season = season or seasons.current_season()
    current = season_metrics(pitcher_id, season)

    prev_label = previous_season_with_data(pitcher_id, season)
    previous = season_metrics(pitcher_id, prev_label) if prev_label else None
    # Guard the pathological case where a season had pitches but no usable
    # metric at all -- treat it as no comparison rather than a row of blanks.
    if previous is not None and all(
            previous.get(m) is None for m in DELTA_METRICS):
        previous = None

    return {"current": current, "previous": previous,
            "deltas": _deltas(current, previous)}
