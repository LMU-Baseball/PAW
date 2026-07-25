# HitTrax Practice Tab — Round 2 Design

**Date:** 2026-07-24
**Branch:** `feat/dashboard-polish-pass` (continues the dashboard polish pass)
**Status:** Design approved; proceeding to plan.

## Summary

A second refinement round on the HitTrax Practice tab, from coach review of the
running app. Centers on the batted-ball section: real LMU-park home-run
determination (the coach supplied field dimensions), fan/scatter consistency, and
richer hovers — plus two small chart tweaks (crimson heatmap colorscale, labeled
hovers).

**Scope:** HitTrax practice dashboard only (`app/data/practice.py`,
`app/dashboards/hitting_practice/charts.py`). No other dashboard, no DB/schema
change, no new dependency.

## Decisions locked with the coach

- Foul balls (|angle|>45°): **kept on the landing scatter but marked distinctly**
  (hollow/greyed); the fan stays fair-only.
- Home runs: determined from **real LMU fence dimensions** (below), not a flat
  distance proxy.
- Fan outer ring becomes a true **HR ring** bounded by the fence curve.
- Home runs get a **distinct marker** on the scatter.
- Heatmaps + fan use our crimson sequential ramp (light pink → `#9A0021`).

## LMU field dimensions (coach-supplied)

Fence carry distance by spray direction (our angle convention: negative = left,
0 = center, +45 = right-field line):

| Angle | Location | Fence (ft) |
|------:|----------|-----------:|
| −45   | LF line  | 326 |
| −22.5 | LF-center alley | 362 |
| 0     | CF       | 406 |
| +22.5 | RF-center alley | 365 |
| +45   | RF line  | 321 |

`fence_distance(angle)` = piecewise-linear interpolation over these five points
(`np.interp(angle, [-45,-22.5,0,22.5,45], [326,362,406,365,321])`), clamped to the
±45° fair range. This is a PROVISIONAL model (linear between the five measured
points); one-line to refine if more survey points arrive.

**Home run rule:** a batted ball is a home run when it is **fair** (|angle| ≤ 45°)
**and** `distance_feet ≥ fence_distance(angle)`.

## A. Pitch Zones heatmaps — crimson colorscale

All three metric heatmaps (Contact %, Avg EV, Avg Distance) in
`charts.pitch_zone_heatmap` switch from `"YlOrRd"` to a crimson sequential
colorscale: `[[0.0, "rgb(253,234,238)"], [1.0, "#9A0021"]]` (a light-pink →
crimson ramp; add a mid-stop `[0.5, "rgb(214,120,140)"]` if the two-stop ramp
reads too flat). `_METRIC_CFG` currently hardcodes `"YlOrRd"` per metric — replace
with the shared crimson scale. The black strike-zone box and colorbar stay.

## B. Labeled hovers on practice charts

- `ev_distance_by_pitch`: replace the default `(x, y)` hover with labeled two-line
  templates — EV trace `Pitch #: %{x}<br>Exit Velo: %{y:.1f} mph`, Distance trace
  `Pitch #: %{x}<br>Distance: %{y:.0f} ft`.
- `pitch_zone_heatmap`: the hover already shows `x`/`y`/`z`; relabel `z` with the
  active metric name (e.g. `Contact %: 62`, `Avg EV: 88 mph`, `Avg Dist: 250 ft`)
  and keep the coordinates as `Horizontal`/`Height`.
- `swing_decision_trend_fig` already reads cleanly (date + score); leave it.

## C. Fence model + ball classification (`app/data/practice.py`)

- New `fence_distance(angle)` (accepts scalar or array; used by both charts and the
  fan).
- `spray_points(plays)` gains two boolean columns: `is_foul` (|angle|>45°) and
  `is_hr` (fair and `distance_feet ≥ fence_distance(angle)`). Existing columns
  (`x, y, hit_type_label, distance_feet, exit_velocity`) unchanged; it still
  returns ALL batted balls (fair + foul) — the scatter shows everything.

## D. Landing scatter (`charts.spray_chart_fig`)

- `showlegend=False` (top chips are the legend).
- Draw the **real fence** as a curve: `fence_distance(angle)` sampled across
  −45…+45°, plus the two foul lines, replacing the generic 330 ft arc. Keep the
  infield diamond.
- **Three visual classes** of points, all still positioned by (x, y):
  - Fair, non-HR: filled marker in the hit-type color (current look), Distance +
    Exit-Velo hover.
  - **Foul** (`is_foul`): hollow/greyed marker (open circle, muted) — kept but
    visually separated. Hover notes "Foul".
  - **Home run** (`is_hr`): distinct marker (star symbol) in the hit-type color
    with a dark outline, so HRs pop. Hover notes "HR".
