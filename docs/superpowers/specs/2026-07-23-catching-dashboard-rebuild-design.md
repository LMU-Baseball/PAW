# Design: Catching Dashboard Rebuild (match legacy `src/app.R`)

**Date:** 2026-07-23
**Branch:** `feat/catching-dashboard-rebuild` (off `main` @ `29f3dcd`)
**Status:** Approved for implementation (user, 2026-07-23)
**Supersedes:** the Slice-1 catching dashboard (`docs/superpowers/specs/2026-07-23-catching-dashboard-design.md`, merged commits `5a5210c`/`4aa94ba`), which was built without access to `src/` and diverged from the legacy app.

---

## 1. Motivation

The shipped catching dashboard was reconstructed **blind** — the Cursor agent that built it did not have the legacy R catcher app (`src/` is gitignored for the RDS creds). Having now read `src/app.R` ("THE CATCHER'S PAW", author Shaye O'Beirne, 2024) and verified the live warehouse, the shipped version diverges from the coaches' established design and flow:

- Its **Framing** tab uses a generic *called-strike-% on takes* metric instead of the legacy **stolen-strike / lost-strike** model that coaches know.
- It **dropped the legacy filters** (Batter Hand, Pitcher Hand, Pitch Speed, Zone) and the **Static Framing** facet views.
- It **invented Blocking and Throws tabs** that the old app never had. Both are weak on the live data:
  - **Blocking** matches `PassedBall`/`WildPitch` against `play_result`, but those values do **not exist** in the warehouse (`play_result` ∈ CaughtStealing/Double/Error/FieldersChoice/HomeRun/Out/Sacrifice/StolenBase/Single/Triple/Undefined). So "blocked" always equals the dirt count → **block% is structurally pinned at 100%** (verified live: Gamboa game = 13 dirt / 13 blocked / 100%). Only 55 `BallinDirt` events exist all season.
  - **Throws** columns are real but sparse: pop_time 145 / throw_speed 257 / exchange_time 168 across 8,744 season pitches → most single games show 0 attempts.

This rebuild realigns the dashboard to the legacy design and flow while staying on the modern Trackman warehouse.

## 2. Goals

1. Restore the legacy **stolen-strike / lost-strike framing model** and its summary table.
2. Restore the **4 legacy filters** and the **Static Framing** facet views.
3. Replace the broken Blocking tab and the empty-most-games Throws tab with a single **Caught Stealing** tab backed by real `StolenBase`/`CaughtStealing` outcomes + pop time.
4. Keep the PAW shell, role scoping, and split-id handling already in place.

## 3. Non-goals / Deferred

- **Pitch Level video tab** (CF + Home-plate video + clickable table) — deferred like hitting/pitching; needs the S3 video model (`vw_pitch_video`) wired.
- **PO / A / E sidebar tiles** via lmulions.com scrape — the legacy sidebar scraped fielding stats; we use warehouse-derived framing tiles instead (§7). A scrape can be a later slice.
- Umpire / park framing adjustments; catcher postgame PDF.

## 4. Architecture

**Rewrite in place** — no new package. Same paths, route, and shell so navigation and tests stay stable:

```
app/dashboards/catching/
  __init__.py      build_catching_dash(server) @ /dash/catching/   (UNCHANGED)
  index.py         shell.index_string()                            (UNCHANGED)
  selectors.py     role-aware options + resolve_catcher            (UNCHANGED — keep)
  layout.py        sidebar + selector row + 3 tabs                 (REVISED: tiles + tabs)
  callbacks.py     selection -> stores -> tabs + filter callbacks  (REVISED)
  tables.py        DataTable builder                               (UNCHANGED — keep df_table)
  charts.py        framing scatter (stolen/lost) + facet figures   (REWRITTEN)
  tabs/
    framing.py         Overall Framing (REWRITTEN)
    static_framing.py  Static Framing facets (NEW)
    caught_stealing.py Caught Stealing (NEW; replaces throws.py + blocking.py)
app/data/catching.py   warehouse loaders + transforms (REVISED)
```

**Removed files:** `tabs/blocking.py`, `tabs/throws.py`.

**Warehouse + scoping (unchanged from the shipped version):**
- Source: `fact_tm_game_pitch` + `dim_tm_game` + `tm_player` + `tm_team`. Canonical id = `catcher_id`. LMU catchers = received while `pitcher_team = 'LOY_LIO'` (`LMU_PITCHER_TEAM`).
- Coach picks any LMU catcher + game; **player locked to self** via `resolve_catcher` (unchanged).
- Split-id sibling union retained (`_sibling_catcher_ids`, `game_pitches_for`, `games_for_catcher`).
- **No DB access in tabs/charts/tables** — pure `df → components`. Only selectors/callbacks and the data layer touch the warehouse.

## 5. Data layer (`app/data/catching.py`)

### Kept (unchanged)
`_in_clause`, `_sibling_catcher_ids`, `wh_lmu_catchers`, `catcher_name`, `catcher_tm_id_for`, `games_for_catcher`, `game_pitches_for`, `catcher_profile`, `game_pitches_season`, `game_context`, `_col`.

### Removed
`framing_by_zone`, `framing_overall`, `framing_shadow`, `framing_by_batter_side` (CS%-on-takes model), `_is_dirt_row`, `dirt_events`, `blocking_summary`, `throw_attempts`, `throws_summary`, and the `_DIRT_CALLS`/`_PASSED_WILD`/`_LOW_BALL_CALLS` constants.

### New / revised transforms (pure `df -> df|dict`, provisional & docstring'd)

**Pitch classification helpers**
- `PITCH_SPEED_MAP` — recode of `tagged_pitch_type` → `Fastball` / `Offspeed`, matching the legacy R map (Fastball/Sinker/Cutter/Splitter/TwoSeamFastBall/FourSeamFastBall/OneSeamFastBall → Fastball; Slider/ChangeUp/Changeup/Curveball/Knuckleball/Undefined → Offspeed).
- `add_framing_cols(df) -> df` — the single source of derived columns used by every framing view. Adds:
  - `Zone` ∈ {Heart, Shadow, Chase, Waste} via `hitting_wh.attack_zone(plate_loc_side, plate_loc_height)`.
  - `InZone` (bool) — **geometry-derived**: pitch inside the rulebook strike-zone box. Provisional definition: `abs(side*12) <= 10 and abs(height*12 - 30) <= 13` (matches the solid box drawn in the legacy plot; `src/app.R` used a DB `InZone` column that the warehouse lacks — `zi` is NULL). Coach-confirmable one-liner.
  - `PitchSpeed` ∈ {Fastball, Offspeed} via `PITCH_SPEED_MAP`.
  - `CallType` ∈ {Stolen Strike, Lost Strike, Correct Call}: `Stolen` = `not InZone and pitch_call == 'StrikeCalled'`; `Lost` = `InZone and pitch_call == 'BallCalled'`; else `Correct`. Non-take pitches (swings/in-play) are `Correct` (they carry no framing signal), mirroring the legacy `ifelse` chain.
  - `_x`, `_y` catcher-view plot coords: `_x = side * -12`, `_y = height*12 - 30` (matches `src/app.R` framing_overall + current charts).
- `apply_framing_filters(df, *, bat_side, pitcher_throws, pitch_speed, zone) -> df` — each arg is `"All"` or a concrete value; `"All"` = no filter on that dimension. Filters on `batter_side`, `pitcher_throws`, `PitchSpeed`, `Zone`. (Mirrors the legacy `*_choice()` reactives.)

**Framing summary (legacy table)**
- `framing_table(df) -> dict` — one-row summary computed on `add_framing_cols` output over the (already-filtered) df. Keys exactly matching the legacy `framing_table_df`:
  - `net_strikes` = stolen − lost (all zones)
  - `steal_pct` = round(lost / total_takes * 100, 1)  *(note: legacy labels this "Steal%" but computes lost/total — reproduced faithfully; flagged as a legacy quirk, see §10)*
  - `shadow_net`, `shadow_steal_pct` = stolen / shadow_total * 100
  - `heart_net`, `heart_loss_pct` = lost_heart / heart_total * 100
  - `waste_net` (Waste+Chase), `waste_steal_pct` = lost_{waste+chase} / {waste+chase}_total * 100
  - Guards div-by-zero → `None`/`—`.
- `framing_season_tiles(catcher_id) -> dict` — SQL-aggregate season tiles: `games`, `pitches`, `net_strikes`, `steal_pct`. Computed with `SUM(...)` over the sibling-union catcher rows using the same geometry InZone expressed in SQL (`ABS(plate_loc_side*12) <= 10 AND ABS(plate_loc_height*12 - 30) <= 13`). Does not pull all pitches into pandas. Replaces `season_summary`.

**Caught stealing**
- `CS_RESULTS = {'StolenBase', 'CaughtStealing'}`.
- `caught_stealing_events(df) -> df` — rows where `play_result in CS_RESULTS`; adds `Caught` bool (`play_result == 'CaughtStealing'`) and surfaces `pop_time`/`exchange_time`/`throw_speed` (defensive `_col` lookup; NaN when absent).
- `caught_stealing_summary(df) -> dict` — `attempts`, `caught`, `cs_pct` (caught/attempts*100), `avg_pop` (mean of non-null pop_time), all `None`/`—` when empty.

## 6. Tabs

### Overall Framing (`tabs/framing.py`, rewritten)
- **Filter row** (4 dropdowns, ids `fr-bat`/`fr-throws`/`fr-speed`/`fr-zone`), each `All` + legacy choices:
  - Batter Hand: All / Left / Right
  - Pitcher Hand: All / Left / Right
  - Pitch Speed: All / Fastball / Offspeed
  - Zone Location: All / Heart / Shadow / Chase / Waste
- **Zone-location scatter** (`charts.framing_scatter`): takes plotted at `_x`/`_y`, colored by `CallType` — **Stolen Strike = black, Lost Strike = crimson `#9A0021`, Correct Call = light gray** (see `CALLTYPE_COLORS`, §8) — over the legacy zone frame (home-plate pentagon + 3 nested rectangles: rulebook box solid, Heart + Shadow dashed). Hover: velo, batter side, pitcher throws, pitch speed, call.
- **Framing summary table** (`tables.df_table`) rendering `framing_table` as a one-row, human-labeled table (Net Strikes / Steal% / Shadow Net / Shadow Steal% / Heart Net / Heart LOSS% / Waste Net / Waste Steal%).
- A short provisional-definition caption.

### Static Framing (`tabs/static_framing.py`, new)
- Four faceted scatters (`charts.framing_facets(df, by=...)`) stacked vertically, each split into small multiples, same color scheme, **not filtered** (whole-game view — mirrors legacy `static_*`):
  - by `batter_side` ("Batter Side")
  - by `pitcher_throws` ("Pitcher Side")
  - by `PitchSpeed` ("Pitch Speed")
  - by `Zone` ("Zone Location")
- Implemented with Plotly facets (`px`-style or `go` subplots) — static, no per-tab callbacks.

### Caught Stealing (`tabs/caught_stealing.py`, new)
- Tiles: **Attempts**, **Caught**, **CS%**, **Avg Pop (s)** from `caught_stealing_summary`.
- Per-attempt table from `caught_stealing_events`: Inning, Pitcher, Result (Caught / Stolen), Pop (s), Exchange (s), Throw (mph) — blanks where timing absent.
- Empty state: "No stolen-base attempts recorded for this game." when 0 attempts.

## 7. Layout / sidebar / callbacks

- **Sidebar** (`layout.sidebar`): photo + `#jersey` + name/position (unchanged shape), tiles **GAMES / PITCHES / NET STRIKES / STEAL%** from `framing_season_tiles`. Caption updated ("Season framing tiles — provisional stolen/lost model").
- **Selector row + scoreboard**: unchanged (Catcher dd disabled for players, Game dd, scoreboard `date · vs/@ OPP · type`).
- **Tabs**: `dcc.Tabs` values `framing` / `static` / `caught`.
- **Callbacks** (`callbacks.py`):
  - `_on_catcher`, `_on_selection`, `_on_load_data` — unchanged (selection → stores → `game-data`).
  - `_render_tab` — routes to `framing.render` / `static_framing.render` / `caught_stealing.render`; keeps the empty-df guard.
  - **New** `_framing_filtered` callback: inputs = the 4 filter dropdowns + `game-data`; output = the framing scatter + summary table container (`fr-body`). Body/skeleton split mirrors the pitching dashboard's `lo-body`/`_lo_body` pattern so the filters re-render only the framing content, not the whole tab.

## 8. Charts (`charts.py`, rewritten)

- `_zone_frame(fig)` — adds the legacy home-plate pentagon (5 segments) + 3 nested rectangles (rulebook solid, Heart dashed, Shadow dashed) in catcher-view inches. Shared by scatter + facets.
- `CALLTYPE_COLORS = {"Stolen Strike": "#000000", "Lost Strike": "#9A0021", "Correct Call": "#cccccc"}` (Lost = crimson-red for brand fit; provisional).
- `framing_scatter(df) -> go.Figure` — single panel; markers colored by `CallType`; Teko font, transparent paper / near-white plot bg (reads over palms), axes hidden, fixed range matching legacy (~±40 x, ±25 y adjusted).
- `framing_facets(df, by, title) -> go.Figure` — small multiples over distinct `by` values, same frame + colors.

## 9. Testing

- `tests/test_catching.py` — **rewritten**, synthetic DataFrames, no DB:
  - `add_framing_cols`: Stolen/Lost/Correct classification on hand-built in/out-of-zone + StrikeCalled/BallCalled rows; `Zone`/`PitchSpeed`/`InZone` correctness; non-take rows → Correct.
  - `apply_framing_filters`: `All` passthrough + each concrete filter narrows correctly.
  - `framing_table`: Net Strikes, Steal%, Shadow/Heart/Waste math on a known fixture; div-by-zero → None.
  - `caught_stealing_events`/`caught_stealing_summary`: CS%/avg pop on a fixture incl. a no-attempt empty case.
  - `PITCH_SPEED_MAP` recode.
- `tests/test_catching_dash.py` — keep selector role-scoping tests (`resolve_catcher` self-only / discards requested id / coach options); update sample df to the new columns; assert `build_catching_dash` mounts and each of the 3 tab `render()` functions returns a component on a synthetic df; assert the framing tab exposes the 4 filter dropdown ids.
- Live-DB tests follow the existing unguarded convention (skip only via missing `.env`, same as pitching).
- Update any hub/shell assertions if tab labels are referenced (they are not expected to be).
- **Target: full suite green** (currently 228; net change from removing 2 tabs' tests + adding new ones).

## 10. Provisional definitions (coach-confirmable, each a one-line change)

- **InZone geometry** box `abs(side*12) ≤ 10`, `abs(height*12−30) ≤ 13`. The legacy app relied on a Trackman `InZone` DB flag absent from the warehouse.
- **Legacy "Steal%" quirk:** `src/app.R` labels the metric "Steal%" but computes `Lost Strikes / total takes` (i.e., a *loss* rate), and "Shadow Steal%" as `stolen / shadow_total`. We reproduce the legacy formulas verbatim so numbers match what coaches saw, and flag the naming inconsistency for coach confirmation rather than silently "fixing" it.
- **Pitch Speed** Fastball/Offspeed recode uses `tagged_pitch_type` (same as legacy `TaggedPitchType`).
- **Caught Stealing** counts every `StolenBase`/`CaughtStealing` charged on a pitch attributed to the catcher; no pickoff/PB nuance.

## 11. Success criteria

- Home → Catching → Stats Dashboard opens `/dash/catching/`.
- Coach picks any LMU catcher + game; all 3 tabs render; the 4 framing filters reactively re-render the scatter + summary table.
- Player is locked to self.
- Framing numbers reproduce the legacy stolen/lost model; season sidebar tiles show Games/Pitches/Net Strikes/Steal%.
- Blocking and Throws tabs are gone; no dead PassedBall/WildPitch code remains.
- Hitting / pitching dashboards unchanged; full test suite green.
