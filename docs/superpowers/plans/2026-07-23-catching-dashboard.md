# Catching Stats Dashboard (Slice 1) — Implementation Plan

> **For agentic workers:** implement task-by-task; commit named files only.

**Goal:** Enable Catching hub → `/dash/catching/` with Framing / Blocking / Throws tabs,
mirroring the pitching dashboard architecture on the modern warehouse.

**Spec:** `docs/superpowers/specs/2026-07-23-catching-dashboard-design.md`

## Tasks

### Task 1: Data layer `app/data/catching.py`
- Loaders: `wh_lmu_catchers`, `games_for_catcher`, `game_pitches_for`, profile/summary
- Transforms: framing / blocking / throws (provisional)
- Tests: `tests/test_catching.py` (synthetic dfs)

### Task 2: Dash package `app/dashboards/catching/`
- Scaffold + selectors + layout + callbacks + charts/tables + 3 tabs
- Register in `app/dashboards/__init__.py`
- Tests: `tests/test_catching_dash.py`

### Task 3: Hub wire-up
- Enable Catching hub card → `/dash/catching/`
- Update `tests/test_shell.py` hub assertion

### Task 4: Design doc
- Spec checked in under `docs/superpowers/specs/`

## Notes
- Legacy R catcher app under `src/` is gitignored (RDS credentials) and was not
  available when this slice was written. Metric definitions are provisional and
  should be reconciled against `src/` once accessible.
- Live-DB loader tests require `.env` MYSQL_* credentials (same as pitching).
