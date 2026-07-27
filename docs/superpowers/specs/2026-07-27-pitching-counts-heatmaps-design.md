# Design: Pitching Analytical Tabs — Counts + Heatmaps (Sub-project P)

**Date:** 2026-07-27
**Branch:** `feat/pitch-level-video` (deferred-tabs build; V + H already on this branch)
**Status:** Approved for implementation (user, 2026-07-27 — build straight through after specs)
**Part of:** V → H → **P (this)** → D.

---

## 1. Motivation

The pitching dashboard shipped 4 of the legacy `src/app 4`'s tabs (Pitch Breakdown, Location/Movement, RHH v. LHH, Last Outings) + the new Pitch Level video tab (sub-project V). Two deferred analytical tabs remain:
- **Counts** — pitch usage + location filtered by count state(s) (0-0, 1-2, …).
- **Heatmaps** — a 2-D location density heatmap filtered by pitch type(s) / batter hand / count state(s).

## 2. Confirmed decisions

- Both tabs render from the loaded **game-data** df (the selected outing, or the "All games in range" pool) — same as the existing Location/Movement and RHH v. LHH tabs. No new queries needed; the df already has `balls`, `strikes`, `plate_loc_side`, `plate_loc_height`, `batter_side`, `tagged_pitch_type`.
- **Counts** = a count-state multiselect dropdown → a pitch-usage table + a location scatter (colored by pitch type), filtered to the chosen counts. Default: all counts selected.
- **Heatmaps** = three filters (pitch type multiselect, batter side All/Right/Left, count-state multiselect) → a white→yellow→red 2-D density heatmap over the strike zone. Default: all pitch types, All sides, all counts.
- Reuse existing pitching figures/transforms: `fig_location`, `pitch_usage`, `pitch_type`, `pitch_color`, `_add_zone`, `_base_layout`, `tables.df_table`. Add one new figure `fig_heatmap`.
- Coordinate system matches the existing `fig_location` (feet; zone box via `_add_zone`; ranges [-2.5,2.5] × [0,5]).

## 3. Architecture

### 3a. Data / figure — `app/data/pitching.py` (add one figure + one helper)
- `count_states(df) -> list[str]` — sorted distinct `"{balls}-{strikes}"` present (used to build dropdown options).
- `fig_heatmap(df) -> go.Figure` — `go.Histogram2dContour` of (`plate_loc_side`, `plate_loc_height`) with a white→yellow→red colorscale (`contours_coloring="fill"`, `line_width=0`, `showscale=False`), the strike-zone box drawn via `_add_zone`, axes ranged like `fig_location`. Empty-safe (renders just the zone box when no pitches).

### 3b. Tabs
- `app/dashboards/pitching/tabs/counts.py`:
  - `count_options(df) -> list[dict]` — dropdown options from `count_states(df)`.
  - `body(df) -> html.Div` — a pitch-usage table (`pitch_usage` → display cols Pitch/Count/Usage %) + `fig_location(df)`.
  - `render(df) -> html.Div` — a `dcc.Dropdown(id="counts-dd", multi=True)` (default all counts) + `html.Div(id="counts-body", children=body(df))`.
- `app/dashboards/pitching/tabs/heatmaps.py`:
  - `body(df) -> html.Div` — `dcc.Graph(figure=P.fig_heatmap(df))`.
  - `render(df) -> html.Div` — three controls (`hm-pt` pitch-type multiselect default all, `hm-side` All/Right/Left, `hm-count` count multiselect default all) + `html.Div(id="hm-body", children=body(df))`.

### 3c. Wiring — `app/dashboards/pitching/{layout,callbacks}.py`
- Two new tabs: `dcc.Tab("Counts", value="counts")`, `dcc.Tab("Heatmaps", value="heatmaps")` (after the Pitch Level tab from V).
- `_render_tab` branches (both use the game-data `df`, after the empty guard): `counts` → `counts.render(df)`, `heatmaps` → `heatmaps.render(df)`.
- Callbacks:
  - `_counts_body(counts, game-data)` — filter df to selected count states → `counts.body(df_f)`.
  - `_hm_body(pts, side, counts, game-data)` — filter df by pitch type / batter side / count → `heatmaps.body(df_f)`.

## 4. Error handling / edge cases
- No pitches / empty filter selection → the tables/figures render an empty state (empty usage table, zone-box-only heatmap).
- "All games in range" → the pooled df flows through unchanged (counts/heatmap aggregate the range).
- Missing plate coords → dropped by the figures (existing `dropna`).

## 5. Testing
- `tests/test_pitching.py` additions (live DB or synthetic df): `fig_heatmap` returns a `go.Figure` for empty and non-empty input; `count_states` returns sorted `"b-s"` strings.
- `tests/test_pitching_dash.py` additions: the two tabs appear in `serve_layout`; `counts.render`/`heatmaps.render` contain their control ids + body div; `counts.body`/`heatmaps.body` handle empty df.

## 6. Out of scope / deferred
- Per-pitch video click-through on the Counts location scatter (video is its own tab from V).
- Stuff+/Runners hover fields from the legacy app (not in the warehouse df).
