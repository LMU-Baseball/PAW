# PAW — Database reference & health audit

**Audited 2026-08-23** against the live warehouse, read-only. Numbers here are
measured, not estimated, unless a row says otherwise.

---

## 1. The two databases

| | Analytics warehouse | App database |
|---|---|---|
| Schema | `lmubaseball` | `paw_app` |
| Host | same RDS instance: `lmubaseball.c36mi2uaumxg.us-east-2.rds.amazonaws.com` | same |
| Accessed via | `app.db.get_engine()` (SQLAlchemy + PyMySQL) | Flask-SQLAlchemy (`config.SQLALCHEMY_DATABASE_URI`) |
| Holds | all Trackman / HitTrax / scraped data, **plus** coach-entered velo board + Cauldron | user accounts, coach notes, dev plans |
| Selected by | `MYSQL_DB` | `APP_DB_NAME=paw_app` (else ephemeral SQLite) |

Both live on one RDS instance. `APP_DB_NAME` is what makes accounts and notes
durable — without it the app falls back to SQLite that dies on redeploy.

### Server facts

| Setting | Value | Note |
|---|---|---|
| Version | MySQL **8.0.45** | |
| `innodb_buffer_pool_size` | **256 MB** | small instance (~1 GB RAM class) |
| `max_connections` | **60** | app pool is 10 + 20 overflow = up to 30 per instance |
| `sql_mode` | **`NO_ENGINE_SUBSTITUTION`** only | ⚠️ **STRICT mode is OFF** — see §4.2 |
| Charset / collation | `utf8mb4` / `utf8mb4_0900_ai_ci` | consistent across all 37 warehouse tables |
| `paw_app` collation | `utf8mb4_unicode_ci` | differs from the warehouse; harmless (never joined) |
| Time zone | UTC | |
| Uptime at audit | 33.8 days | |

**Buffer pool hit rate: 99.9985%** (116,836 disk reads against 7.93 billion read
requests). Despite the small pool, the working set fits comfortably in RAM. This
is also strong evidence that the 3.4 GB `NCAA` table is essentially never read.

---

## 2. Table inventory

37 tables in `lmubaseball`, 3 in `paw_app`. Exact row counts as of the audit.

### Core game data (Trackman)

| Table | Rows | Size | Date span | Status |
|---|---|---|---|---|
| `GAMES` | 104,764 | 99 MB | 2022-03-11 → 2026-05-16 | **live** — the main pitch table |
| `GAMES_v1` | 46,255 | 53 MB | → 2024-11-16 | **dead** — superseded, 0 code refs |
| `GAMES_v2` | 46,255 | 54 MB | → 2024-11-16 | **dead** — same data as v1, 0 code refs |
| `BULLPEN` | 24,581 | 14 MB | 2023-09-17 → 2026-05-13 | live (was stale, now repopulated) |
| `VIDEO` | 20,638 | 15 MB | — | live (legacy 4-angle URL table) |
| `video_clips` | 38,055 | 44 MB | 2026-03-08 → 2026-05-15 | live — S3 clip index |
| `POSITIONING` | 57,432 | 32 MB | 2022-03-22 → 2024-05-18 | **dead** — 0 code refs, ends 2024 |
| `B1` | 7,325 | 4.5 MB | 2023-09-18 → 2024-05-27 | **dead** — 0 code refs, ends 2024 |
| `ZONES` | 86 | tiny | — | **dead** — 0 code refs (oldest table, 2024-08-28) |

`GAMES` pitches by season: 2022 → 7,712 · 2023 → 9,987 · 2024 → 28,488 ·
2025 → 17,561 · **2026 → 40,898 across 140 games** (largest season on record),
plus **118 rows with a blank date** attributed to 60 blank `GameID`s.

### Practice data (HitTrax)

| Table | Rows | Date span | Status |
|---|---|---|---|
| `PRACTICE_SESSIONS` | 2,245 | 2023-10-11 → 2026-06-09 | live |
| `PRACTICE_PLAYS` | 17,978 | 2025-10-30 → 2026-06-09 | live |
| `RAW_PRACTICE_CSV` | 20,223 | ingested 2026-01-08 → 2026-06-10 | live (raw landing) |
| `practice_sessions` | **0** | — | ⚠️ empty lowercase twin, see §4.4 |
| `raw_practice_csv` | **0** | — | ⚠️ empty lowercase twin, see §4.4 |

