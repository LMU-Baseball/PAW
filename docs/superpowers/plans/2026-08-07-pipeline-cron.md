# Goal 3 — Pipeline loader + cache invalidation (verifiable core) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (inline, full-suite gate at end). Checkbox steps.

**Goal:** Build the testable core of the daily "load new LMU games → rebuild precalc → invalidate caches" pipeline: LMU-aware/upload-folder-pruned SFTP selection, SFTP keepalive, `flask pipeline-load`, and cross-process cache invalidation. Live SFTP validation + cron scheduling deferred.

**Tech Stack:** Python, paramiko, pandas, click, pytest (mocked SFTP; no live network).

## Global Constraints

- Dry-run-first; loader stays insert-only. No live SFTP in tests.
- Back-compat: `iter_game_files(since_days=None)` and `load_games(lmu_only=…, since_days=…)` default to today's behavior for existing callers; `LoadResult.skipped_non_lmu` defaults 0.
- Cache invalidation is additive: in-process `clear_all()` on rebuild stays; the version gate is a no-op when no reader is configured.
- Full suite green (621 as of `4a0fdea`).

---

### Task 1: `games.py` — pure selection helpers + loader flags

**Files:** `app/ingest/common.py` (`LoadResult`), `app/ingest/games.py`; Test `tests/test_ingest_games.py` (extend or create).

- [ ] **Step 1 — failing tests:**

```python
import datetime as dt
from app.ingest import games

def test_dir_within_window_year_month_day():
    cut = dt.date(2026, 9, 10)
    assert games._dir_within_window("/v3/2026", cut) is True        # year open
    assert games._dir_within_window("/v3/2026/09", cut) is True     # month open
    assert games._dir_within_window("/v3/2026/09/15", cut) is True  # after cutoff
    assert games._dir_within_window("/v3/2026/09/05", cut) is False # before cutoff
    assert games._dir_within_window("/v3/2025", cut) is False       # old year
    assert games._dir_within_window("/v3/2026/09/15/CSV", cut) is True  # non-date leaf allowed

def test_is_lmu_game_by_foreign_id_or_team_code():
    import pandas as pd
    assert games.is_lmu_game(pd.DataFrame({"HomeTeamForeignID": [78], "AwayTeamForeignID": [12]}))
    assert games.is_lmu_game(pd.DataFrame({"AwayTeamForeignID": [78]}))
    assert games.is_lmu_game(pd.DataFrame({"PitcherTeam": ["LOY_LIO"], "BatterTeam": ["X"]}))
    assert not games.is_lmu_game(pd.DataFrame({"HomeTeamForeignID": [12], "AwayTeamForeignID": [34]}))
    assert not games.is_lmu_game(pd.DataFrame({"PitcherTeam": ["SAN_TOR"]}))
```

- [ ] **Step 2:** Run → FAIL. **Step 3 — implement:**
  - `common.LoadResult`: add `skipped_non_lmu: int = 0` (last field, defaulted).
  - `games._dir_within_window(dirpath, cutoff)`: split path after `/v3`; take the numeric leading components (year[/month[/day]]); build the *latest* date that prefix could represent at its granularity (year→Dec 31, year/month→month end, full→that day) and return `latest >= cutoff`; a component that isn't numeric (e.g. `CSV`) or a path with no date components → return True (don't prune non-date dirs).
  - `games.is_lmu_game(df)`: `78` in the set of `HomeTeamForeignID`/`AwayTeamForeignID` values (coerce, ignore NaN) OR `'LOY_LIO'` in `PitcherTeam`/`BatterTeam` values. Missing columns are treated as no-match.
  - `iter_game_files(sftp, root="/v3", since_days=None)`: if `since_days` set, `cutoff = _today() - timedelta(days=since_days)` and only push a subdir when `_dir_within_window(path, cutoff)` (files still matched by the existing regex + `CSV` parent). `_today()` is a tiny seam (`return dt.date.today()`) so tests can monkeypatch it.
  - `load_games(..., since_days=None, lmu_only=True)`: pass `since_days` to `iter_game_files`; for each parsed df, if `lmu_only and not is_lmu_game(parsed)`: `skipped_non_lmu += 1; continue`. Thread `skipped_non_lmu` into the returned `LoadResult`.
