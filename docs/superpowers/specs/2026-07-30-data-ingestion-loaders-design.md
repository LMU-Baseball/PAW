# Data Ingestion Loaders — Design Spec (2026-07-30)

## Problem

The pipelines that fed PAW's data tables are dead (former analytics director left). Three
tables/table-groups are stale and must be refilled from their upstream file feeds, which the
user has confirmed live on two servers whose credentials are now in `.env`:

- **Trackman SFTP** (`ftp.trackmanbaseball.com:22`, `TM_SFTP_*`) — practice + game CSVs.
- **HitTrax FTPS** (`HT_FTPS_*`, FTP-over-TLS, **not** SSH/SFTP) — daily play/session exports.

Recon (2026-07-30, read-only) confirmed egress from this environment to both servers works
(`paramiko 5.0.0` for SFTP, stdlib `ftplib.FTP_TLS` for FTPS).

### Strategic context
The user intends to populate the **legacy all-caps tables** (`GAMES`, `BULLPEN`, `PLAYERS`) and
likely **delete the `tm_*`/`fact_*`/`dim_*` warehouse** later (a separate future migration of the
app's data layer, out of scope here). These loaders write to the tables that already exist and are
already read by the app (`BULLPEN` → bullpen report; `practice_*` → hitting-practice dashboard).
`GAMES` is populated for the coming migration and for the legacy-table strategy.

## Goals

1. **`BULLPEN`** ← Trackman `/practice/**/Pitching_*_verified.csv` (bullpen reports go current).
2. **`GAMES`** ← Trackman `/v3/**/CSV/*.csv` (full game pitch data; enables all-caps strategy).
3. **HitTrax** ← FTPS `PlaysExport_*` / `SessionExport_*` → `raw_practice_csv` → `practice_sessions`
   / `practice_plays` / `player_stats_summary` (hitting-practice dashboard goes current).
4. Re-runnable, incremental, and **idempotent** — safe to run repeatedly (this is how they'll be
   scheduled later).

## Non-goals

- Scheduling/automation wiring (deploy-time; note the old HitTrax cron was GH Actions Mon–Sat 13:10 UTC).
- Migrating the app's data layer off the warehouse onto the all-caps tables (separate project).
- Any change to dashboards/reports/UI.
- Backfilling `PLAYERS` (no confirmed file feed; deferred).

## Safety model (hard requirements)

- **Insert-only.** Loaders never `DELETE`/`DROP`. (HitTrax transform is the one exception — it
  rebuilds the 3 derived tables from the immutable raw layer; see below — done in a transaction.)
- **Idempotent.** Re-running never duplicates:
  - `BULLPEN`: skip rows whose `PlayID` already exists.
  - `GAMES`: skip rows whose `PitchUID` already exists.
  - HitTrax raw: `INSERT IGNORE` on `raw_practice_csv.row_hash` (SHA-256 of the row).
- **Dry-run mode** on every loader: report "would insert N rows across dates X–Y, skipping M
  already present" and write nothing.
- **Orchestrator runs prod writes**, not subagents. Subagents build code + tests only (tests use
  the downloaded sample CSVs and mocked/again-idempotent paths — never write to prod).
- Read-only probe scripts + downloaded samples live in the scratchpad, not the repo.

## Source → target details (verified live)

### 1. Trackman practice → `BULLPEN`
- Files: SFTP `/practice/YYYY/MM/DD/Pitching_<ISOts>_verified.csv` (**68 cols**). Also likely
  `Hitting_*` practice files in the same tree → **filter to `Pitching_` prefix**.
- `BULLPEN` table = **79 cols**; the CSV's 68 columns map **1:1 by name** to the first 68.
  Derived cols (`AreaNum,InZone,Zone,AreaOfZone,IntendedLoc,Torque,WindupStretch,C1,Stuff,Video,
  Catcher`) are left NULL by a raw load (old loader/manual tags; acceptable).
- `Date`/`Time` stored as TEXT. Batting cols are mis-typed `tinyint` (pandas auto-create on
  all-NULL data) — harmless for pitching rows (stay NULL).
- **Dedup key: `PlayID`** (varchar, present in both CSV and table). No `PitchUID` col exists.
- Load ALL practice pitching rows (LMU's own Trackman account). Current table ends 2025-04-14;
  feed runs ≥ 2026-05-14 (~13 months to add).

### 2. Trackman games → `GAMES`
- Files: SFTP `/v3/YYYY/MM/DD/CSV/YYYYMMDD-Opponent-N_unverified.csv` (**167 cols**, full Trackman
  game export). Folder date = upload date; **game date is in the filename / `Date` col**.
- `GAMES` table = **175 cols**, pandas-auto-typed. Column-name differences to reconcile:
  CSV `Top/Bottom` → table `Top.Bottom` (dot); align by a normalized-name map, load intersecting
  columns, leave table-only columns NULL. **No ML pitch-tagger needed** — `GAMES` stores raw
  `TaggedPitchType`/`AutoPitchType`.
- **Dedup key: `PitchUID`** (present in CSV; verify it exists in `GAMES` — if absent, fall back to
  composite `(GameID, PitchNo)` / `(GameUID, PitchNo)`).
- Both teams' pitches load (game files contain both). No LMU filter at load time (app filters).

### 3. HitTrax → `raw_practice_csv` → `practice_*`
Reproduce the original ELT documented in `docs/reference/hittrax-practice-analytics/`
(`pipeline-architecture.md` + `transformed_schema.sql` have the complete mapping).
- **Extract+Load (raw):** FTPS list root, for each `*.CSV` read with pandas, per row compute
  `row_hash = sha256(json.dumps(payload, sort_keys=True))`, `INSERT IGNORE` into `raw_practice_csv`
  (`source_file, ingested_at_utc, row_hash, payload` JSON). Skip <10-byte/empty files.
- **Transform:** rebuild the 3 derived tables from raw (transaction: `SET FOREIGN_KEY_CHECKS=0`,
  truncate the 3, reload, re-enable). Raw layer is immutable/complete so a full rebuild is safe
  and matches the reference.
  - **Unit conversions:** `mps_to_mph(x)=round(x*2.23694,2)`, `meters_to_feet(x)=round(x*3.28084,2)`;
    missing → NULL (never 0).
  - **Sessions** (`SessionExport_*`): map per `transformed_schema.sql` comments (AEV/MEV→avg/max
    exit velo mph, AD/MD→distances ft, AElv→launch angle, APV/MPV→pitch velo, AHZ1-13→zone_avg_*,
    AB/HC/Sing/Doub/Trip/Home/AVG/SLG/RBI/SCR, Type→session_type, Tag→session_tag, GT/SL, etc.).
    Unique key `(session_date, player_id, hittrax_session_id)`.
  - **Plays** (`PlaysExport_*`): map per schema (Velo→exit_velocity mph, Elv→launch_angle,
    Dist→distance_feet, GD→ground_distance, HorzAngle→horizontal_angle, EBV1/2/3→exit_velo_x/y/z,
    HT/Res/PT/QD→hit_type/result/pitch_type/zone_section, PP1/2/3→pitch_location_x/y/z ft,
    RadarVelo→pitch_velocity, PitchAngle, PBH/PBV, Id→play_id, etc.). Map `session_id` by joining
    on `(session_date, player_id)`. Unique key `play_id`.
  - **Player summary:** aggregate `practice_plays` by `player_id` (total_plays, avg/max EV,
    avg/max distance, hard_hit_rate EV≥95, fly_ball_rate HT=3, line_drive_rate HT=2, swing_rate,
    last_practice_date) + career batting totals from `practice_sessions`; `INSERT … ON DUPLICATE
    KEY UPDATE`.

## Architecture

New package `app/ingest/`:
- `config.py` — `IngestConfig` dataclass reading `TM_SFTP_*` + `HT_FTPS_*` from env (via existing
  `config.py`/dotenv). Missing var → clear error naming the var.
- `connections.py` — `open_sftp()` (paramiko `Transport`+`SFTPClient`, ctx mgr) and `open_ftps()`
  (`FTP_TLS`, ctx mgr). Timeouts, clean close.
- `bullpen.py` — `parse_bullpen_csv(text|df)->DataFrame` (pure map+filter) and
  `load_bullpen(*, dry_run)->LoadResult` (walk SFTP `/practice`, dedup `PlayID`, insert).
- `games.py` — `parse_game_csv(...)` + `load_games(*, dry_run)` (walk `/v3`, dedup `PitchUID`).
- `hittrax.py` — `extract_load_raw(*, dry_run)` + `transform(*, dry_run)` + `load_hittrax` wrapper.
- `common.py` — `LoadResult` dataclass (`inserted, skipped, files, date_min, date_max, dry_run`),
  `existing_keys(table, col)->set`, chunked insert helper, `mps_to_mph`/`meters_to_feet`.
- `cli.py` — Flask CLI commands `flask ingest bullpen|games|hittrax [--dry-run] [--limit N]`
  registered in `app/cli.py`, so creds/engine come from the app config.

Deps: add `paramiko>=3` to `requirements.txt` (ftplib is stdlib). `.env.example` gains the
`TM_SFTP_*` + `HT_FTPS_*` placeholder block.

## Testing strategy

- **Pure transforms** (parsing, name mapping, unit conversion, dedup-key, row_hash) unit-tested
  against the **downloaded sample CSVs** copied into `tests/fixtures/ingest/` (small: the 18-row
  bullpen sample, a trimmed game sample, a trimmed HitTrax plays+session sample).
- **I/O paths** (sftp/ftps walk, sql insert) tested with monkeypatched connection objects and a
  fake/served engine; assert dry-run writes nothing and idempotent re-run inserts 0.
- No test touches the live analytics DB for writes. Live prod load is an orchestrator step after
  dry-run verification.

## Provisional / confirm-later

- `GAMES` dedup key `PitchUID` (verify column exists; else composite). — data check at build time.
- Whether to also load Trackman `/practice/Hitting_*` anywhere (currently ignored). Coach call.
- HitTrax transform full-rebuild vs incremental (reference used full-rebuild; kept).