Sessions per year: 2023 → 287 · 2024 → 670 · 2025 → 900 · 2026 → 388.

### Coach-entered data (irreplaceable — exists nowhere else)

| Table | Rows | Latest | Note |
|---|---|---|---|
| `velo_board_entries` | 19 | week of 2026-07-27 | only one week entered so far |
| `velo_board_overrides` | 20 | 2026-08-21 | |
| `cauldron_daily` | 33 | 2026-08-20 | actively in use |
| `cauldron_scoring` | 13 | 2026-08-11 | the tunable rubric |
| `cauldron_teams` | 9 | 2026-08-21 | |
| `NOTES` | 23 | — | legacy coach notes (legacy-keyed, reads as "" in app) |
| `paw_app.users` | 2 | — | shared coach + player logins |
| `paw_app.game_notes` | **0** | — | nothing written yet |
| `paw_app.dev_plans` | **0** | — | nothing written yet |

### Derived / precomputed

`precalc_hitting_player_season` (119), `precalc_pitching_player_season` (103),
`precalc_catching_player_season` (27), `precalc_meta` (version 174, last built
**2026-08-21**). All rebuildable by code.

### Recruiting / scraped

| Table | Rows | Last scraped | Code refs |
|---|---|---|---|
| `roster_players` | 2,760 | 2026-03-31 | 1 |
| `recruits` | 3,153 | 2026-03-24 | 0 |
| `retention_checks` | 967 | 2026-03-31 | 0 |
| `schools` | 71 | 2026-03-24 | 0 |
| `conferences` | 5 | 2026-03-24 | 0 |
| `scrape_runs` | 59 | 2026-03-31 | 0 |
| `STANDINGS` | 181 | — | 1 |
| `TRANSFERPORTAL` | 316 | — | 0 |

**All recruiting data was scraped once around 2026-03-24/31 and never refreshed** —
five months stale.

### Other

| Table | Rows | Note |
|---|---|---|
| `NCAA` | 2,982,153 | **3,386 MB = 90% of the entire database.** Zero indexes, zero application code references. See §5.1 |
| `PLAYERS` | 43 | live |
| `PAW_LOGS` | 3,613 | visit log, ends 2026-03-03, 0 code refs |
| `raw_cauldron_scoreboard` | 231 | written 2026-08-22, 0 code refs |
| `schema_migrations` | 3 | migration ledger |

---

## 3. Indexes

**14 tables have no PRIMARY KEY:** `B1`, `BULLPEN`, `GAMES`, `GAMES_v1`,
`GAMES_v2`, `NCAA`, `NOTES`, `PAW_LOGS`, `POSITIONING`, `STANDINGS`,
`TRANSFERPORTAL`, `VIDEO`, `ZONES`, `raw_cauldron_scoreboard`.

That is why duplicate pitches were possible (§4.1).

**`GAMES` has 12 secondary indexes**, all single-column: `Batter`, `BatterId`,
`BatterTeam`, `Catcher`, `CatcherId`, `CatcherTeam`, `Date`, `GameID`, `Pitcher`,
`PitcherId`, `PitcherTeam`, `PitchUID`. No composite indexes — dashboard queries
that filter by player *and* date can only use one.

**`NCAA` has no indexes at all** — 2.98M rows, so any query against it is a full
table scan.

**`video_clips` index (25.8 MB) is larger than its data (18.5 MB)** — it carries
UNIQUE indexes on *both* `s3_key` and `s3_url`, which are redundant (the URL is
derived from the key).

---

## 4. Problems found, worst first

### 4.1 `GAMES` contains 2,163 duplicate pitches — ⚠️ affects stats

- **2,163 distinct `PitchUID`s appear twice** (4,326 rows, 2,163 excess). None
  appears three or more times.
- **All of them are in the 2024 season** (4,319 rows) plus 7 with blank dates.
  2025 and 2026 are clean, so the current pipeline is not producing them; a 2024
  ingest ran twice.
- **Impact:** any 2024 pitch count, usage total, or per-pitcher aggregate is
  overstated by roughly 2%. Rate stats (velocity, whiff%) are barely affected.

**⚠️ They are NOT interchangeable, so they cannot simply be deduped.** Comparing
full-row MD5s across all **176** columns: only **342 pairs are byte-identical**;
**1,821 differ**. No pair has a completeness gap (identical non-null counts), so
"keep the fuller row" is not available. **No measurement column differs** —
`RelSpeed`, spin and trajectory are identical throughout. What differs is
contextual tagging:

| Column | Pairs differing |
|---|---|
| `Runners` | 1,501 |
| `Time` / `UTCDate` / `UTCTime` | 657 each |
| `PitchNo` / `PAofInning` / `PitchofPA` | 317 / 171 / 119 |
| **`Pitcher` / `PitcherId`** | **36** |
| **`Batter` / `BatterId`** | **14** |
| `Outs` / `Balls` / `Strikes` | 29 / 23 / 19 |
| `PlayResult` / `KorBB` / `PitchCall` | 8 / 6 / 2 |

So these are the same physical pitches ingested twice from Trackman exports whose
tagging was **revised between exports** — and `GAMES` has no ingest-timestamp
column, so there is no way to tell which row holds the corrected tagging. A blind
`DELETE ... LIMIT 1` would coin-flip old-vs-revised tagging on 1,821 pitches and
attribute 36 of them to the wrong pitcher.

**The fix is a 2024 re-ingest from the Trackman source (still on the FTP), into a
table with `UNIQUE(PitchUID)` from the start** — which resolves this by
construction. Not a one-liner; needs a scope decision.

Separately, **368 rows have an empty-string `PitchUID`**. These are **368
distinct rows from a single `GameID` on a single date** — one real game whose
UIDs never populated, not junk. And **118 rows have an empty `Date`**. Because
`PitchUID` is `varchar(255) NOT NULL`, the usual "set blanks to NULL so UNIQUE
tolerates them" trick needs an `ALTER` first.

### 4.2 STRICT mode is off — this is *how* the bad rows got in

`sql_mode` is only `NO_ENGINE_SUBSTITUTION`. MySQL 8's default includes
`STRICT_TRANS_TABLES` and `ONLY_FULL_GROUP_BY`; both are disabled here. Under
non-strict mode MySQL **silently coerces** bad input instead of rejecting it —
an out-of-range number becomes 0, an invalid date becomes `0000-00-00` or empty,
an over-long string is truncated. Nothing errors, so the ingest looks successful.

Fixing this requires an **RDS parameter group change** (needs AWS console access).
Until then, validation has to live in the ingest code.

### 4.3 Date and time columns are `TEXT`, in inconsistent formats

`GAMES.Date` is `text`, not `DATE`. So are `BULLPEN.Date`, `B1.Date`,
`POSITIONING.Date`, and the whole `*Time` family. Formats are not consistent:

| Column | Example | Format |
|---|---|---|
| `GAMES.Date` | `2026-05-16` | ISO — sorts correctly by luck |
| `GAMES.UTCDate` | `5/3/24` | M/D/YY — does **not** sort chronologically |
| `GAMES_v1/v2.Date` | `5/3/24` | M/D/YY |
| `GAMES.Time` | `7:34:47 PM` | 12-hour |
| `GAMES.UTCTime` | `59:59.6` | minutes:seconds — a different unit entirely |
| `STANDINGS.Date` | `Apr01(Tue)` | display string |
| `cauldron_daily.play_date` | `2026-08-20` | `varchar` |
| `velo_board_entries.week_start` | `2026-07-27` | `varchar` |

Consequences: no date arithmetic without `CAST`, range filters are string
comparisons, and `MIN`/`MAX` on any non-ISO column is meaningless. The app works
today because the columns it filters on happen to be ISO-formatted.

### 4.4 Empty lowercase "shadow" tables

`practice_sessions` (created **2026-08-22**) and `raw_practice_csv` (created
2026-08-10) are empty lowercase twins of the real `PRACTICE_SESSIONS` /
`RAW_PRACTICE_CSV`. On Linux MySQL table names are case-sensitive, so these are
genuinely separate tables. They are referenced only by
`scripts/rename_practice_tables.py`, which renames lowercase → uppercase —
meaning something recreates the lowercase name on each run and the rename is
re-applied. **Risk:** if any code path ever reads the lowercase name it silently
gets zero rows.

### 4.5 453 orphaned `PRACTICE_PLAYS`

453 plays reference a `session_id` with no matching `PRACTICE_SESSIONS` row.
Likely fallout from `transform()` destructively rebuilding those tables.

### 4.6 8,400 aborted connections in 34 days

~250/day, against a MySQL port reachable from the public internet. Consistent
with internet-wide scanning or brute-force attempts. Combined with a
never-rotated password that was once committed in plaintext, this is the most
concrete security argument for locking the security group down.

