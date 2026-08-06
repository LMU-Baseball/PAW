# Data Ingestion Loaders — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to
> implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refill `BULLPEN`, `GAMES`, and the HitTrax `practice_*` tables from the Trackman SFTP and
HitTrax FTPS feeds with re-runnable, idempotent, dry-run-capable loaders.

**Architecture:** New `app/ingest/` package: a config + connection layer (paramiko SFTP, stdlib
FTPS), pure per-feed parser/mapper functions (unit-tested against sample fixtures), loader functions
that walk the remote tree, dedup against existing keys, and insert in chunks, plus Flask CLI
commands. Prod writes are performed by the human orchestrator after a dry-run; tests never write to
the live analytics DB.

**Tech Stack:** Python, pandas, SQLAlchemy (existing `app.db`), paramiko (SFTP), `ftplib.FTP_TLS`
(FTPS), pytest.

## Global Constraints

- Insert-only; never DELETE/DROP except the HitTrax transform's transactional truncate-and-rebuild
  of the 3 derived tables from the immutable `raw_practice_csv`.
- Every loader supports `dry_run=True` → computes and reports counts, writes nothing.
- Idempotent: `BULLPEN` dedup on `PlayID` (fallback composite for NULL PlayID); `GAMES` dedup on
  `PitchUID`; HitTrax raw `INSERT IGNORE` on `raw_practice_csv.row_hash`.
- Creds come only from env (`TM_SFTP_*`, `HT_FTPS_*`), read via existing config/dotenv. Never print
  secret values.
- Unit conversions (HitTrax): `mps_to_mph(x)=round(x*2.23694,2)`, `meters_to_feet(x)=round(x*3.28084,2)`;
  missing/blank → `None` (NULL), never 0.
- Follow `docs/reference/hittrax-practice-analytics/{pipeline-architecture.md,transformed_schema.sql}`
  for the HitTrax mapping verbatim.
- Test fixtures live in `tests/fixtures/ingest/` (already created): `bullpen_sample.csv` (18r×68c),
  `game_sample.csv` (30r×167c), `hittrax_plays_sample.csv` (30r×88c), `hittrax_session_sample.csv`
  (30r×93c).
- Live DB facts: `BULLPEN` 79 cols, ends 2025-04-14, PlayID varchar. `GAMES` 175 cols, has
  `PitchUID`/`GameUID`/`GameID`/`PitchNo`/`Top.Bottom`, dates stored `M/D/YY` text. `raw_practice_csv`
  = (id, source_file, ingested_at_utc, row_hash char, payload json). `practice_sessions`/
  `practice_plays`/`player_stats_summary` per `transformed_schema.sql`.

---

### Task 1: Foundation — deps, config, connections, common helpers

**Files:**
- Modify: `requirements.txt` (add `paramiko>=3`)
- Modify: `.env.example` (add TM_SFTP_* + HT_FTPS_* placeholder block)
- Create: `app/ingest/__init__.py`
- Create: `app/ingest/config.py`
- Create: `app/ingest/connections.py`
- Create: `app/ingest/common.py`
- Test: `tests/test_ingest_common.py`

**Interfaces produced:**
- `config.trackman_cfg()->dict` keys `host,port,user,password` (from `TM_SFTP_*`); `config.hittrax_cfg()`
  keys `host,port,user,password,remote_dir` (from `HT_FTPS_*`). Missing var → `RuntimeError("TM_SFTP_HOST not set")`.
- `connections.open_sftp(cfg)` ctx mgr → paramiko `SFTPClient`; `connections.open_ftps(cfg)` ctx mgr → `FTP_TLS`.
- `common.LoadResult` dataclass: `inserted:int, skipped:int, files:int, date_min:str|None, date_max:str|None, dry_run:bool`.
- `common.mps_to_mph(x)->float|None`, `common.meters_to_feet(x)->float|None`, `common.safe_numeric(x)->float|None`.
- `common.existing_keys(engine, table, col)->set[str]` (SELECT DISTINCT col; str-cast, drop None).
- `common.chunked_insert(engine, table, rows:list[dict], chunksize=500)->int` (parameterized INSERT,
  returns count; caller pre-filters dedup).

- [ ] Write `tests/test_ingest_common.py`: `mps_to_mph(28.61)==64.01`, `meters_to_feet(1)==3.28`,
  `mps_to_mph(None) is None`, `safe_numeric('')` is None, `safe_numeric('12.5')==12.5`,
  `LoadResult` fields default. Config: monkeypatch env, assert `trackman_cfg()['host']` and that a
  missing var raises `RuntimeError` naming the var.
