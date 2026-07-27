# Design: Hitting Analytical Tabs — Balls in Play (Spray/Radial) + Last 27 PA (Sub-project H)

**Date:** 2026-07-27
**Branch:** `feat/pitch-level-video` (continues the deferred-tabs build; sub-project V already on this branch)
**Status:** Approved for implementation (user, 2026-07-27 — "go right into building" after specs)
**Part of:** deferred-tabs effort V → **H (this)** → P → D.

---

## 1. Motivation

The hitting dashboard shipped tabs 1–3 (Game Level, Plate Appearances, Zone Location); the legacy `src/app 1` had more. This adds the two most-requested deferred analytical tabs:
- **Balls in Play** — a launch-angle **radial** plot + a **spray chart** for the hitter's batted balls, with a hit-type filter. (The user explicitly named "spray charts".)
- **Last 27 PA** — a "last outings" aggregate over the hitter's most recent 27 plate appearances (batting line + batted-ball + swing decisions + a BIP spray).

## 2. Data availability (verified live)

`fact_tm_game_pitch` carries, for LMU balls in play (`pitch_call='InPlay'`, ~1409 rows): `exit_speed` (1372), `la` launch angle (1372), `bearing` (1306), `distance` (1306), `tagged_hit_type` (GroundBall/FlyBall/LineDrive/PopUp/Undefined). No image assets are needed — the radial rings and the spray field are drawn in Plotly (same approach as the practice `spray_chart_fig`).

Note: the existing hitting game-data df sets `Angle`=NaN (a legacy assumption predating the `la` column). The BIP charts therefore use a **dedicated fresh query** (`wh_bip_points`) rather than the loaded df, leaving existing transforms untouched.

## 3. Confirmed decisions

- Both tabs render from the current **selection** (batter + game or "All games in range"), queried fresh in the tab branch — same pattern as the video tab. No new columns added to the game-data store.
- **Balls in Play** operates on the loaded selection (a single game, or the whole range via the existing "All games in range" option — which already gives season-level, so no separate Game/Season toggle is built).
- **Hit-type chip filter** on Balls in Play (GroundBall/FlyBall/LineDrive/PopUp/Undefined), filtering both the radial and spray, mirroring the existing pitching `chip_row`/`lm-*` pattern.
- **Last 27 PA** = the hitter's most recent 27 PAs across all their games (ordered by game_date desc, inning desc, pa desc), passed through the existing `_finish` pipeline so the existing transforms (`game_batting_line`, `batted_ball_profile`, `swing_decisions_by_zone`) are reused unchanged, plus a BIP spray for those PAs.
- Colors: reuse hit-type palette (FlyBall crimson-ish, GroundBall blue, LineDrive orange, PopUp green, Undefined grey) — define one `_HIT_COLORS` map in hitting `charts.py`.

## 4. Architecture

### 4a. Data — `app/data/hitting_wh.py` (additions; existing functions untouched)
- `wh_bip_points(batter_tm_id, game_id) -> pd.DataFrame` — `game_id` int or list. InPlay pitches for the batter (sibling-union) in the game(s). Returns one row per BIP with: `hit_type` (tagged_hit_type; None→"Undefined"), `exit_speed`, `la`, `bearing`, `distance`, `x` = `sin(bearing°)·distance`, `y` = `cos(bearing°)·distance`, `rx` = `exit_speed/120·cos(la°)`, `ry` = `exit_speed/120·sin(la°)`, plus `Count` (`balls-strikes`), `Result`, `PitchType`, `Pitcher` for hover. Rows with the coords needed for a given chart missing are kept but that chart drops them (spray needs bearing+distance; radial needs exit_speed+la). Empty full-column frame when none. Guards empty game list → empty frame (like `video`).
- `wh_last_n_pas(batter_tm_id, n=27) -> pd.DataFrame` — the batter's most recent `n` PAs across all games, returned through `_finish` (same column shape as `wh_game_pitches`). Implementation: rank distinct (game_id, inning, pa_of_inning) by (game_date desc, inning desc, pa_of_inning desc), take the top `n`, filter pitches to those PAs, `_finish`. Empty frame when the batter has no pitches.

