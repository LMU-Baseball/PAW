# Design: Catching Dashboard Enhancements (Sub-project A)

**Date:** 2026-07-23
**Branch:** `feat/catching-enhancements` (off `feat/dashboards-date-range` — sub-project B; so the date-range picker + `range_pitches_for` are present)
**Status:** Approved for implementation (user, 2026-07-23)
**Part of:** the 3-sub-project enhancement set (B done → **A (this)** → C).

---

## 1. Motivation

Coach feedback on the rebuilt catching dashboard (from screenshots):
1. The strike-zone scatters **stretch to page width**, so the zone renders wide/skinny and misleads — it should always look like a proportionate strike zone.
2. Coaches want to **filter the framing scatter by call type** (Stolen Strike / Lost Strike / Correct Call), like the pitching dashboard's pitch-type chip filter.
3. The Caught Stealing tab is table-only; coaches want a **visual** — a time-series of caught-stealing % and average pop time across games.

## 2. Goals

1. Fixed, proportionate aspect ratio for the framing scatter and static facets (zone looks correct at any container width).
2. A call-type chip filter on Overall Framing that toggles which CallType markers show **on the scatter only**.
3. A Caught Stealing trend chart (CS% + avg pop time over game dates) alongside the existing tiles + table.

## 3. Non-goals / Deferred

- Changing the framing metric definitions (unchanged from the rebuild).
- Pitch Level video tab; PO/A/E scrape (still deferred).
- Enriching sparse caught-stealing data — the trend is thin by nature (~2–6 attempts per catcher per season); we present what exists.

## 4. Confirmed decisions (brainstorming)

- **Chips filter the scatter only.** The Framing Summary table stays computed from the full (dropdown-filtered) df — it is already a per-call breakdown, so filtering it by call type would be redundant/confusing.
- **CS trend follows the selection.** It plots the games in the currently loaded df: one point in single-game mode (with a note to widen the range for a trend), a per-game trend when "All games in range" is selected. This requires `game_date` on the loaded pitch df.

## 5. Architecture / components

Rewrite in place within `app/dashboards/catching/` + `app/data/catching.py`. No new packages.

### 5a. Fixed aspect (`app/dashboards/catching/charts.py`)
- `framing_scatter`: in `update_layout`/axes, add `scaleanchor="x", scaleratio=1` to the y-axis (via `fig.update_yaxes(scaleanchor="x", scaleratio=1)` alongside the existing range). Keep the existing `range` values. Plotly then holds one data-unit-x == one data-unit-y and letterboxes within the container, so the zone is always proportionate regardless of width.
- `framing_facets`: apply the same `scaleanchor`/`scaleratio` to each subplot's y-axis (per `row/col`), so every facet stays proportionate.
- No change to zone geometry, colors, or `CALLTYPE_COLORS`.

### 5b. Call-type chip filter (`app/dashboards/catching/tabs/framing.py` + `callbacks.py`)
Mirror the pitching `chip_row` pattern (`app/dashboards/pitching/tabs/location_movement.py`):
- New helper `call_chip_row()` in `framing.py`: three `html.Button` chips (Stolen Strike, Lost Strike, Correct Call) colored via `charts.CALLTYPE_COLORS`, ids `{"type": "call-chip", "index": <call>}`, plus a `dcc.Store(id="call-active", data=<all three>)`. Placed in the filter area of `render(df)`.
- `body(df, *, bat_side, pitcher_throws, pitch_speed, zone, active_calls=None)`: after applying the 4 dropdown filters to get `f`, build the summary **table from `f`** (unchanged, all calls); build the **scatter from `f` filtered to `active_calls`** (`f[f["CallType"].isin(active_calls)]` when `active_calls` is provided, else all). So chips affect only the scatter.
- `callbacks.py`: add the chip-toggle + chip-style callbacks mirroring pitching's `_lm_active` (`Input({"type":"call-chip","index":ALL}, "n_clicks")` → `Output("call-active","data")`, toggling membership) and the chip-style callback. Add `Input("call-active","data")` to the existing `_framing_body` callback so the scatter re-renders on chip toggle; pass it as `active_calls`.

