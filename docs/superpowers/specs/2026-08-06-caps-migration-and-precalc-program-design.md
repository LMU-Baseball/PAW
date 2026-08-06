# CAPS migration + precalc program — design

**Date:** 2026-08-06
**Status:** Program overview (brainstorm). Sequencing approved by user (migration first). Each phase gets its own spec → plan → build.

## Goal

Two coupled user goals, tackled as one program:

1. **Speed.** The site recomputes everything on the fly; tab clicks take a few seconds and big requests can crash. User wants tabs to feel instant.
2. **Kill the data redundancy.** The DB currently holds BOTH the legacy ALL-CAPS tables (`GAMES`/`BULLPEN`/`PLAYERS`/`STANDINGS`/`VIDEO`, the originals — cleaner, tailored to this app) AND a newer `tm_*`/`fact_*`/`dim_*` star-schema warehouse (added by a non-technical analytics director; less clean, not all CAPS tables kept current). User wants: backfill CAPS from `tm_*` + FileZilla, **move the whole app to read CAPS, then delete `tm_*`.** The future SFTP pipeline will keep CAPS current, so precalc tables stem from CAPS.

## Profiling findings (2026-08-06, live DB, heaviest hitter = 1,094 pitches)

Measured where a hitting tab load actually spends time:

| What runs | Time | Nature |
|---|---|---|
| **Sidebar (every selection)** | **3.2 s** | ~6 separate queries; loads full season **twice** (QAB%, then slash line with a row-by-row Python loop) |
| `_sibling_ids` (returns 1 row) | 0.5 s | pure network latency |
| `wh_game_pitches` (24 rows) | 0.7 s | pure network latency |
| `all_pas_figure` (Plotly build) | **2.6 s** | **CPU, not a query** |
| JSON store round-trip | 0.01 s | negligible |

**Key insight:** every query costs ~500–900 ms **regardless of row count** — this is RDS us-east-2 network round-trip latency, not compute or data volume. Consequences:

- **Precalc's real value is collapsing many round-trips into one row read** (sidebar 6 queries → 1), plus killing the double-season-load. Not "avoid computation" — computation is cheap here.
- **Precalc does nothing for the 2.6 s Plotly figure.** That is a separate fix (cache the built figure / reduce points / WebGL).
- **An in-process cache** (memoize per player/game) makes repeat selections instant (0 queries) and is source-agnostic.

## Migration recon findings (2026-08-06, read-only)

**App→warehouse dependency map** (`grep`): `hitting_wh.py`, `pitching.py`, `catching.py` read `fact_tm_game_pitch`/`dim_tm_game`/`tm_player`/`tm_team` + views `vw_pitcher_recent_outings`/`vw_pitcher_velo_trend`/`vw_game_pitchers`; `video.py` reads `vw_pitch_video`. `bullpen.py` already reads CAPS `BULLPEN`; a legacy `hitting.py` already reads CAPS `GAMES` (and supplies the shared transforms `_add_pitch_category`/`qab_frame`).

**Safe / already aligned:**
- **GAMES has every needed column:** `PitchUID`, `GameID`, `GameUID`, `BatterId`, `PitcherId`, `CatcherId`, `Date`, `TaggedPitchType`, `AutoPitchType`, `HomeTeam`, `AwayTeam`, `PlateLocSide`, `PlateLocHeight`.
- **No ML dependency** — app uses `tagged_pitch_type` → `auto_pitch_type` fallback, both raw-Trackman columns in GAMES. (`ml_pitch_type` is unused.)
- **Video URLs are safe** — they live in base table **`video_clips`** (`pitch_uid`/`angle`/`s3_url`/`game_date`), NOT in `tm_*`. Only the *view* `vw_pitch_video` joins them to `fact_tm_game_pitch`+`dim_tm_game`.
- **Player logins already use raw Trackman ids** (`batter_tm_id` == `current_user.trackman_id` == `GAMES.BatterId`), so auth/roles survive the id-space change.