- Points are grouped by hit type for color; within each, split by class for marker
  style. Hover template includes hit type, Distance, Exit Velo, and the class tag.

## E. Distribution fan (`spray_fan` + `spray_distribution_fan`)

### `spray_fan(plays)` (data)
- Rings redefined to **Infield / Outfield / HR** where the Outfield↔HR boundary is
  the **fence** (angle-dependent), not a flat 330. Per fair ball: ring 0 if
  `dist < FAN_INFIELD_MAX` (150); ring 2 (HR) if `dist ≥ fence_distance(angle)`;
  else ring 1 (Outfield). Foul balls (|angle|>45) remain excluded (fan is
  fair-only).
- Each of the 15 cells additionally aggregates `avg_ev` and `avg_dist` (means of
  `exit_velocity` / `distance_feet` for that cell's balls; `None`/NaN when empty).
- `count` / `pct` invariants preserved (15 rows; `pct` sums to 100 over fair
  batted balls; full-precision `pct` per the round-1 fix). Geometry columns
  (`a0, a1, r0, r1`): the Outfield outer / HR inner radius is the fence at the
  wedge's representative angle; ring 2 outer = `FAN_DISPLAY_MAX`.

### Constants
- `FAN_INFIELD_MAX = 150.0`; `FAN_RINGS = ["Infield", "Outfield", "HR"]`;
  `FAN_DISPLAY_MAX = 440.0` (beyond the 406 ft CF fence + the 418.6 ft max carry,
  so the HR ring is always visible). `FAN_RING_EDGES` retired in favor of the
  fence-based boundary (keep `FAN_WEDGE_EDGES`, `FAN_DIRECTIONS`).

### `spray_distribution_fan(fan_df)` (chart)
- Ring polygons: Infield inner/outer 0/150 (constant); Outfield 150/fence;
  HR fence/display_max. The fence boundary is drawn as a **curve** (radius sampled
  at each angle within the wedge via `fence_distance`), so the HR ring hugs the
  real wall.
- Crimson shading (unchanged `_crimson_shade`) + `%` labels (unchanged).
- **Richer hover per cell:** `{direction} · {ring}`, then `Balls: {count}`,
  `Share: {pct}%`, `Avg EV: {avg_ev} mph`, `Avg Dist: {avg_dist} ft` (show "—"
  when a cell has no balls / no EV/dist).

## Testing

Follow repo conventions (pure data helpers → unit tests; chart builders → render +
targeted structural tests; live-DB tests unguarded).

- `fence_distance`: known points return the table values; midpoints interpolate;
  beyond ±45 clamps.
- `spray_points`: `is_foul`/`is_hr` columns correct for a fair-over-fence ball, a
  fair-short ball, and a foul ball; deep-line-vs-alley HR distinction holds
  (340 ft @ −45 = HR; 340 ft @ −22.5 = not HR).
- `spray_fan`: 15 rows; `pct` sums to 100; HR ring populated only by over-fence
  fair balls; `avg_ev`/`avg_dist` present and correct for a known cell; empty df →
  15 zero cells with `None` averages.
- `pitch_zone_heatmap`: colorscale is the crimson ramp (not `YlOrRd`) for all three
  metrics; hover names the metric.
- `ev_distance_by_pitch`: both traces carry labeled `Pitch #` / `Exit Velo` /
  `Distance` hovertemplates.
- `spray_chart_fig`: `showlegend` False; a fence curve shape present; foul points
  rendered as a distinct (open/greyed) trace; HR points as a distinct (star) trace.
- `spray_distribution_fan`: renders; hover text includes Balls / Avg EV / Avg Dist.

Full suite stays green (currently 290). Live smoke both roles; restart 8050 by port
owner.

## Files touched

- `app/data/practice.py` — `fence_distance` (new), `spray_points` (+is_foul/is_hr),
  `spray_fan` (fence rings + avg_ev/avg_dist), fan constants.
- `app/dashboards/hitting_practice/charts.py` — `pitch_zone_heatmap` (crimson +
  hover), `ev_distance_by_pitch` (labeled hover), `spray_chart_fig` (no legend +
  fence + foul/HR markers), `spray_distribution_fan` (fence-curve rings + richer
  hover).
- `tests/` — additions per above.

## Non-goals

- No true HR verification beyond carry-vs-fence (HitTrax has no fences/off-the-bat
  outcome; projected carry is the best available signal).
- No change to the fan's fair-only counting, the chip filter, or other tabs.