- [ ] **Step 4:** Run → PASS + existing `tests/test_ingest_games.py` green. **Step 5:** Commit `feat(pipeline): LMU-aware + upload-folder-pruned game selection`.

- [ ] **Step 6 — loader integration test** (mocked SFTP): a fake `sftp` with `listdir_attr` returning a small tree (one in-window LMU game, one in-window non-LMU game, one out-of-window) + `_read_csv_from_sftp` monkeypatched per path; assert `load_games(engine, sftp, dry_run=True, since_days=3, lmu_only=True)` reports `files`/`inserted`/`skipped_non_lmu` correctly and `since_days=None` still finds all. Commit with Step 5 or separately.

### Task 2: SFTP keepalive (`app/ingest/connections.py`)

**Files:** `app/ingest/connections.py`; Test `tests/test_connections.py` (create).

- [ ] **Step 1 — failing test:** monkeypatch `paramiko.Transport` with a mock (and `socket.create_connection`); enter `open_sftp(cfg)`; assert the transport's `set_keepalive` was called with `30`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** In `open_sftp`, after `transport.connect(...)`, add `transport.set_keepalive(30)`. **Step 4:** Run → PASS. **Step 5:** Commit `feat(pipeline): SFTP keepalive so long walks don't drop`.

### Task 3: precalc version stamp (`app/data/precalc.py`)

**Files:** `app/data/precalc.py`; Test `tests/test_precalc.py`.

- [ ] **Step 1 — failing test:** `precalc.ensure_tables(get_engine())`; capture `v0 = precalc.read_data_version()`; `precalc._bump_version(get_engine())`; assert `precalc.read_data_version() == v0 + 1`.
- [ ] **Step 2:** Run → FAIL. **Step 3:**
  - Add `PRECALC_META_TABLE = "precalc_meta"` + DDL `(id INT PRIMARY KEY, version BIGINT, updated_at DATETIME)` to `_DDL`.
  - `_bump_version(engine)`: `INSERT INTO precalc_meta (id, version, updated_at) VALUES (1, 1, :now) ON DUPLICATE KEY UPDATE version = version + 1, updated_at = :now`.
  - `read_data_version(engine=None) -> int`: `SELECT version FROM precalc_meta WHERE id=1`; return `int` or `0` if absent/table missing (try/except).
  - Call `_bump_version(engine)` inside `_replace_rows` right after the `cache.clear_all()` (every rebuild bumps).
- [ ] **Step 4:** Run → PASS. **Step 5:** Commit `feat(pipeline): precalc data-version stamp (bumped each rebuild)`.

### Task 4: cache version gate (`app/data/cache.py`) + wiring

**Files:** `app/data/cache.py`, `app/__init__.py`; Test `tests/test_cache.py`.

- [ ] **Step 1 — failing tests:**

```python
def test_maybe_invalidate_clears_on_version_change_and_respects_ttl():
    from app.data import cache
    cache.clear_all()
    versions = [1, 1, 2]
    reader = lambda: versions.pop(0)
    cleared = []
    orig = cache.clear_all
    # count clears
    import app.data.cache as C
    calls = {"n": 0}
    def spy():
        calls["n"] += 1
    C._STORES  # ensure module loaded
    cache.configure(version_reader=reader, ttl=10.0)
    cache.maybe_invalidate(now=100.0)   # first read: version 1, sets baseline (no clear)
    cache.maybe_invalidate(now=105.0)   # within ttl: reader NOT called (still 1 left in list)
    cache.maybe_invalidate(now=120.0)   # ttl elapsed: reader -> 2 -> clears
    assert versions == []               # reader called exactly twice (100.0, 120.0)
    cache.configure(version_reader=None)  # reset for other tests

def test_maybe_invalidate_noop_without_reader():
    from app.data import cache
    cache.configure(version_reader=None)
    cache.maybe_invalidate(now=0.0)     # must not raise
