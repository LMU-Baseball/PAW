# Phase 4 — Precalc (hitting rollups) design

**Date:** 2026-08-07
**Status:** Design approved (brainstorm). First buildable slice of Phase 4 (the precalc layer). Season-grain hitting rollup only; pitching/catching + the player×date grain + pre-shaped pitch rows are later slices.

## Goal

Kill the profiled hitting-sidebar hotspot. Today `hitting_caps.sidebar_stats(batter_id)` loads the batter's **entire rolling-season pitch set** (`season_pitches`, ~all pitches over a 12-month window) and computes four scalars (QAB%, BA, OBP, SLG) in pandas — the measured ~3.2s cost is that full-season load + transform, run on every selection. Replace it with a **1-row read** from a precomputed rollup, rebuilt on demand.

This is the first slice of the precalc layer: the site reads off precalc; only the rebuild job reads raw CAPS.

## Background (profiling, 2026-08-06)

Every RDS query costs ~500–900ms regardless of row count (us-east-2 round-trip). The sidebar's cost is the big `season_pitches` pull + the pandas `qab_frame`/`_slash_from_pas` transform. Precalc's win here is turning that into one indexed 1-row `SELECT`. (Chart *render* cost — the ~2.6s Plotly build — is a separate Phase 5 concern, not addressed here.)

## Scope

**In:** a season-grain hitting rollup table, a `flask rebuild-precalc` command that (re)builds it from the existing CAPS compute path, and repointing the hitting sidebar/summary reads to it (with a compute fallback).

**Out (later slices):** the player×date grain; pre-shaped one-row-per-pitch tables; pitching and catching rollups; incremental rebuild + the daily cron; any chart-render/caching work (Phase 5).

## Design

### 1. Table: `precalc_hitting_player_season`

One row per LMU hitter, over the **same rolling recent-season window** `sidebar_stats` uses today (`_RECENT_WINDOW_CLAUSE`, anchored to `MAX(GAMES.Date)`; numeric-GameID-guarded — identical scope to `season_pitches`, so the same hitters that appear in `lmu_hitters()` appear here).

| column | type | source |
|---|---|---|
| `batter_id` | BIGINT **PRIMARY KEY** | raw `GAMES.BatterId` (canonical id, per `lmu_hitters`) |
| `batter_name` | VARCHAR | `GAMES.Batter` |
| `qab_pct` | DECIMAL(4,3) NULL | `qab_frame(df).QAB.sum()/total` (NULL when no PAs) |
| `ba`, `obp`, `slg` | VARCHAR(8) | exact display strings from `_slash_from_pas` (`"—"` when undefined) — the sidebar's contract, stored verbatim so the reader is a pass-through |
| `pa`, `ab`, `h`, `doubles`, `triples`, `hr`, `bb`, `so` | INT | the counting components behind the slash line (from the same PA frame) |
| `season_label` | VARCHAR(32) | label for the window (e.g. the max-date season); one window today, column present so a future multi-season rebuild is additive |
| `built_at` | DATETIME | rebuild timestamp |

Created idempotently by the rebuild command (`CREATE TABLE IF NOT EXISTS`); lives in the analytics RDS alongside `GAMES`. Row count is tiny (~25 hitters).

### 2. Compute path = single source of truth

The rebuild computes each row through the **existing** CAPS functions — `season_pitches(batter_id)` → `qab_frame` → `_slash_from_pas` — plus the counting components extracted from the same PA frame. No metric is redefined; the rollup is a memo of what the app already computes. This guarantees precalc == on-the-fly compute (the parity test).

To share cleanly, extract the current bodies into `_compute_season_rollup(batter_id) -> dict` in `hitting_caps.py` (returns all the columns above except `built_at`). `sidebar_stats`/`season_qab_rate`/`slash_line` become thin wrappers over the reader (below), and the rebuild calls `_compute_season_rollup`.

### 3. Rebuild command: `flask rebuild-precalc [--module hitting]`

- Full rebuild: `CREATE TABLE IF NOT EXISTS`; for every id in `lmu_hitters()`, compute `_compute_season_rollup`; then in ONE transaction `DELETE FROM precalc_hitting_player_season` followed by a `common.chunked_insert` of all fresh rows. Idempotent — re-running yields the same row set.
- Full (not incremental) because data is static in the offseason and volumes are trivial; incremental + cron is deferred.
- `--module` defaults to `hitting` (the only module this slice builds); the flag exists so pitching/catching slot in later.
- Reuses `common.chunked_insert` (same loader plumbing as the ingest work).

### 4. Read path

`app/data/hitting_caps.py`:
- New `_read_season_rollup(batter_id) -> dict | None` — one indexed `SELECT * ... WHERE batter_id = :b`. Returns the row as a dict, or `None` if absent.
- `sidebar_stats(batter_id)` → read the rollup row; return `{"qab": qab_pct, "BA": ba, "SLG": slg, "OBP": obp}`. **If the row is missing** (player not yet built, or table absent), fall back to `_compute_season_rollup` on the fly — so correctness never depends on a rebuild having run.
- `season_qab_rate` / `slash_line` similarly read the rollup (they're subsets of the same row), same fallback.
- Return shapes are **unchanged** — dashboards/selectors keep calling `sidebar_stats` etc. exactly as today.

### 5. Testing

- **Parity:** for a sample hitter, `_read_season_rollup` (after a rebuild) == `_compute_season_rollup` field-for-field; and `sidebar_stats` output is byte-identical to the pre-precalc compute for that hitter.
- **Fallback:** with no rollup row (or table dropped), `sidebar_stats` still returns the correct computed dict.
- **Rebuild idempotency:** running `rebuild-precalc` twice yields identical row set (same count, same values).
- **Coverage:** after a rebuild, every id in `lmu_hitters()` has exactly one rollup row.

## Risks / notes

- **Window drift:** the rollup snapshots the recent-season window at rebuild time; if new games land, a rebuild is required to refresh — acceptable (offseason: no new games; the cron will rebuild after each load later).
- **Fallback keeps it safe:** because the reader falls back to compute, shipping the table empty (before the first rebuild) degrades to today's behavior rather than breaking.
- **No new redundancy of the kind Phase 3 removed:** precalc is a *derived* cache of CAPS, explicitly rebuilt from it — not a second source of truth.

## Success criteria

`flask rebuild-precalc` populates `precalc_hitting_player_season`; the hitting sidebar reads one row instead of loading the full season; parity + fallback + idempotency tests green; full suite green; live sidebar visibly faster.
