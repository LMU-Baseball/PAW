# Dashboard Polish Pass — Design

**Date:** 2026-07-24
**Branch:** `feat/dashboard-polish-pass`
**Status:** Design approved; pending written-spec review.

## Summary

A coordinated cosmetic/UX refinement pass across four Dash dashboards, driven by
coach screenshots. Nine changes grouped by area. The only substantial new
component is the HitTrax "batted-ball distribution fan" (item B5); everything else
is a targeted tweak to existing code.

**Non-goals:** no new data sources, no new tabs, no role/permission changes, no
warehouse queries added. Roll-out of the pitching conventions (items C7/C8) to
other dashboards is explicitly deferred.

## Decisions locked with the user

- Fan (B5 left): **faithful fan sectors** — 5 direction wedges × 3 depth rings,
  home plate at the point, each cell shaded + `%`-labeled.
- Fan color: **brand crimson sequential** (light → `#9A0021`), not the mockup's
  brown.
- Zone chips (B4): **full standard set (Zone 1–13)**, drop Zone 0, relabel
  `Z#` → `Zone #`, grey + disable zones with no data.
- Spray chips (B5): **filter both** the fan and the scatter (kept in sync).
- Pitching conventions (C7/C8): **pitching dashboard only** this round.
- Squished facets (D9b): the **catching Static Framing** `framing_facets`.

---

## A. Global chrome

### A1 — Footnote color
The provisional footnote under the sidebar tiles is `#888`, too light over the
palms. Change to `#555` to match the profile/meta line above it.

- `app/dashboards/hitting/layout.py` — "Slash line = warehouse game data
  (provisional)." footnote.
- `app/dashboards/pitching/layout.py` — "Season totals = warehouse
  (provisional)." footnote.
- Practice/catching sidebars have no such footnote — no change.

### A2 — Back-link on the hitting game dashboard
`app/dashboards/hitting/layout.py::serve_layout` calls `header()` with no args.
Change to `header(back_href="/hitting", back_label="← Hitting")`, matching the
pitching (`/pitching`) and practice (`/hitting`) dashboards. No `shell.header`
change needed — it already supports the params.

---

## B. HitTrax Practice dashboard

### B3 — Session dates render as epoch values
`charts.swing_decision_trend_fig` sets `x = trend_df["play_date"].astype(str)`,
which renders raw epoch-style values on the "Session date" axis. Root-cause fix in
the chart builder: coerce `play_date` with `pd.to_datetime(...)` and render a
readable label (`%b %-d` / `%b %d`) on a category axis, so ticks read like
`Mar 31`, `Apr 7`, … Confirm dtype at implementation time; if `play_date` is
already `date`/`datetime`, the coercion is a no-op and only the label formatting
matters. No data-layer change expected.

### B4 — Zone chips
Today `swing_frequency.zone_chip_row` builds one chip per **present**
`zone_section` value (so Zone 0 leaks in and empty standard zones vanish).

New behavior:
- Iterate the **fixed** set `ZONES = range(1, 14)` (Zone 1–13). Zone 0 is never a
  chip.
- Chip label = `"Zone {z}"` (was `"Z{z}"`).
- A zone with data → active/colored and clickable (current crimson-filled style).
- A zone with **no** data in the current filter → rendered greyed and
  **non-interactive** (`disabled=True`, muted style, not part of the active set),
  so the grid stays stable across filters.