```

(Adjust the clear-count assertion to the final API; the key behaviors: reader gated by ttl; `clear_all` on version change; no-op without a reader.)

- [ ] **Step 2:** Run → FAIL. **Step 3 — implement in `cache.py`:**
  - Module state: `_version_reader=None`, `_ttl=60.0`, `_seen_version=None`, `_last_check=None`.
  - `configure(version_reader=None, ttl=60.0)`: set the reader + ttl; reset `_seen_version=None`, `_last_check=None`.
  - `maybe_invalidate(now=None)`: if no reader → return. `now = now if now is not None else time.monotonic()`. If `_last_check is not None and now - _last_check < _ttl` → return. Set `_last_check = now`; `v = _version_reader()`; if `_seen_version is not None and v != _seen_version`: `clear_all()`. Set `_seen_version = v`.
  - In `cached`'s wrapper, call `maybe_invalidate()` before the store lookup.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5 — wire** in `app/__init__.create_app` (after blueprints, near the other `app.data` imports): `from app.data import cache, precalc; cache.configure(version_reader=precalc.read_data_version)`. **Step 6:** Run `tests/test_cache.py tests/test_cache_integration.py` → green. **Step 7:** Commit `feat(pipeline): cross-process cache invalidation via precalc version gate`.

### Task 5: `flask pipeline-load` (`app/cli.py`)

**Files:** `app/cli.py`; Test `tests/test_pipeline_cli.py` (create) — or a direct-function test.

- [ ] **Step 1 — failing test:** monkeypatch a `_run_pipeline(dry_run, since_days)` helper's collaborators (`load_games`, `precalc.rebuild_all`, `open_sftp`) and assert: dry-run → rebuild NOT called; `--no-dry-run` with `inserted>0` → rebuild called; `inserted==0` → rebuild skipped. (Factor the body into a testable `_run_pipeline` returning a summary dict; the click command is a thin wrapper.)
- [ ] **Step 2:** Run → FAIL. **Step 3 — implement:** add `_run_pipeline(engine, *, dry_run, since_days)` in `app/cli.py` (or a small `app/ingest/pipeline.py`): open SFTP via `trackman_cfg`, `res = load_games(engine, sftp, dry_run=dry_run, since_days=since_days, lmu_only=True)`; if `not dry_run and res.inserted > 0`: `rebuilt = precalc.rebuild_all(engine)` else `rebuilt = None`; return a summary. Register `@server.cli.command("pipeline-load")` with `--dry-run/--no-dry-run` (default dry-run) + `--since-days` (default 3) that calls it and echoes the summary.
- [ ] **Step 4:** Run → PASS. **Step 5:** Commit `feat(pipeline): flask pipeline-load (load new LMU games -> rebuild-precalc)`.

### Task 6: document the deferred cron step

- [ ] Add a short "Deploying the daily cron (Fall 2026)" note to the spec or a `docs/` runbook: the one-liner (`flask --app run pipeline-load --no-dry-run --since-days 3` daily), the pre-flight `--dry-run` supervised check, and the required `TM_SFTP_*` env vars. Commit `docs(pipeline): deferred cron scheduling runbook`.

---

## Post-plan verification

- [ ] `pytest -q` green (621 + new tests).
- [ ] `flask --app run pipeline-load --dry-run --since-days 3` — with live creds it reports would-load counts writing nothing; **without creds it fails fast on the missing `TM_SFTP_*` env (expected offseason)** — confirm the failure is the config guard, not a code bug (run the unit tests as the real gate).
- [ ] Live app unaffected: restart dev server, dashboards 200; `rebuild-precalc` still works and now bumps `precalc_meta.version`.

## Self-review notes

- **Spec coverage:** part1=Task1, part2=Task2, part4=Tasks3+4, part3=Task5, deferral=Task6.
- **Placeholders:** the Task-4 test's clear-count assertion carries an "adjust to final API" note; behaviors (ttl gate, clear-on-change, no-op) are explicit.
- **Back-compat:** every new param defaults to prior behavior; `LoadResult.skipped_non_lmu` defaulted; version gate no-ops without a reader (so scripts/CLI that don't call `create_app` are unaffected).
