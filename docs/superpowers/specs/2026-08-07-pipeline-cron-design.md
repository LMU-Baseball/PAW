# Goal 3 — Daily pipeline loader + cron (verifiable core) design

**Date:** 2026-08-07
**Status:** Design approved (brainstorm). Builds the testable core of the daily "load new games → rebuild precalc" pipeline. Live SFTP validation + cron scheduling are deferred (offseason; need live data + supervision).

## Goal

Make the app self-updating for the season: a daily job pulls newly-uploaded LMU games from the Trackman SFTP into `GAMES`, then rebuilds the precalc rollups — and invalidates the web layer's in-process cache across processes so users see fresh data.

## Context

`app/ingest/games.py` already parses the 167-col Trackman v3 game CSV → GAMES names, dedups on `PitchUID`, inserts (insert-only, dry-run-capable). What's missing is the *hardening* the migration spec flagged: the `/v3` tree is a ~50k-file multi-team "swamp", `folder = upload date` (not game date), the SFTP has no keepalive (long walks drop), and the loader is not LMU-filtered.

**Key insight:** `folder = upload date` is a blocker only for a one-time historical backfill. For a **daily incremental cron**, recent uploads live in recent `/v3/YYYY/MM/DD` folders, so pruning the walk to the last N upload-days is both correct and turns the 50k-file walk into a few days'.

**Hard constraint:** it is the **offseason — no new games upload until Fall 2026** — so the end-to-end pipeline cannot be live-tested now, and a live SFTP run needs Trackman creds + supervision. This spec therefore builds only the parts verifiable now (pure logic + orchestration + cache invalidation, with mocked SFTP and dry-run-first); live-walk validation and scheduling are documented deferrals.

## Design

### 1. LMU-aware, upload-folder-pruned file selection (`app/ingest/games.py`)

- `_dir_within_window(dirpath, cutoff_date) -> bool` — **pure.** Parses a `/v3/YYYY[/MM[/DD]]` path; returns True if the (partial) date is >= cutoff at its granularity (so `/v3/2026` and `/v3/2026/09` stay open until the DD level decides). Non-date dirs under `/v3` (e.g. the `CSV` leaf) are always allowed so the walk still reaches the files. Unit-tested with explicit dates.
- `iter_game_files(sftp, root="/v3", since_days=None)` — unchanged when `since_days is None` (full walk, back-compat). When set, computes `cutoff = today - since_days` and prunes directory descent via `_dir_within_window` (only descend date-dirs in the window). Keeps the existing `CSV`-parent + `^\d{8}-.*\.csv$` file match.
- `is_lmu_game(df) -> bool` — **pure.** True if `78 in {HomeTeamForeignID, AwayTeamForeignID}` (LMU's foreign id) OR `'LOY_LIO' in {PitcherTeam, BatterTeam}` values. Robust to either marker being present. Unit-tested.
- `load_games(engine, sftp, *, dry_run=True, limit=None, since_days=None, lmu_only=True)` — passes `since_days` to the walk; when `lmu_only`, skips a file whose parsed df fails `is_lmu_game` (counted separately in the result as `skipped_non_lmu`). Dedup/insert path unchanged. `LoadResult` gains `skipped_non_lmu` (default 0, so existing callers/tests are unaffected). Default `lmu_only=True` is safe: the games loader was never run against prod, so no behavior regression.

### 2. SFTP keepalive (`app/ingest/connections.py`)

`open_sftp` calls `transport.set_keepalive(30)` after `transport.connect(...)` — paramiko sends a keepalive packet every 30s, preventing the idle-drop the recon hit on long walks. Unit-tested by mocking `paramiko.Transport` and asserting `set_keepalive(30)` was called.

### 3. `flask pipeline-load` (`app/cli.py`)

One cron entrypoint. Options: `--dry-run/--no-dry-run` (default dry-run), `--since-days N` (default 3). Steps: (a) open SFTP (`trackman_cfg`), run `load_games(engine, sftp, dry_run=…, since_days=…, lmu_only=True)`; (b) if not dry-run and rows were inserted, `precalc.rebuild_all(engine)`; (c) echo a summary (files / inserted / skipped / non-LMU / date span / rebuilt counts). The loader/rebuild are module attributes so the test monkeypatches them and asserts: sequence, dry-run propagation, and that rebuild is skipped on a dry-run or a zero-insert run.

### 4. Cross-process cache invalidation (`app/data/precalc.py` + `app/data/cache.py`)

- `precalc.ensure_tables` also creates `precalc_meta (id INT PRIMARY KEY, version BIGINT, updated_at DATETIME)` (single row, id=1). `_bump_version(engine)` — `INSERT ... ON DUPLICATE KEY UPDATE version = version + 1, updated_at = now`; called inside `_replace_rows` after the write (so every rebuild bumps). `read_data_version(engine=None) -> int` — reads the stamp (0 if absent).
- `cache.configure(version_reader=fn)` stores a callable; `cache.maybe_invalidate(now)` — if `now - _last_check >= _TTL` (60s), calls the reader (1 cheap round-trip), and if the version changed since last seen, `clear_all()` + records it. Each `@cached` wrapper calls `maybe_invalidate(time.monotonic())` before the store lookup. If no reader is configured (e.g. tests, scripts), it's a no-op.
- Wire in `app/__init__.create_app`: `from app.data import cache, precalc; cache.configure(version_reader=precalc.read_data_version)`.
- Effect: a separate-process cron rebuild bumps the version; each web worker notices within ≤60s (one round-trip/worker/minute) and clears its cache — closing the multi-worker gap documented in Phase 5. In-process rebuilds still `clear_all()` immediately (unchanged), so this is purely additive.

## Testing

- **Pure:** `_dir_within_window` (in/out of window at Y/M/D granularity; non-date dirs allowed); `is_lmu_game` (foreign-id hit, team-code hit, neither → False).
- **Loader:** `load_games(..., since_days=3, lmu_only=True)` with a mocked SFTP (fake tree + CSV reads) inserts only in-window LMU games, counts `skipped_non_lmu`; `since_days=None` preserves today's full-walk behavior.
- **Keepalive:** mocked `paramiko.Transport` → `set_keepalive(30)` called.
- **pipeline-load:** monkeypatched `load_games`/`rebuild_all` → dry-run skips rebuild; `--no-dry-run` with inserts runs rebuild; zero-insert skips rebuild.
- **Cache invalidation:** `maybe_invalidate` with a fake reader + fake clock → clears on version change, respects the 60s TTL (no reader call within TTL), no-op when unconfigured; a decorated fn re-queries after a simulated version bump.
- Full suite stays green; return shapes unchanged.

## Out of scope (documented deferrals)

Live SFTP walk validation against the real `/v3` tree; the actual OS/agent cron schedule (a one-liner calling `flask pipeline-load --no-dry-run` daily — documented, wired when Fall-2026 data exists and can be supervised); any historical FileZilla backfill (the warehouse already backfilled history in Phase 1).

## Success criteria

`pipeline-load --dry-run` runs the LMU-aware, window-pruned selection and reports what it *would* load + rebuild, writing nothing; keepalive is set; the version-stamp invalidation clears caches on a version bump within the TTL; all new logic unit-tested; full suite green. The pipeline is cron-ready pending a supervised live run in Fall 2026.
