# Roster placeholder ids → real Trackman ids (why data can "disappear")

## What happened (2026-10-13 scrimmage)

After the first fall scrimmage, every pitcher who threw lost their
**Built on the Bluff** strength numbers, Gas Station rows (and the Gas Station
videos linked from them), scripts and pen results. Nothing was deleted. The rows
were still in the database, saved under the wrong player id.

## Why

- Before a player has a single tracked pitch in a season, PAW lists them from
  `lmu_roster` (`data/rosters/<season>.json`) with a **negative placeholder id**
  (`-roster_id`). Anything a coach saves for them before their first outing,
  in Built on the Bluff, Cauldron or Velo Board, is stored under that negative id.
- The first time they show up in `GAMES` (scrimmage, live AB in a game, real
  game), the dropdowns switch them to their **real Trackman PitcherId**.
- `lmu_roster.reconcile_ids` exists to move saved rows from the placeholder id
  to the real id. It only covered Cauldron and Velo Board. The Bluff tables
  weren't on its list, and it only ran when someone remembered
  `flask roster-reconcile`. So the page looked up the real id, found nothing,
  and showed blank.

## The fix (so it can't happen again)

1. `reconcile_ids` now also moves every Built on the Bluff table
   (`splash_plans`, `splash_engine_readings`, `splash_gas_station`,
   `splash_scripts`, `splash_script_rows`, `splash_pen_results`,
   `splash_movement`, legacy `splash_engine_metrics`, and its dated
   `splash_engine_history`).
2. It runs **automatically after every GAMES load**, both the cron pipeline
   (`flask pipeline-load`) and `scripts/load_game_csv.py`, via
   `lmu_roster.reconcile_after_load`.
3. Bluff rows are **never deleted** by the reconcile. They move one
   (season, cycle) at a time. If a coach already saved that same
   season/cycle under the real id, that group is skipped, left where it was, and
   a warning is logged. That case needs a human to decide which version to keep.
4. Tests: `tests/test_lmu_roster.py` (Bluff move, dry run, collision keeps both),
   `tests/test_pipeline.py` (reconcile runs on every real pipeline run).

## If it ever looks like a player "lost" data again

```
flask --app "app:create_app" roster-reconcile --season 2026/2027 --dry-run   # preview, changes nothing
flask --app "app:create_app" roster-reconcile --season 2026/2027             # do it
```

Run the dry run first. Re-running the real command is safe because it's
idempotent: once everything is moved it reports 0. If the log shows
`already has rows for real id ... left placeholder ...`, both versions are in the
database. Look at both before touching anything.

**When adding a new table that stores anything per player/pitcher id, add it to
the reconcile** (`_RECONCILE_TABLES` or `_splash_tables()` in
`app/data/lmu_roster.py`) or this will happen again for that table.

## 2026-10-16 restore

`flask roster-reconcile --season 2026/2027` moved 686 placeholder rows to the
pitchers' real ids with no collisions. A follow-up dry run reports 0 left.