---

## 5. Recommendations, prioritized

### P0 — do before the season starts

1. **Back up including `NCAA` first:** `python scripts/backup_warehouse.py --with-ncaa`.
   Every destructive step below assumes this exists.
2. **Re-ingest the 2024 season** rather than deduping in place — see §4.1 for why
   a blind dedupe would corrupt pitcher attribution.
3. **Add a UNIQUE constraint on `GAMES.PitchUID`** once #2 lands, so this cannot
   recur. Highest-value schema change available, but blocked until the duplicates
   and the 368 blank UIDs are resolved.
4. **Verify the fall ingest actually ingests.** Data currently ends mid-May 2026.
   The HitTrax cron is still `--dry-run --limit 20`, and that limit is an
   alphabetical prefix that would never reach new files — flipping it live as-is
   produces a permanently-green job that ingests nothing. Fix incremental file
   selection before the first fall practice.

### P1 — cleanup (reclaims ~93% of the database)

5. **Archive and drop `NCAA`** — 3,386 MB, 90% of the database, zero code
   references, and the buffer-pool numbers prove it is never read. Check the
   legacy R apps in `src/` before dropping, since they are gitignored and were
   not searched.
6. **Drop `GAMES_v1` and `GAMES_v2`** — 106 MB, superseded by `GAMES`, identical
   to each other, zero code references, untouched since Jan 2025.
7. **Drop the empty lowercase twins** and fix whatever recreates them.
8. **Consider dropping `POSITIONING` (32 MB), `B1` (4.5 MB), `ZONES`, `PAW_LOGS`,
   `TRANSFERPORTAL`** — all zero code references, all ending in 2024.

After 5–7 the database goes from **3.7 GB to roughly 260 MB**, which shrinks
backups, cuts RDS storage cost, and leaves the working set entirely in RAM.

### P2 — schema hardening

9. Add PRIMARY KEYs or UNIQUE constraints to the remaining 13 tables that lack
   them, starting with `BULLPEN` and `VIDEO`.
10. Add composite indexes to `GAMES` matching real query patterns —
    `(PitcherId, Date)` and `(BatterId, Date)` — and consider dropping the
    low-cardinality single-column indexes (`BatterTeam` card. 50, `CatcherTeam`
    43), which cost write throughput on ingest and buy little.
11. Drop the redundant `video_clips.s3_url` UNIQUE index (keep `s3_key`).
12. Plan a typed-date migration (§4.3). Lowest-risk path: add a real `DATE`
    generated column alongside the text one, migrate queries, then retire the
    text column. Do not attempt this mid-season.

### P3 — security & operations

13. **Rotate the RDS password** (long-deferred). Requires knowing every consumer
    first — see `docs/deploy-meeting-brief.md`.
14. **Restrict the security group** to known hosts; §4.6 is the evidence.
15. **Turn `STRICT_TRANS_TABLES` on** via an RDS parameter group.
16. **Verify RDS automated backups and the retention window** — cannot be checked
    without console access; it is on the AWS access checklist.
17. **Schedule `scripts/backup_warehouse.py`** weekly now that it exists and is
    proven to restore.

### P4 — freshness before the semester

18. Re-scrape the recruiting tables if the recruiting board is in use (5 months stale).
19. Re-run `scripts/scrape_roster_media.py` for new roster players — the shipped
    `instance/roster_media.json` is a 2026-07-22 snapshot.
20. Get the coach to confirm the provisional Cauldron formulas and point values
    before coaches rely on the numbers in-season.

---

## 6. Application performance: response compression

**Status: FIXED 2026-08-23.** `Flask-Compress>=1.14` is now in
`requirements.txt` and all 7 `Dash(...)` call sites pass `compress=True`, so the
app compresses its own responses on any host.

**What the finding was:** Dash 4.4.0 defaults `compress=False`
(`get_combined_config("compress", compress, False)`), none of the 7 Dash apps
overrode it, and `flask-compress` was neither installed nor in
`requirements.txt`. So the application did no gzip/brotli compression at all.
Note the two halves are coupled: `compress=True` is a silent no-op unless the
`Flask-Compress` package is present, so the requirement and the kwarg must ship
together.

**But in production today it does not matter:** Render sits behind Cloudflare,
which already returns `Content-Encoding: br` (verified against the live login
page). The edge compresses responses, including the JSON callback payloads that
dominate a Dash app's traffic.

