# Hitting Practice Dashboard (HitTrax) — Implementation Plan

**Spec:** `docs/superpowers/specs/2026-07-23-hitting-practice-dashboard-design.md`
**Upstream UI:** `BRADhaskell/lmu-baseball-practice-analytics` → `dashboard/app.py`

## Tasks

### Task 1: Data layer — DONE
- [x] `app/data/practice.py` loaders + filters + metrics (heatmap, SDS, trim)

### Task 2: Dash package — DONE
- [x] `/dash/hitting-practice/` with Pitch Zones / Swing Frequency / Contact Overview / Session Tables
- [x] Shared shell + back link to Hitting hub

### Task 3: Hub wire-up — DONE
- [x] Enable Practice Dashboard card on Hitting hub
- [x] Update `tests/test_shell.py`

### Task 4: Tests — DONE
- [x] `tests/test_practice.py`, `tests/test_hitting_practice_dash.py`

## Notes
- Practice tables must exist in the same MySQL RDS (`practice_plays`, etc.).
- Live loaders skip/empty-safe if tables are missing.
- PDF/CSV exports deferred.