- [ ] Run tests → fail.
- [ ] Implement `config.py` (read `os.getenv`, `load_dotenv()` first via existing pattern in
  `config.py`), `common.py` (dataclass + helpers; `existing_keys`/`chunked_insert` use `app.db`
  engine / `sqlalchemy.text`), `connections.py` (paramiko `Transport`+`from_transport`; `FTP_TLS`
  `.connect/.login/.prot_p`; both `@contextmanager` with try/finally close, 30s timeouts).
- [ ] Run tests → pass. Add `paramiko>=3` to requirements, install it, add `.env.example` block.
- [ ] Commit: `feat(ingest): config + SFTP/FTPS connections + common helpers`.

---

### Task 2: BULLPEN parser (pure)

**Files:**
- Create: `app/ingest/bullpen.py` (parser portion)
- Test: `tests/test_ingest_bullpen.py`

**Interfaces produced:**
- `bullpen.BULLPEN_COLS: list[str]` — the 68 CSV columns that map to BULLPEN (names identical).
- `bullpen.parse_bullpen_csv(df: pd.DataFrame, *, source_file:str)->pd.DataFrame` — returns rows with
  exactly the BULLPEN-mapped columns (drop CSV cols not in BULLPEN; the 11 derived BULLPEN cols are
  simply absent → NULL on insert). Adds nothing extra. Filters nothing (file-level `Pitching_`
  filter happens in the loader).
- `bullpen.dedup_key(row: dict)->str` — `str(row['PlayID'])` if truthy else
  `f"{PitcherId}|{Date}|{Time}|{PitchNo}"` composite.

**Interfaces consumed:** none.

- [ ] Write `tests/test_ingest_bullpen.py`: load `tests/fixtures/ingest/bullpen_sample.csv` with
  pandas; `parse_bullpen_csv` returns 18 rows; every returned column is in the known BULLPEN column
  set (hard-code the 79-name set in the test or a subset incl `PitcherId,TaggedPitchType,RelSpeed,
  SpinRate,PlayID,PracticeType`); `PlayID`-based `dedup_key` for a row equals that row's PlayID;
  a synthesized row with empty PlayID yields the composite key.
- [ ] Run → fail.
- [ ] Implement. `BULLPEN_COLS` = the 68 header names of the sample (read once, hard-code the list).
  `parse_bullpen_csv` selects `[c for c in BULLPEN_COLS if c in df.columns]`, returns copy.
- [ ] Run → pass.
- [ ] Commit: `feat(ingest): BULLPEN CSV parser + dedup key`.

---

### Task 3: BULLPEN loader + CLI

**Files:**
- Modify: `app/ingest/bullpen.py` (add loader)
- Modify: `app/cli.py` (register `flask ingest` group + `bullpen` command)
- Create: `app/ingest/cli.py` (the click group)
- Test: `tests/test_ingest_bullpen_loader.py`

**Interfaces produced:**
- `bullpen.iter_practice_pitching_files(sftp, root='/practice')->list[str]` — recursive walk,
  return paths whose basename startswith `Pitching_` and endswith `.csv`.
- `bullpen.load_bullpen(engine, sftp, *, dry_run=True, limit=None)->LoadResult` — walk, read each CSV
  with pandas, `parse_bullpen_csv`, compute dedup keys, drop rows whose key ∈ existing PlayIDs (from
  `existing_keys(engine,'BULLPEN','PlayID')`) or seen-this-run, insert the rest via `chunked_insert`
  (unless dry_run). `date_min/date_max` from the `Date` column of inserted rows.

**Interfaces consumed:** Task 1 (`open_sftp`, `existing_keys`, `chunked_insert`, `LoadResult`),
Task 2 (`parse_bullpen_csv`, `dedup_key`, `iter_practice_pitching_files`).

