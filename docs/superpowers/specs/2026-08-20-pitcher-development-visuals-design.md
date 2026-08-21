# Pitcher development visuals — design

**Date:** 2026-08-20
**Status:** approved, building
**Reference:** `IMG_3435.PNG` — a Wake Forest pitcher development card (Chris Levonas):
a YoY max-velo headline, a row of KPI tiles each with a season-over-season delta
arrow, and two side-by-side movement plots (2025 vs 2026) coloured by pitch type.

## Why

From the 2026-08-20 coaches' meeting, the "player dashboard updates" bullet:

- movement plot, release side, and release height on the homepage tab
- a development-trend callout (avg/max velo + K / barrel / walk) under the
  existing KPI block
- a year-over-year movement plot comparison (2025 vs 2026) for returning players
- season view needs no new tab — the existing "all games" date-range filter
  already covers it

These are **pitcher** metrics. The reference card shows induced vertical break,
horizontal break, pitch-type movement clusters and a 98.4 mph max velo; "K /
barrel / walk" reads as strikeout rate, barrel% allowed and walk rate, all
standard pitcher stats. The meeting notes list hitting separately as "minor KPI
additions, nothing major". So all of this lands on the **pitching dashboard**.

## What already exists (reuse, do not rebuild)

| Thing | Where |
|---|---|
| Movement scatter w/ 1σ covariance ellipses per pitch type | `app.data.pitching.fig_movement(df)` |
| Per-pitch-type avg/max velo, spin, ivb, hb, rel_height, rel_side, extension | `app.data.pitching.pitch_characteristics(df)` |
| Per-season rollup (K%, BB%, Barrel%, IP, …) | `app.data.pitching_caps._compute_season_rollup(pitcher_id, season)` |
| Range rollup driving the sidebar tiles | `app.data.pitching_caps.range_summary(pitcher_id, start, end)` |
| Season label from a date | `app.data.pitching_caps._season_label(date_str)` |
| Season list / bounds / current | `app.data.seasons` |
| Pitch-type colour map | `app.data.pitching.pitch_color(pt)` |
| Standard figure chrome | `app.data.pitching._base_layout(fig, title)` |
| Sidebar KPI tiles (APP/IP/K%/BB%/Barrel%) | `app/dashboards/pitching/layout.py::sidebar` (~L46) |
| "Personal Breakdown" homepage tab | `app/dashboards/pitching/tabs/pitch_breakdown.py` |
| "Movement Profile" tab | `app/dashboards/pitching/tabs/location_movement.py` |

Raw columns available on a pitch dataframe: `rel_speed`, `spin_rate`,
`induced_vert_break`, `horz_break`, `rel_height`, `rel_side`, `extension`.

## Deliverables

### 1. Release-point plot + movement plot on the homepage tab

`pitch_breakdown.render(df)` gains two figures beside its existing table:

- **Movement** — reuse `pitching.fig_movement(df)` verbatim. No new code.
- **Release point** — NEW `pitching.fig_release(df)`: scatter of `rel_side` (x)
  vs `rel_height` (z), one trace per pitch type, `pitch_color` for colour,
  `_base_layout` for chrome. Axis titles "Release Side (ft)" / "Release Height
  (ft)". Mirror `fig_movement`'s structure and hovertemplate style. Keep the
  x-axis symmetric about 0 so arm side reads correctly, and preserve aspect so
  the release cluster isn't visually distorted.

Both must degrade gracefully to an empty-state when the columns are all-NaN
(pull-through of `fig_movement`'s `dropna` behaviour).

### 2. Development-trend callout under the sidebar KPI block

New module **`app/data/pitcher_development.py`** owning the season-over-season
comparison, so neither `pitching.py` nor `pitching_caps.py` grows further.

```
season_comparison(pitcher_id, season=None) -> dict
```

Returns, for `season` (default `seasons.current_season()`) and the prior season
that has data for this pitcher:

```
{
  "current": {"label": "2025/2026", "avg_velo":…, "max_velo":…,
              "k_pct":…, "bb_pct":…, "barrel_pct":…},
  "previous": {…same keys…} | None,
  "deltas":   {"avg_velo": +2.8, …} | {}   # current - previous, None-safe
}
```

- "Previous season" = the most recent season BEFORE `season` in which the
  pitcher actually has pitches. Not simply "the year before" — a redshirt or an
  injury year would otherwise produce a bogus empty comparison.
- Velo = Fastball/Sinker `rel_speed` only, matching the definition already used
  by `velo_board` and `pitching_caps._pitcher_velo_appearances`. Do not invent a
  second definition of "velo".
- Every value None-safe: a pitcher with no prior season returns
  `previous=None`, `deltas={}`, and the UI shows the current value with no arrow.

UI: a compact block under the existing tiles in `layout.py::sidebar`, one row per
metric — previous value, delta arrow, current value — styled after the reference
card. **Delta direction is per-metric**: up is good for avg/max velo and K%, up
is BAD for BB% and Barrel%. Colour by whether the change is an improvement, not
by its sign.

### 3. Year-over-year movement comparison for returning players

On the **Movement Profile** tab, below the existing single-season plot:
two movement plots side by side, previous season left, current right, same axis
ranges on both so clusters are visually comparable (compute the union of both
extents and apply to each).

- Only rendered when the pitcher has movement data in a prior season — that is
  the "returning player" condition. Otherwise render nothing (no empty panel, no
  apology text).
- Data via `pitcher_development.season_movement(pitcher_id, season)` returning
  the pitch dataframe for one season, reusing the existing season-scoped read.
- Reuse `fig_movement` for each side rather than writing a second movement plot.

## Non-goals

- No new tab. The existing "all games" date-range filter already covers the
  season view.
- Hitting/catching KPI additions are a separate, later piece of work.
- No change to write access, role gating, or any filter behaviour.

## Testing

- `pitching.fig_release`: returns a figure, one trace per pitch type, correct
  axis titles, survives an all-NaN release frame.
- `pitcher_development.season_comparison`: picks the correct prior season when
  the immediately-preceding one is empty; `previous=None` for a true first-year
  pitcher; deltas None-safe; velo restricted to Fastball/Sinker.
- Delta polarity: a BB% increase must not render as an improvement.
- YoY panel absent for a first-year pitcher, present for a returning one.
- Both dashboards still render for coach AND player roles (the filter-access
  tests in `tests/test_player_filter_access.py` must keep passing).