- `sfz-active` store initializes to the **present** zones only (empty zones start
  off and can't be toggled on).

Callback touch-points (`app/dashboards/hitting_practice/callbacks.py`):
- `_sfz_toggle` ignores clicks on disabled chips (guard: only toggle zones that
  are present). Simplest: disabled buttons emit no `n_clicks`, so a defensive
  `if z not in present` is optional but the store already excludes them.
- `_sfz_styles` must style the full 1–13 set consistently (active / inactive /
  disabled-empty), matching the ids it receives.

Data helper: add `present_zones(df) -> set[int]` (or compute inline) in
`app/data/practice.py` if it keeps the tab code clean; not required.

### B5 — Spray section: two fields side by side
Replaces the single spray chart in `tabs/batted_ball.py`. Layout top-to-bottom:

1. **Hit-type chip row** (deselectable), styled like the pitching
   `location_movement.chip_row`: one chip per hit type present
   (Ground Ball / Line Drive / Fly Ball), colored by `_HIT_COLORS`. A
   `dcc.Store` holds the active set; toggling filters **both** charts below.
2. **Two graphs side by side** (flex, `flex:1` each):
   - **Left — Batted-Ball Distribution fan** (new `charts.spray_distribution_fan`).
   - **Right — Landing scatter** (`charts.spray_chart_fig`, upgraded hover).
3. **Contact-Type bar** (full width, recolored `charts.contact_type_bar`).

#### B5a — Distribution fan (`charts.spray_distribution_fan(fan_df) -> go.Figure`)
Faithful to the mockup:
- Home plate at `(0, 0)`; fair territory is the 90° wedge from the left-field
  foul line (−45°) to the right-field foul line (+45°), measured from the y-axis
  (straightaway center = 0°).
- **5 direction wedges**, each 18° wide, spanning −45°…+45°.
- **3 depth rings** by `distance_feet`: Infield (`0–150`), Outfield (`150–330`),
  Deep/HR (`> 330`). Thresholds are provisional constants (docstring'd,
  one-line to change).
- Each of the 15 cells is drawn as a filled polygon (annular sector approximated
  by line segments — Plotly `path` shapes don't support SVG arcs, so use
  `go.Scatter(fill="toself")` polygons). Fill color = brand crimson **sequential**
  by the cell's share of total batted balls (light → `#9A0021`). Cells with 0
  balls are unfilled/very light.
- Each non-empty cell gets a centered `%` annotation (share of total batted
  balls), matching the mockup's `27%` labels.
- Hover per cell: `"{direction} · {ring}: {pct}% ({n} balls)"`.
- Foul lines + outfield arc drawn as reference like the current field.

Data: new `P.spray_fan(plays, hit_types=None) -> pd.DataFrame` returning one row
per (wedge_index, ring_index) with `count`, `pct`, and geometry-ready
angle/radius bounds — OR return raw per-ball `(angle_deg, distance, wedge, ring)`
and let the chart aggregate. Prefer the aggregation to live in `practice.py`
(pure, testable): return a tidy cell table `[direction, ring, count, pct]` plus
constants for wedge/ring bounds exposed for the chart to draw geometry. Batted
balls only (`hit_type in {1,2,3}`), optional `hit_types` filter for chip sync.

#### B5b — Landing scatter (upgrade `charts.spray_chart_fig`)
- Keep the Plotly field (foul lines, arc, infield diamond) and per-hit-type
  colors.
- Extend `P.spray_points` to also carry `distance_feet` and `exit_velocity` so the
  scatter can add hover: `"{hit type}<br>Distance: {d:.0f} ft<br>Exit Velo:
  {ev:.1f} mph"` via `customdata` + `hovertemplate`.
- Accept an active-hit-types filter (applied in the tab/callback before drawing).

#### B5c — Contact-Type bar (recolor `charts.contact_type_bar`)
- Per-bar `marker_color` from a shared hit-type color map (GB `#7a5230`,
  LD `#9A0021`, FB `#0076A5`, Miss/Foul grey `#5a5a5a`) instead of all-crimson.
- Colors come from one module-level map reused by fan legend / scatter / bar so
  they never drift (promote `_HIT_COLORS` to the canonical source; add Miss/Foul).

#### B5d — Chip callback
Add an `sf`-style toggle for the batted-ball chips (mirror the existing
`_sfz_*`/`_lm_*` pattern): a `dcc.Store` of active hit types, a toggle callback,
a styles callback, and a body callback that re-renders both graphs filtered to the
active set. Component-id prefix `bb` (e.g. `bb-chip`, `bb-active`, `bb-body`).

### B6 — Remove Session-type and Exclude-test controls
Delete from `layout.serve_layout`:
- the "Session" `dcc.Dropdown(id="prac-session")` block,
- the "Options" `dcc.Checklist(id="prac-exclude-test")` block.

Hardcode the behavior:
- `prac-filters` store seeds `session="All session types"`, `exclude_test=True`
  (unchanged defaults).
- `callbacks._on_filters`: drop `Input("prac-session")`, `Input("prac-exclude-test")`
  and `Output("prac-session","options")`; compute with `session="All session
  types"` and `exclude_test=True` fixed.
- Downstream readers (`_load_pitch`, `_render`, `_sidebar`) already read
  `exclude_test`/`session` from the store — they keep working with the fixed
  values.

`P.session_options` and the session-filter branch in `P.apply_filters` stay (still
unit-tested; harmless when always called with "All session types").

---

## C. Pitching dashboard (this dashboard only)

### C7 — Colored pitch names in tables
`app/dashboards/pitching/tables.py::df_table` gains optional per-cell text
coloring. When the table has a pitch column (default column name `"Pitch"`, or a
passed `color_col`), add `style_data_conditional` entries: for each distinct pitch
type value, `{ "if": {"filter_query": '{Pitch} = "<type>"', "column_id":
"Pitch"}, "color": P.pitch_color(type), "fontWeight": "bold" }`.

Apply to tables with a Pitch/type column:
- Pitch Characteristics (`tabs/pitch_breakdown.py`),
- All Pitches (`tabs/location_movement.py`),
- RHH/LHH usage tables (`tabs/rhh_lhh.py`) if they carry a pitch column.

Signature: `df_table(df, id_=None, color_col="Pitch")`; no-op when `color_col`
absent from `df.columns`.

### C8 — Labeled hovers on pitching charts
Add explicit `hovertemplate`s where charts currently fall back to `(x, y)`:
- `fig_velo_by_pitch` (Velocity Across Outing): `"Pitch No: %{x}<br>Velo:
  %{y:.1f} mph<br>%{fullData.name}<extra></extra>"`.
- `fig_movement`: `"%{fullData.name}<br>HB: %{x:.1f} in<br>IVB: %{y:.1f} in
  <extra></extra>"`.
- `fig_velo_by_inning` (bar): `"Inning %{x}<br>Avg Velo: %{y:.1f} mph<extra>
  </extra>"`.
- `fig_outings_velo_trend`: date + velo labels per line.
- `fig_location` / `fig_location_split` already carry a labeled Result hover —
  extend to include plate side/height if trivial, otherwise leave.

### C9 — Movement 1σ ellipses
`fig_movement` gains a translucent covariance ellipse per pitch type (≥3 points),
matching the PDF report's movement map. For each pitch type: mean (μx, μy) +
2×2 covariance → 1σ ellipse polygon (eigen-decomposition, ~40-point polygon),
drawn as a filled `go.Scatter(fill="toself")` in the pitch color at low alpha
(~0.15), under the markers. Reuse the report's approach in `app/reports/plots.py`
as reference (do not import matplotlib — build the polygon with numpy for Plotly).

---

## D. Catching dashboard

### D9b — Un-squish Static Framing facets
`app/dashboards/catching/charts.py::framing_facets` currently uses
`make_subplots(rows=1, cols=n)`, so Zone Location (4 values) renders 4-across and
cramped. Change to a **max-2-columns grid**:
- `cols = min(2, n)`, `rows = ceil(n / 2)`.
- Map facet index → `(row, col)`; keep the per-facet `_zone_frame`,
  `_scatter_traces`, `_base_axes`, and `scaleanchor` wiring (anchor each subplot to
  its own x-axis id).
- Height scales with rows (e.g. `~360 * rows`), add vertical spacing.
- 2-value facets (Batter Side, Pitcher Side, Pitch Speed) stay 1×2 — visually
  unchanged.

---

## Testing

Follow existing repo conventions (pure data helpers get unit tests; Dash render
functions get "renders without error / has expected component" smoke tests;
live-DB tests unguarded per the existing pattern).

- **B3:** `swing_decision_trend_fig` produces string date tick labels (no epoch).
- **B4:** `zone_chip_row` emits 13 chips labeled `"Zone N"`, none for Zone 0;
  disabled flag set for zones absent from the df; `sfz-active` excludes empties.
- **B5:** `P.spray_fan` returns 15 cells summing to 100% over batted balls;
  `hit_types` filter narrows counts; `P.spray_points` carries distance +
  exit_velocity; `spray_distribution_fan` / upgraded `spray_chart_fig` /
  recolored `contact_type_bar` render without error; chip toggle callback filters
  both.
- **B6:** layout no longer contains `prac-session` / `prac-exclude-test`;
  `_on_filters` runs without those inputs and still defaults to all-sessions /
  exclude-test.
- **C7:** `df_table` includes `style_data_conditional` colored entries when a
  Pitch column is present; none when absent.
- **C8/C9:** movement/velo figures carry `hovertemplate`s; `fig_movement`
  includes one ellipse trace per pitch type with ≥3 points.
- **D9b:** `framing_facets` with 4 values yields a 2×2 subplot grid (rows=2).

Full suite must stay green (currently 271 passing). Live smoke both roles after
implementation; restart the 8050 server by port owner (see Memory §3b GOTCHA).

## Files touched (summary)

- `app/data/practice.py` — `spray_points` (+dist/ev), new `spray_fan`,
  canonical hit-type color map, date-label helper (if extracted).
- `app/dashboards/hitting_practice/charts.py` — `spray_distribution_fan` (new),
  `spray_chart_fig` (hover), `contact_type_bar` (recolor),
  `swing_decision_trend_fig` (date labels).
- `app/dashboards/hitting_practice/tabs/batted_ball.py` — two-field layout +
  chip row.
- `app/dashboards/hitting_practice/tabs/swing_frequency.py` — `zone_chip_row`
  fixed set + labels + greying.
- `app/dashboards/hitting_practice/layout.py` — remove Session/Exclude controls.
- `app/dashboards/hitting_practice/callbacks.py` — drop session/exclude inputs;
  add batted-ball chip callbacks; zone chip style/disable handling.
- `app/dashboards/hitting/layout.py` — back-link + footnote color.
- `app/dashboards/pitching/layout.py` — footnote color.
- `app/dashboards/pitching/tables.py` — colored pitch column.
- `app/data/pitching.py` — hovertemplates + movement ellipses.
- `app/dashboards/catching/charts.py` — `framing_facets` 2-col grid.
- `tests/` — additions per above.