**It starts mattering the moment you move to AWS.** A Lightsail or EC2 box has no
CDN in front of it, so without action every Plotly figure payload ships
uncompressed. Two options:

- **App-level (portable) — this is what we did.** `Flask-Compress` in
  `requirements.txt` + `compress=True` on each `Dash(...)`; Dash wires it
  automatically (`dash/backends/_flask.py:360`). Works identically on any host.
- **Server-level (optional, additive):** also enable `gzip`/`brotli` in the nginx
  config from `docs/DEPLOY.md`. Marginally faster (no Python CPU cost), but
  host-specific — and unnecessary now that the app handles it.

Plotly figure JSON is highly repetitive text and typically compresses 70–90%, so
this is a real win on the AWS path — just not an urgent one while Cloudflare is
doing it for you.

---

## 7. How to re-run this audit

The audit scripts were scratch, not committed. What is committed:

- `scripts/backup_warehouse.py` — dump + verify (see §5 P0).
- `app/db.py::query_df` — the read-only query helper everything above used.

Useful one-liners live in this doc's queries; the highest-value recurring checks
are duplicate `PitchUID` count, max `Date` per source table (freshness), and
`precalc_meta.updated_at`.

---

## 8. Change log — what was applied 2026-08-23

### Done in code (tests green)

| Change | Files |
|---|---|
| **Decoupled PAW from `player_stats_summary`** — removed the `DELETE`, the `INSERT` (`_PLAYER_STATS_SQL`, 116 lines), and the `SELECT COUNT(*)`; the returned `players` count is now computed from the loaded frames, mirroring the dry-run branch | `app/ingest/hittrax.py`, `app/ingest/cli.py` |
| **Removed 8 index-defeating `DATE(col)` filters.** ISO-text columns compare as plain strings; the `DATETIME` column uses a half-open range | `app/data/bullpen.py` (5), `app/data/practice.py` (3), `app/data/velo_board.py` (2 — BULLPEN only; the GAMES clause was already correct) |
| **Enabled response compression** — `Flask-Compress>=1.14` + `compress=True` on all 7 dashboards | `requirements.txt`, all 7 `app/dashboards/*` |
| **Disabled the destructive DROPs** in the Streamlit reference schema and added a warning banner explaining the 2026-08-22 incident | `docs/reference/hittrax-practice-analytics/transformed_schema.sql` |
| **Corrected a stale docstring** — BULLPEN is no longer "stale, ends 2025-04-14"; it runs through 2026-05-13 | `app/data/bullpen.py` |
| **Updated two tests to the new spec** — one now asserts PAW *never* touches `player_stats_summary`; the other's injected failure moved to the `total_plays` back-fill | `tests/test_ingest_hittrax_transform.py` |
| **New:** `scripts/apply_db_indexes.py` (4 indexes, additive, idempotent, `--dry-run`) | — |
| **New:** `scripts/backup_warehouse.py` (dump + verify, Docker `mysqldump`) | — |

### Requires a human to run (the assistant is blocked from production writes)

```
python scripts/apply_db_indexes.py
```

Adds `BULLPEN(PitcherId, Date(10))`, `VIDEO(PitchUID(64), GameID(32))`,
`GAMES(PitcherId, Date(10))`, `GAMES(BatterId, Date(10))`. `--dry-run` validated.

### Deliberately NOT done

| Item | Why |
|---|---|
| **`GAMES` dedupe** | The 2,163 duplicate pairs are **not** interchangeable — 1,821 differ in tagging (`Runners`, timestamps, sequence numbers, and `Pitcher` in 36 pairs), with no completeness gap and no ingest timestamp to break the tie. Deleting arbitrarily would mis-attribute pitches. Needs a 2024 re-ingest from the Trackman source instead. |
| **`UNIQUE(GAMES.PitchUID)`** | Blocked by the 2,163 duplicates *and* 368 blank UIDs (one real game); the column is `NOT NULL`, so the multiple-NULLs trick needs an `ALTER` first. |
| **Dropping `NCAA`** | Keeping it — it is national D1 Trackman data with real scouting value. It does need indexes before it is queryable. |
| **Dropping the lowercase shadow tables** | They belong to the Streamlit app's ETL, not PAW. |
| **Creating `player_stats_summary`** | Same — Streamlit's table. PAW no longer references it. |
| **Typed-date migration** | Correct, but not mid-season. |
