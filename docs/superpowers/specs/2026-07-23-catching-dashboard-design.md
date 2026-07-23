# Design: Catching Stats Dashboard (Slice 1)

**Date:** 2026-07-23
**Branch:** `cursor/catching-dashboard-1c83`
**Status:** Approved for implementation (inferred from hub card + pitching/hitting patterns)

---

## 1. Motivation

The Catching hub (`/catching`) currently shows a single disabled card —
**"Blocking / Framing / Throws"**. Hitting and Pitching already have live Dash
game-stats dashboards. Coaches need the same for catchers.

The legacy R Shiny catcher sources live under `src/` (gitignored — contains RDS
credentials) and were **not** available in this environment. Slice 1 therefore
reconstructs the three capabilities named on the hub card on the modern warehouse,
mirroring the pitching dashboard's shell / selectors / tabs architecture.

## 2. Goal

1. Enable the Catching hub card → `/dash/catching/`.
2. Ship a role-aware Catching Dash module with three tabs:
   - **Framing** — called-strike rate on takes by attack zone (Heart / Shadow / Chase / Waste).
   - **Blocking** — dirt / blocked vs passed / wild outcomes around the plate.
   - **Throws** — pop time / exchange / throw speed on throw attempts.
3. Reuse the shared Dash shell (`app/dashboards/shell.py`) and roster media.

## 3. Architecture decisions

- **Warehouse-based.** `fact_tm_game_pitch` + `dim_tm_game` + `tm_player` +
  `tm_team`. Same decision as hitting / pitching. Not legacy `GAMES`.
- **Canonical id = warehouse `catcher_id`** (joinable to `tm_player.player_id`).
  A player's `current_user.trackman_id` maps to catcher via `catcher_tm_id`,
  parallel to pitching's `pitcher_tm_id` → `pitcher_id` resolution.
- **LMU scope.** Catchers who received for LMU pitchers:
  `pitcher_team = 'LOY_LIO'` (catcher is always on the pitching team). Constant
  `LMU_CATCHER_TEAM = "LOY_LIO"` for any direct catcher-team filter if present.
- **Role scoping.** Coach: any LMU catcher + game. Player: locked to self via
  `resolve_catcher` (self-only guard).
- **Package layout** mirrors pitching:

```
app/dashboards/catching/
  __init__.py      build_catching_dash(server) @ /dash/catching/
  index.py         INDEX_STRING via shell.index_string()
  selectors.py     pure role-aware options + resolve_catcher
  layout.py        sidebar + catcher/game selectors + 3 tabs
  callbacks.py     selection → stores → tabs
  tables.py        DataTable builder
  charts.py        framing zone scatter, pop-time chart
  tabs/
    framing.py
    blocking.py
    throws.py
app/data/catching.py   warehouse loaders + metric transforms
```

- **No DB in tabs/charts/tables.** Pure df → components. Only selectors/callbacks
  and the data layer touch the warehouse.

## 4. Tabs

### Framing
- Filter to **takes** (no swing): PitchCall in
  `{StrikeCalled, BallCalled, BallinDirt, HitByPitch}` (and close variants).
- Strike-zone scatter of takes, colored by call (strike vs ball).
- Called-strike % table by attack zone (reuse `hitting_wh.attack_zone` geometry)
  and overall. Provisional: no park/umpire adjustment.

### Blocking
- Candidate dirt pitches: low plate height and/or PitchCall / PlayResult
  indicating dirt / passed ball / wild pitch (provisional classifier).
- Summary tiles: dirt pitches, blocked, passed/wild, block %.
- Table of dirt events (inning, count, pitcher, call/result).

### Throws
- Rows with non-null `pop_time` and/or `throw_speed` (warehouse throw attempts).
- Summary: attempts, avg/min pop time, avg exchange, avg throw speed.
- Scatter / distribution of pop time; per-attempt table.

## 5. Data layer (`app/data/catching.py`)

| Function | Role |
|----------|------|
| `wh_lmu_catchers()` | Dropdown rows; dedupe split Trackman ids by name |
| `games_for_catcher(catcher_id)` | Games newest first with `GameLabel` |
| `game_pitches_for(game_id, catcher_id)` | Pitch df for one catcher-game (sibling-id union) |
| `catcher_profile(catcher_id)` | Name, throws/bats best-effort, jersey/photo |
| `season_summary(catcher_id)` | Games caught, pitches received, framing CS%, block % |
| `framing_by_zone(df)` / `takes(df)` | Framing transforms |
| `blocking_summary(df)` / `dirt_events(df)` | Blocking transforms |
| `throws_summary(df)` / `throw_attempts(df)` | Throws transforms |

Column expectations (warehouse snake_case, verified against live DB when available;
code tolerates missing optional throw columns by returning empty/placeholders):

- Identity: `catcher_id`, `catcher_tm_id`, `catcher_name`
- Location/call: `plate_loc_side`, `plate_loc_height`, `pitch_call`, `play_result`,
  `korbb`, `balls`, `strikes`, `inning`, `pitch_no`, `pitcher_name`, `tagged_pitch_type`
- Throws (optional): `pop_time`, `exchange_time`, `throw_speed`

## 6. Navigation

- Catching hub card enabled → `/dash/catching/`
- Dash header back-link → `/catching` (`← Catching`)

## 7. Testing

- `tests/test_catching.py` — transforms on synthetic DataFrames (no DB).
- `tests/test_catching_dash.py` — selectors + mount; live-DB fixtures when `.env` present
  (same unguarded convention as pitching; skip gracefully only if we add a guard —
  match pitching: unguarded live queries).
- Update hub assertion in `tests/test_shell.py` / home tests so Catching card is linked.

## 8. Deferred

- Full port of any remaining R catcher tabs once `src/` is available outside gitignore.
- Coach notes, video, advanced framing run values / umpire adjustments.
- Catcher postgame PDF via `app/reports/`.

## 9. Success criteria

- Home → Catching hub → Stats Dashboard opens `/dash/catching/`.
- Coach picks any LMU catcher + game; all three tabs render.
- Player locked to self.
- Hitting / pitching dashboards unchanged; suite stays green for non-DB tests.