### 4b. Charts — `app/dashboards/hitting/charts.py` (additions)
- `_HIT_COLORS: dict` — the shared hit-type palette.
- `radial_fig(bip_df) -> go.Figure` — half-disk (θ∈[−90°,90°]) with three EV rings (40/90/120 mph, drawn at radii 1/3, 2/3, 1 with grey fills), launch-angle guide segments at 8°/25°/45°/90°, points at (`rx`,`ry`) colored by `hit_type`, EV/LA hover. Axes hidden, `scaleanchor` equal. Empty-safe.
- `spray_fig(bip_df) -> go.Figure` — foul lines (±45°), an outfield arc, an infield diamond, points at (`x`,`y`) colored by `hit_type`, distance/EV hover. `xaxis` [−250,250], `yaxis` [−20,430] with `scaleanchor="x"`. Empty-safe.

### 4c. Tabs
- `app/dashboards/hitting/tabs/balls_in_play.py`:
  - `chip_row(bip_df) -> html.Div` — a hit-type chip per type present (all active), store `bip-active`, ids `{"type":"bip-chip","index":<hit_type>}`.
  - `body(bip_df) -> html.Div` — radial + spray side by side, or an empty note.
  - `render(bip_df) -> html.Div` — `chip_row` + `html.Div(id="bip-body", children=body(bip_df))`.
- `app/dashboards/hitting/tabs/last_27.py`:
  - `render(last_df, bip_df) -> html.Div` — batting-line table + batted-ball table + swing-decision table (reusing `hitting` transforms + `tables.stat_table`) + the BIP spray for those PAs. Empty note when `last_df` is empty.

### 4d. Wiring — `app/dashboards/hitting/{layout,callbacks}.py`
- Two new tabs: `dcc.Tab("Balls in Play", value="bip")`, `dcc.Tab("Last 27 PA", value="last27")`.
- `_render_tab` branches (both read `sel`, like the video branch): 
  - `bip`: resolve game_ids from sel (game or range), `wh_bip_points`, `balls_in_play.render`.
  - `last27`: `wh_last_n_pas(bid, 27)` + `wh_bip_points(bid, <those game_ids>)`, `last_27.render`.
- Chip-filter callbacks for `bip-chip`/`bip-active`/`bip-body` mirroring the pitching `_lm_toggle`/`_lm_body`/`_lm_chip_styles` trio (filter the bip df by active hit types → re-render `body`).

## 5. Error handling / edge cases
- No BIP for the selection → empty-state note in each chart / tab.
- Missing `bearing`/`distance` → dropped from spray only; missing `exit_speed`/`la` → dropped from radial only.
- Empty game list (range with no games) → `wh_bip_points` returns empty frame (no SQL `IN ()`), matching the video helper's guard.
- Hitter with <27 PAs → Last 27 PA shows whatever exists.

## 6. Testing
- `tests/test_hitting_wh.py` additions (live DB): `wh_bip_points` returns coord columns, one row per BIP, sibling union, empty-game guard, computes x/y/rx/ry correctly for a known row; `wh_last_n_pas` returns ≤27 PAs worth of pitches with the `_finish` column shape.
- `tests/test_hitting_dash.py` additions: `radial_fig`/`spray_fig` return a `go.Figure` for empty and non-empty input; the two tabs appear in `serve_layout` source; `balls_in_play.render` contains the chip store + a Graph.

## 7. Out of scope / deferred
- The legacy heatmap-by-swing-result on Last 27 PA, and per-PA video on Balls in Play (video is its own tab from sub-project V).
- Season-level BIP as a separate control (covered by the global "All games in range").