**The three real rocks (work, not blockers):**
1. **Video** — recreate the `vw_pitch_video` join against GAMES on `PitchUID` (video_clips untouched).
2. **Pitcher velo-trend / appearance views** (`vw_pitcher_recent_outings`, `vw_pitcher_velo_trend`, `vw_game_pitchers`, and their base `vw_pitcher_appearance_velo`/`vw_active_players`) — re-implement as GAMES queries in `pitching.py`.
3. **Team/player name resolution** — app gets display names from `tm_team.team_name`/`tm_player`; GAMES stores raw codes (`LOY_LIO`) + embedded names. Preserve the code→name mapping in a small CAPS lookup before dropping `tm_team`.

**The gap to fill:** GAMES currently ends ~May 2025. The warehouse's Fall-2025/Spring-2026 data (**142 games, 2025-11-22 → 2026-05-16**) is not yet in GAMES. Backfill it from FileZilla (the `/v3/**/CSV/*.csv` files are the native 175-col GAMES format; the `games` loader already exists).

**Warehouse objects to eventually drop:** base tables `dim_conference`, `dim_tm_game`, `fact_tm_game_pitch`, `tm_ingest_file`, `tm_player`, `tm_player_alias`, `tm_player_team_status`, `tm_team`, `tm_team_alias`, `tm_team_conference_history`, `tm_umpire`; plus dependent `vw_*` views. `video_clips` and `VIDEO` are NOT warehouse and stay.

## The 5-phase program (sequencing approved: migration first)