### 5c. Caught Stealing trend (`app/data/catching.py`, `charts.py`, `tabs/caught_stealing.py`)
- **Data — expose `game_date` on the loaded pitch df.** Add `g.game_date` to the SELECT of `range_pitches_for` (join already present) **and** `game_pitches_for` (add the `dim_tm_game` join) so both single-game and pooled dfs carry `game_date`. Harmless extra column for the other tabs (they select specific columns). `SELECT f.*, g.game_date` — watch the `game_id` ambiguity: the existing `game_pitches_for` is `SELECT * FROM fact_tm_game_pitch` (no join) so adding a join needs `SELECT f.*, g.game_date` and a `JOIN dim_tm_game g`. Prefix nothing else (only `game_date` is added).
- **Transform** `caught_stealing_trend(df) -> pd.DataFrame`: from `caught_stealing_events(df)` grouped by `game_date`: columns `game_date`, `attempts`, `caught`, `cs_pct` (caught/attempts*100), `avg_pop` (mean non-null pop_time). Only dates with ≥1 attempt. Sorted by `game_date`. Empty df → empty frame with those columns. PROVISIONAL, docstring'd.
- **Chart** `caught_stealing_trend_fig(trend_df) -> go.Figure`: dual-axis line chart — CS% (crimson `#9A0021`, left y-axis, 0–100) and Avg Pop time (blue `#0076A5`, right y-axis) over `game_date` (x). Markers sized/annotated by attempts (hover shows attempts). Teko font, transparent paper / near-white plot bg. Empty/one-point safe (a single game renders one marker per line).
- **Tab** `caught_stealing.render(df)`: keep tiles + per-attempt table; insert the trend chart (a `section("Caught Stealing Trend")` + `dcc.Graph`) between the tiles and the table. When the loaded df spans a single game, show a one-line note under the chart: "Select 'All games in range' or widen the date range to see a trend." Detect single-game via the **loaded df's distinct `game_date` count ≤ 1** (not the trend rows — a single game may have zero attempts and thus an empty trend, but the note should still show).

## 6. Interfaces (summary)

| Unit | Change |
|------|--------|
| `charts.framing_scatter` / `framing_facets` | add `scaleanchor="x", scaleratio=1` (fixed aspect) |
| `charts.caught_stealing_trend_fig(trend_df)` | NEW dual-axis CS%/pop trend |
| `catching.game_pitches_for` / `range_pitches_for` | add `game_date` column (join dim_tm_game) |
| `catching.caught_stealing_trend(df)` | NEW per-game-date CS trend transform |
| `framing.call_chip_row()` + `body(..., active_calls)` | NEW call-type chips; scatter-only filter |
| `caught_stealing.render` | insert trend chart + single-game note |
| `callbacks` | call-chip toggle + style callbacks; `call-active` Input on `_framing_body` |

## 7. Testing

- `tests/test_catching.py`: `caught_stealing_trend` on a synthetic multi-game CS df (2 dates → 2 rows, correct cs_pct/avg_pop, dates with 0 attempts excluded); empty-safe. `game_pitches_for`/`range_pitches_for` include `game_date` (live-DB, matching convention).
- `tests/test_catching_dash.py`: `framing.render` exposes `call-chip`/`call-active`; `framing.body(..., active_calls=["Stolen Strike"])` scatter shows only that call while the summary table is unchanged (assert the table row values match the all-calls `framing_table`); `charts.framing_scatter` figure has `scaleanchor=='x'` on the y-axis; `caught_stealing.render` includes a Graph; `caught_stealing_trend_fig` builds on empty + single-row + multi-row.
- Full suite stays green.

## 8. Success criteria

- Framing scatter + static facets render as a proportionate strike zone at any window width.
- Call-type chips toggle scatter markers (table unaffected).
- Caught Stealing tab shows a CS%/avg-pop trend that follows the date-range selection, with a single-game note; sparse data renders without error.
- Full suite green; single-game catching behavior otherwise unchanged.

## 9. Branch / sequencing

Base `feat/dashboards-date-range` (B). New branch `feat/catching-enhancements`. C (practice overhaul) follows. Merge chain rebuild → B → A → C at the end (user chose to keep stacking).