- [ ] Write `tests/test_ingest_bullpen_loader.py`: build a **fake sftp** object (listdir_attr
  returns one dir `2026`→`05`→`14` then the sample file; `open`/`file` returns the fixture bytes) OR
  monkeypatch `iter_practice_pitching_files` to return `['bullpen_sample.csv']` and a reader to load
  the fixture; use a **fake engine** where `existing_keys` returns `set()` and `chunked_insert`
  records rows. Assert: dry_run → `chunked_insert` NOT called, `LoadResult.inserted==18`,
  `date_max=='2026-05-14'`(or the fixture's Date); a second call with existing keys = all 18 PlayIDs
  → `inserted==0, skipped==18`.
- [ ] Run → fail.
- [ ] Implement loader + `app/ingest/cli.py` click group with `bullpen --dry-run/--no-dry-run
  --limit`, wire into `app/cli.py` (`app.cli.add_command(ingest_cli)` inside `register_cli`/create_app
  as existing CLI is registered). Command opens engine (`app.db`) + `open_sftp(trackman_cfg())`,
  calls `load_bullpen`, prints the `LoadResult`.
- [ ] Run → pass.
- [ ] Commit: `feat(ingest): BULLPEN loader (SFTP /practice) + flask ingest bullpen CLI`.

---

### Task 4: GAMES parser (pure)

**Files:**
- Create: `app/ingest/games.py` (parser portion)
- Test: `tests/test_ingest_games.py`

**Interfaces produced:**
- `games.CSV_TO_GAMES: dict[str,str]` — maps CSV col → GAMES col where names differ (notably
  `'Top/Bottom' -> 'Top.Bottom'`); identity for the rest.
- `games.GAMES_COLS: list[str]` — the GAMES columns the loader targets (intersection of mapped CSV
  cols and the 175 table cols; hard-code the reconciled list).
- `games.parse_game_csv(df, *, source_file)->pd.DataFrame` — rename via `CSV_TO_GAMES`, select cols
  present in `GAMES_COLS`, return copy. `PitchUID` preserved for dedup.

**Interfaces consumed:** none.

- [ ] Write `tests/test_ingest_games.py`: load `game_sample.csv`; `parse_game_csv` returns 30 rows;
  output has column `Top.Bottom` and NOT `Top/Bottom`; `PitchUID`, `GameID`, `PitchNo`,
  `TaggedPitchType`, `AutoPitchType` all present; no output column is absent from a hard-coded GAMES
  175-name set (the test embeds the set — get it from the spec's note / an INFORMATION_SCHEMA dump
  the implementer captures once and pastes).
- [ ] Run → fail.
- [ ] Implement. (Implementer: run a one-off `INFORMATION_SCHEMA.COLUMNS` query for GAMES to get the
  exact 175 names, build `CSV_TO_GAMES` by matching CSV headers to GAMES names case-insensitively,
  special-casing `Top/Bottom`→`Top.Bottom`; hard-code the resulting maps as literals.)
- [ ] Run → pass.
- [ ] Commit: `feat(ingest): GAMES CSV parser + column map`.

---

### Task 5: GAMES loader + CLI

**Files:**
- Modify: `app/ingest/games.py` (loader)
- Modify: `app/ingest/cli.py` (add `games` command)
- Test: `tests/test_ingest_games_loader.py`

**Interfaces produced:**
- `games.iter_game_files(sftp, root='/v3')->list[str]` — recursive walk, return `.csv` paths under
  any `.../CSV/` leaf (basename matches `\d{8}-.*\.csv`).
- `games.load_games(engine, sftp, *, dry_run=True, limit=None)->LoadResult` — walk, read, parse,
  dedup on `PitchUID` vs `existing_keys(engine,'GAMES','PitchUID')` + seen-this-run, insert rest.

**Interfaces consumed:** Task 1 + Task 4.

- [ ] Write `tests/test_ingest_games_loader.py`: fake sftp/reader returning `game_sample.csv`; fake
  engine (`existing_keys`→∅, capture inserts). dry_run → no insert, `inserted==30`; re-run with all
  30 PitchUIDs existing → `inserted==0, skipped==30`.
- [ ] Run → fail.
- [ ] Implement loader + `games` CLI command (mirrors bullpen).
- [ ] Run → pass.
- [ ] Commit: `feat(ingest): GAMES loader (SFTP /v3) + flask ingest games CLI`.

---

### Task 6: HitTrax raw ELT (FTPS → raw_practice_csv)

**Files:**
- Create: `app/ingest/hittrax.py` (raw portion)
- Modify: `app/ingest/cli.py` (add `hittrax-raw` command)
- Test: `tests/test_ingest_hittrax_raw.py`

**Interfaces produced:**
- `hittrax.row_hash(payload: dict)->str` — `sha256(json.dumps(payload, sort_keys=True, default=str)).hexdigest()`.
- `hittrax.csv_to_raw_rows(df, *, source_file)->list[dict]` — each → `{source_file, row_hash,
  payload(json str)}`.
- `hittrax.extract_load_raw(engine, ftps, *, dry_run=True, limit=None)->LoadResult` — list root
  `*.CSV`, skip <10-byte files, read each, build raw rows, `INSERT IGNORE` into `raw_practice_csv`
  (returns inserted vs ignored counts). `ingested_at_utc` passed in (caller supplies a timestamp;
  do not call Date.now inside pure fns).

**Interfaces consumed:** Task 1.

- [ ] Write `tests/test_ingest_hittrax_raw.py`: `row_hash` deterministic + differs by payload;
  `csv_to_raw_rows` on `hittrax_plays_sample.csv` → 30 rows each with a 64-char hash + valid JSON
  payload; `extract_load_raw` with fake ftps (nlst→[plays fixture], retrbinary feeds bytes) + fake
  engine → dry_run writes nothing, `inserted==30`; re-run with those hashes present → `inserted==0`.
- [ ] Run → fail.
- [ ] Implement (use `INSERT IGNORE INTO raw_practice_csv (...) VALUES (...)` via `text()`; JSON via
  `CAST(:payload AS JSON)`).
- [ ] Run → pass.
- [ ] Commit: `feat(ingest): HitTrax raw ELT (FTPS -> raw_practice_csv) + CLI`.

---

### Task 7: HitTrax transform (raw → practice_sessions/plays/summary) + CLI

**Files:**
- Modify: `app/ingest/hittrax.py` (transform portion)
- Modify: `app/ingest/cli.py` (add `hittrax-transform` + `hittrax` [raw+transform] commands)
- Test: `tests/test_ingest_hittrax_transform.py`

**Interfaces produced:**
- `hittrax.transform_sessions(raw_df)->pd.DataFrame` — SessionExport payloads → `practice_sessions`
  columns, mapping + unit conversions per `transformed_schema.sql`.
- `hittrax.transform_plays(raw_df, sessions_with_ids)->pd.DataFrame` — PlaysExport payloads →
  `practice_plays` columns; `session_id` via merge on `(session_date, player_id)`.
- `hittrax.transform(engine, *, dry_run=True)->dict` — read raw, build sessions+plays, and inside a
  transaction (`SET FOREIGN_KEY_CHECKS=0`; truncate the 3 tables; load sessions; reload sessions to
  get ids; load plays; aggregate `player_stats_summary` via the reference `INSERT ... ON DUPLICATE
  KEY UPDATE`; re-enable FK). dry_run → compute + return row counts, no writes. Returns
  `{sessions, plays, players}` counts.

**Interfaces consumed:** Task 1 (`mps_to_mph`, `meters_to_feet`, `safe_numeric`), Task 6 (raw table).

- [ ] Write `tests/test_ingest_hittrax_transform.py`: build a raw_df in memory from
  `hittrax_session_sample.csv` + `hittrax_plays_sample.csv` (payload=json per row, source_file names
  matching `SessionExport`/`PlaysExport`). Assert `transform_sessions` maps `AEV`→`avg_exit_velocity`
  with mps→mph conversion (spot-check one numeric row), `Type`→`session_type`, unique-key cols
  present; `transform_plays` maps `Velo`→`exit_velocity` (mph), `Dist`→`distance_feet` (ft),
  `Id`→`play_id`, and merges a `session_id` when the (date,player) matches. No DB writes in the pure
  fns.
- [ ] Run → fail.
- [ ] Implement per `transformed_schema.sql` (every clean col's source code is in its comment) +
  `pipeline-architecture.md` §2. Session date from `St`/timestamp; player_id from the payload's
  player id field. `transform()` orchestrates the transactional rebuild.
- [ ] Run → pass.
- [ ] Commit: `feat(ingest): HitTrax transform + full flask ingest hittrax CLI`.

---

## Self-review notes
- Spec coverage: BULLPEN (T2–3), GAMES (T4–5), HitTrax raw+transform (T6–7), shared infra/config/
  CLI/safety (T1, folded into each). Dry-run + idempotency asserted in every loader test.
- Prod loads are NOT a task — the orchestrator runs `flask ingest <feed> --dry-run`, verifies, then
  `--no-dry-run`, per the spec safety model.
- Fixtures already exist; tests read them, never the network or live DB.