1. **Backfill GAMES from FileZilla.** Additive/safe; dry-run → verify coverage matches/exceeds the warehouse → load. Idempotent (dedup on `PitchUID`). tm_* untouched.
2. **Rewrite the data layer to read CAPS.** `hitting_wh`/`pitching`/`catching`/`video` query GAMES + small lookups, **keeping return shapes identical** so tabs/transforms/tests survive. Re-implement pitcher views; rewire video. **Parity-test** old-vs-new on the same inputs while both sources are live.
3. **Cut over + drop tm_\*.** Only after the app runs fully on CAPS and is verified. **Archive/rename tm_\* first** (safety net); drop later. Destructive — confirm with user at the moment.
4. **Precalc tables on CAPS (the site's primary read layer).** The CAPS tables are the raw source; a precalc layer is *derived* from them and **the site reads off precalc, not raw CAPS**. Two table families (see below). A rebuild command re-runs after each pipeline load; wired to a **daily cron** later (offseason now — no new games, so no live-update pressure yet).
5. **Filter changes + chart-tab perf.** Change filters to (a) prevent the site pulling too much at once (overload/crash) and (b) fit the precalc grain — season/multi-game views read rollups, not every pitch; large pitch-level selections are bounded. Plus the residual Plotly render cost (figure/selection caching) that even pre-shaped rows can't remove.

### Precalc layer design (Phase 4/5 refinement, user-confirmed 2026-08-06)

**Principle:** the site reads off precalc tables; only the precalc rebuild job reads raw CAPS. **Not everything collapses to one row** — so the layer has two families:

| Family | Grain | Serves | Site does |
|---|---|---|---|
| **Rollups** | player × date, player × season | KPI tiles, summary/usage/slash tables | reads 1 row |
| **Pre-shaped pitch rows** | one row per pitch, **all derived columns precomputed** (Zone, spray x/y, radial rx/ry, contact-type, count, result label, pitch category) | scatter / spray / heatmap / video / per-PA | `SELECT` + plot, **zero transforms** |

- Rollups eliminate the 6-query sidebar (§profiling) → one row.
- Pre-shaped pitch rows eliminate the pandas transforms; the residual cost is Plotly *render* (2.6 s for the PA facet), which **filters** must bound — a single view must never try to plot a whole season of pitches. Season/multi-game views read rollups; pitch-level charts are scoped to a bounded selection.
- **Refresh:** a `flask rebuild-precalc` command rebuilds all precalc tables from CAPS (full or per-player/date-incremental); the daily cron runs pipeline-load → rebuild-precalc. Adding a new metric/page = add its column/table to the rebuild job (documented maintenance cost).
- **Grain confirmed:** "by player and by date" (plus a season roll-up per player). Exact metric list + schemas designed in Phase 4's own spec.

## FileZilla /v3 recon (2026-08-06) — why the backfill source pivoted

Probing the Trackman SFTP `/v3` tree revealed it is NOT a clean per-LMU-game feed:
- `/v3/2025` = **21,828** "game CSV" files, `/v3/2026` = **27,501** — ~50k files in two upload-years alone.
- **`/v3/YYYY/MM/DD/` is the UPLOAD date, not the game date** — e.g. `/v3/2025/01/06/CSV/20220218-VATech-1.csv` is a 2022 VATech game bulk-uploaded in 2025. So a folder-date-pruned walk is impossible.
- It is a **multi-team archive** (VATech, Mercer, Colorado State, …), mostly non-LMU, plus non-pitch files (`_playerpositioning_FHC.csv`). The warehouse's clean 142 LMU games came from filtering this.
- The SFTP wrapper has **no keepalive** (`connections.py`), and full-tree walks are slow → connection drops mid-run.

**Consequence:** the existing `games` loader run as-is would ingest ~50k mixed-team/mixed-year/partly-non-game files into GAMES. Making it LMU-aware + de-noised + keepalive-robust is a real build — needed eventually for the live cron, but NOT to unblock the migration.

**Decision (user-confirmed 2026-08-06):** the one-time gap backfill comes from the **warehouse**, not FileZilla.

## Risk principles (apply to every phase)

- **Gap backfill from the warehouse** (`fact_tm_game_pitch`, already the clean 142 LMU games) via an in-DB transform to GAMES shape — NOT from the FileZilla swamp. FileZilla stays the source for the *future* live cron, via a hardened LMU-aware loader built later (before Fall 2026).
- **Read-only first, then dry-run, then load** for any SFTP→RDS write (the §10 safety plan). User eyeballs dry-run output before any real write.
- **Parity testing** in Phase 2: for each data function, assert CAPS output == warehouse output on the same player/game before cutover.
- **Never hard-delete `tm_*`** without an archive/rename + documented revert path.
- Keep the full test suite green (445 as of last session) at every step; return shapes are the contract.

## Phase 1 detail (first buildable sub-project) — warehouse → GAMES

- **Scope:** the warehouse gap only — the **142 LMU games, 2025-11-22 → 2026-05-16** (plus any Fall-2025 scrimmages in `dim_tm_game`). GAMES has **0 rows** in this span today, so it's a clean insert (no overlap, no dedup pressure).
- **Source:** `fact_tm_game_pitch` (⋈ `dim_tm_game` for `game_date`; ⋈ `tm_team` for team names if GAMES needs display names). Already LMU-filtered + coach-validated.
- **Transform:** map fact snake_case cols → GAMES CamelCase cols (the inverse of `hitting_wh._PITCH_SELECT` plus the rest). Special cases: `game_id`→`GameID`, `pitch_uid`→`PitchUID` (preserve — video join), `korbb`→`KorBB`, `top_bottom`→`Top.Bottom`; write `Date` as **ISO `YYYY-MM-DD`** (fixes the mixed-format issue for the new rows). Columns GAMES has but fact lacks stay NULL (the app only reads fact-derived columns).
- **Build:** a new one-time loader (e.g. `app/ingest/warehouse_to_games.py` or a `flask backfill-games` CLI), insert-only, idempotent (dedup on `PitchUID`), dry-run-capable (report would-insert N rows + game/date span). TDD with a small fixture. Reuses `common.chunked_insert`.
- **Steps:** (a) dry-run → would-insert N rows, game count, date span; (b) user reviews; (c) real load; (d) verify: GAMES now has all 142 warehouse games; per-game pitch counts match fact; spot-check a PitchUID row (GAMES vs fact) column-by-column; confirm `video_clips` still joins to GAMES on PitchUID.
- **Done when:** GAMES contains every warehouse LMU game with correct column population, verified against fact.
- **Out of scope:** the FileZilla LMU-aware loader (later, for the cron); HitTrax; any data-layer code changes (Phase 2); any drop (Phase 3).

## Open questions / provisional decisions

- **Loader branch:** merge `feat/data-ingestion-loaders` to `main` first (recommended — the whole program builds on it) vs. run Phase 1 from the branch. **[decide before Phase 1]**
- **RDS creds still unrotated** (§4 standing recommendation). Doing live prod writes (Phase 1 load) on unrotated creds — flag but not blocking (user has pushed/loaded before).
- **Backfill scope:** load all available v3 CSVs (idempotent) vs. only the warehouse span. Recommend: all available; dedup handles overlap.
- **Precalc grain (Phase 4):** confirmed "by player and by date" per user; exact metric list + table schema designed in Phase 4's own spec.
