# Catching Stats Dashboard (Slice 1) — Implementation Plan

> **For agentic workers:** implement task-by-task; commit named files only.

**Goal:** Enable Catching hub → `/dash/catching/` with Framing / Blocking / Throws tabs,
mirroring the pitching dashboard architecture on the modern warehouse.

**Spec:** `docs/superpowers/specs/2026-07-23-catching-dashboard-design.md`

## Tasks

### Task 1: Data layer `app/data/catching.py` — DONE
- [x] Loaders: `wh_lmu_catchers`, `games_for_catcher`, `game_pitches_for`, profile/summary
- [x] Transforms: framing / blocking / throws (provisional)
- [x] Tests: `tests/test_catching.py` (synthetic dfs)
- [x] Season summary via SQL aggregates (no full-season pitch pull)
- [x] Align take/dirt calls with verified warehouse `pitch_call` values

### Task 2: Dash package `app/dashboards/catching/` — DONE
- [x] Scaffold + selectors + layout + callbacks + charts/tables + 3 tabs
- [x] Register in `app/dashboards/__init__.py`
- [x] Tests: `tests/test_catching_dash.py`
- [x] Framing tab: Shadow CS% tile + LHH/RHH split table

### Task 3: Hub wire-up — DONE
- [x] Enable Catching hub card → `/dash/catching/`
- [x] Update `tests/test_shell.py` hub assertion

### Task 4: Design doc — DONE
- [x] Spec checked in under `docs/superpowers/specs/`

### Task 5: Live-DB verification (needs `.env` MYSQL_*)
- [x] Live fixtures in `tests/test_catching_dash.py` (unguarded, skip if no catchers)
- [ ] Run against warehouse: catcher dropdown, all three tabs, season tiles
- [ ] Confirm throw columns (`pop_time` / `exchange_time` / `throw_speed`) exist;
      adjust `_col` aliases if warehouse naming differs
- [ ] Confirm `catcher_id` / `catcher_tm_id` populated for LMU (`pitcher_team='LOY_LIO'`)

### Task 6 (next slice — deferred)
- [ ] Reconcile metrics against legacy R catcher app once `src/` is available locally
- [ ] Last-N games rollup tab (mirrors pitching Last Outings)
- [ ] Pitch-type chip filter on framing scatter
- [ ] Catcher postgame PDF via `app/reports/`

## Notes
- Legacy R catcher app under `src/` is gitignored (RDS credentials).
- Take calls = `StrikeCalled` + `BallCalled`/`BallinDirt`/`BallIntentional`/`AutomaticBall`
  (verified in `app/data/pitching.py` warehouse notes). HitByPitch excluded.
- Live-DB loader tests require working MYSQL_* credentials pointing at the analytics RDS.
