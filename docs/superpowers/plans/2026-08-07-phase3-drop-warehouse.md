# Phase 3 — Retire the `tm_*` Warehouse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline, full-suite gate between parts). Steps use checkbox (`- [ ]`) syntax.

**Goal:** Remove the now-dead warehouse-query code + parity tests (preserving the pure helpers/transforms still imported by the CAPS layer and reports), then archive + drop the 11 redundant `tm_*`/`fact_*`/`dim_*` tables and their dependent views — leaving one non-redundant CAPS data world.

**Architecture:** The app already reads only CAPS (`GAMES`/`BULLPEN`/`video_clips`/… ) at runtime; the warehouse-query functions survive only as parity oracles for tests. Part A extracts the shared pure helpers out of the doomed `hitting_wh` module, removes the warehouse-query functions from `hitting_wh`/`pitching`/`catching`, deletes their parity tests, repoints the roster-media scraper to `GAMES`, and adds a runtime-purity guard. Part B (destructive) dumps the 11 tables to a gitignored backup, renames them to `zz_archived_*`, verifies the live app, then `DROP`s them (+ the ~13 dependent `vw_*`).

**Tech Stack:** Python, SQLAlchemy/PyMySQL, pandas, pytest (live-DB).

## Global Constraints

- **The app must stay fully functional on CAPS at every step.** Return shapes are the contract; the full suite (671 green as of `0719c4e`) is the gate.
- **Pure helpers that MUST survive** (still imported by live/CAPS code): `hitting_wh.attack_zone`, `hitting_wh._finish`, `hitting_wh._in_clause`, `hitting_wh._BIP_COLS`, `hitting_wh._roster_lookup` (reads `roster_players`, a survivor); all pure transforms in `pitching.py` (`bb_pct`, `barrel_pct_ev`, `format_ip`, `k_pct`, `pitch_color`, `pitch_type`, `pitch_usage_table`, `movement_summary`, `header_stat_line`, `process_metrics`, `outcome_metrics`, `count_states`, `fig_heatmap`, `fastball_callout`, …); `catching._pct` + the framing/caught-stealing transforms used by the catching dashboard tabs.
- **Keep the one-time ingest loaders** (`app/ingest/*`) — their tests use mocked/in-memory seams, so they stay green after the drop.
- **Destructive DB ops require the archive + backup first** and an explicit user go at the DROP step (user pre-approved "rename → verify → dump → drop today").
- **Warehouse objects (drop set):** base tables `dim_conference`, `dim_tm_game`, `fact_tm_game_pitch`, `tm_ingest_file`, `tm_player`, `tm_player_alias`, `tm_player_team_status`, `tm_team`, `tm_team_alias`, `tm_team_conference_history`, `tm_umpire`; + dependent views (all currently unused by the app): `vw_active_players`, `vw_available_game_types`, `vw_available_seasons`, `vw_cleaned_game_csv`, `vw_game_pitchers`, `vw_games`, `vw_pitch_video`, `vw_pitch_video_explorer`, `vw_pitcher_appearance_summary`, `vw_pitcher_appearance_velo`, `vw_pitcher_games`, `vw_pitcher_velo_leaderboard_spring_2026`, `vw_pitchers`. **Survivors:** `GAMES`, `BULLPEN`, `PLAYERS`, `STANDINGS`, `VIDEO`, `video_clips`, `NOTES`, `PAW_LOGS`, `roster_players`, and all recruiting/practice tables.

---

## Part A — make the code CAPS-pure (non-destructive)

### Task A1: Extract the shared pure helpers into a keeper module, delete `hitting_wh.py`

**Files:**
- Modify: `app/data/hitting.py` (receive `attack_zone`, `_finish`, `_in_clause`, `_BIP_COLS`, `_roster_lookup`) — `hitting.py` already reads CAPS and holds shared transforms, so it is the natural home.
- Modify: `app/data/hitting_caps.py:10` (import the four helpers from `hitting` instead of `hitting_wh`)
- Modify: `app/data/catching.py:16` (import `attack_zone` from `hitting` instead of `hitting_wh`)
- Delete: `app/data/hitting_wh.py`
- Delete: `tests/test_hitting_wh.py`
- Test: `tests/test_hitting_caps.py` (drop any parity assertions comparing to `hitting_wh`), `tests/test_hitting_dash.py` (same if present)

**Interfaces:**
- Produces: `hitting.attack_zone`, `hitting._finish`, `hitting._in_clause`, `hitting._BIP_COLS`, `hitting._roster_lookup` — identical signatures/bodies to the `hitting_wh` originals (moved verbatim, incl. the `_add_pitch_category` call inside `_finish` which `hitting.py` already defines/imports).

- [ ] **Step 1:** Read `hitting_wh.py` fully; copy the five helper definitions verbatim into `hitting.py` (resolving any now-local references — `_finish` uses `_add_pitch_category`, already in `hitting.py`). Ensure `_BIP_COLS` and any constants they need come along.
- [ ] **Step 2:** Repoint `hitting_caps.py:10` → `from app.data.hitting import _finish, _in_clause, _roster_lookup, _BIP_COLS` and `catching.py:16` → `from app.data.hitting import attack_zone`.
- [ ] **Step 3:** Grep for every remaining `hitting_wh` reference: `grep -rn "hitting_wh" app/ tests/`. Repoint or remove each (docstring mentions in `hitting_caps`/`hitting.py` are fine to reword). Delete `app/data/hitting_wh.py` and `tests/test_hitting_wh.py`.
- [ ] **Step 4:** Remove `hitting_wh`-parity assertions from `tests/test_hitting_caps.py`/`test_hitting_dash.py` (keep the behavioral CAPS tests).
- [ ] **Step 5:** Run `pytest tests/test_hitting_caps.py tests/test_hitting_dash.py tests/test_hitting.py -q`. Expected: green.
- [ ] **Step 6:** Commit: `refactor(phase3): move pure hitting helpers to hitting.py; delete hitting_wh oracle`.

### Task A2: Remove warehouse-query functions from `pitching.py`; delete its parity tests

**Files:**
- Modify: `app/data/pitching.py` (remove the warehouse-*query* functions; keep all pure transforms/figures — see Global Constraints)
- Test: `tests/test_pitching.py` (delete the parity/oracle tests that call the removed query functions; keep pure-transform tests)
- Test: `tests/test_pitching_caps.py` (drop any `pitching`-oracle bridge parity assertions)

**Query functions to REMOVE** (confirmed warehouse-only, called by parity tests only): `game_pitches`, `game_pitches_for`, `range_pitches_for`, `game_context`, `recent_outings`, `velo_trend`, `pitcher_name`, `pitcher_tm_id_for`, `recent_games`, `pitchers_for_game`, `wh_lmu_pitchers`, `_sibling_pitcher_ids`, `games_for_pitcher` (+ any module-level warehouse constants they alone use, e.g. `LMU_TEAM_ID`). **Verify before removing each:** `grep -rn "P\.<name>\|pitching\.<name>\|import <name>" app/ tests/` returns only `test_pitching.py` / other oracle tests.

- [ ] **Step 1:** For each candidate function, run the grep above to confirm no live caller. If a live caller exists (e.g. `pitching_caps` bridges it), STOP and reassess — it must be reimplemented on CAPS or kept.
- [ ] **Step 2:** Delete the confirmed warehouse-query functions + now-unused warehouse constants/imports from `pitching.py`. Leave the module docstring accurate (it now reads CAPS-derived dataframes passed in / pure transforms only).
- [ ] **Step 3:** Delete the corresponding parity/oracle tests from `tests/test_pitching.py` and any `pitching`-bridge parity in `tests/test_pitching_caps.py`.
- [ ] **Step 4:** Run `pytest tests/test_pitching.py tests/test_pitching_caps.py -q`. Expected: green.
- [ ] **Step 5:** Commit: `refactor(phase3): drop pitching.py warehouse queries + parity tests (keep transforms)`.

### Task A3: Remove warehouse-query functions from `catching.py`; delete its parity tests

**Files:**
- Modify: `app/data/catching.py` (remove warehouse queries; keep `_pct` + framing/caught-stealing transforms used by dashboard tabs; keep the `attack_zone` import from `hitting`)
- Test: `tests/test_catching_caps.py` (drop `catching`-oracle parity assertions), plus any `tests/test_catching*.py` oracle tests.

**Query functions to REMOVE:** `_sibling_catcher_ids`, `wh_lmu_catchers`, `catcher_name`, `catcher_tm_id_for`, `games_for_catcher`, `game_pitches_for`, `range_pitches_for`, `game_pitches_season`, `framing_season_tiles` **(warehouse variant)** — **verify each** with the same grep discipline as A2 (`catching_caps` reimplemented these on CAPS; confirm nothing live still calls the `catching.py` versions).

- [ ] **Step 1:** Grep-confirm no live caller for each candidate (only oracle tests). STOP-and-reassess if a live bridge exists.
- [ ] **Step 2:** Remove the confirmed query functions; keep `_pct` and the pure framing/CS transforms the dashboard tabs import.
- [ ] **Step 3:** Delete the corresponding parity/oracle tests.
- [ ] **Step 4:** Run `pytest tests/test_catching_caps.py -q` (+ other catching tests). Expected: green.
- [ ] **Step 5:** Commit: `refactor(phase3): drop catching.py warehouse queries + parity tests (keep transforms)`.

### Task A4: Repoint the roster-media scraper + delete the video parity oracle

**Files:**
- Modify: `scripts/scrape_roster_media.py` (`lmu_players()` → read `GAMES` instead of `fact_tm_game_pitch`)
- Test: `tests/test_video.py` (delete `test_parity_caps_matches_warehouse_oracle` — its warehouse oracle is now the last video-test warehouse ref; `test_video_source_is_caps_only` stays)

- [ ] **Step 1:** Rewrite `scrape_roster_media.lmu_players()` batter/pitcher queries to `SELECT BatterId AS id, Batter AS name, COUNT(*) AS n FROM GAMES WHERE BatterTeam=:team AND BatterId IS NOT NULL GROUP BY BatterId, Batter` (and the `PitcherId`/`Pitcher`/`PitcherTeam` analogue). `LMU_BATTER_TEAM` == `'LOY_LIO'`.
- [ ] **Step 2:** Delete `test_parity_caps_matches_warehouse_oracle` from `tests/test_video.py`.
- [ ] **Step 3:** Commit: `refactor(phase3): repoint roster scraper to GAMES; drop video parity oracle`.

### Task A5: Runtime-purity guard + full-suite gate

**Files:**
- Create: `tests/test_no_warehouse_refs.py`

- [ ] **Step 1:** Write a test that walks every `.py` under `app/data`, `app/dashboards`, `app/reports`, `app/main`, `app/auth` (EXCLUDING `app/ingest/`, which legitimately keeps the one-time loaders) and asserts none of the source contains the warehouse object names (`fact_tm_game_pitch`, `dim_tm_game`, `tm_player`, `tm_team`, `tm_umpire`, `tm_ingest_file`, `vw_pitch_video`, `vw_pitcher_`, `vw_game_pitchers`, `vw_active_players`, `vw_games`, `dim_conference`). (A short allowlist for the word "warehouse" in prose is fine; match the table tokens.)
- [ ] **Step 2:** Run it. Fix any straggler (reword docstrings; a real reference means a missed removal).
- [ ] **Step 3:** Run the FULL suite: `pytest -q`. Expected: green (671 minus the deleted parity tests, plus the guard). This proves nothing live called a removed function.
- [ ] **Step 4:** Live smoke: restart the dev server on this branch; coach + player, all dashboards + both reports render. (The DB still has `tm_*` at this point, so this validates the code refactor in isolation, before the drop.)
- [ ] **Step 5:** Commit: `test(phase3): add runtime warehouse-purity guard`.

---

## Part B — retire the warehouse (destructive DB)

### Task B1: Dump the 11 tables to a gitignored backup

**Files:**
- Create: `scripts/dump_warehouse.py` (Python dump — no `mysqldump` dependency)
- Modify: `.gitignore` (ignore the backup dir, e.g. `instance/warehouse_archive/`)

- [ ] **Step 1:** Write `dump_warehouse.py`: for each of the 11 tables, `SELECT *` via `query_df` and write to `instance/warehouse_archive/<table>.csv.gz` (gzip). Print row counts. Add a small `<table>.schema.sql` capture via `SHOW CREATE TABLE` so the structure is restorable.
- [ ] **Step 2:** Add `instance/warehouse_archive/` to `.gitignore`.
- [ ] **Step 3:** Run it. Verify each file exists + row counts match `SELECT COUNT(*)` (fact ~40k is the large one). **Show the user the manifest (table → rows → file size).**
- [ ] **Step 4:** Commit the script + gitignore (NOT the dumps): `chore(phase3): warehouse dump script (portable backup before drop)`.

### Task B2: Archive (rename) → verify → DROP

**Files:**
- Create: `scripts/archive_and_drop_warehouse.py` (or run as reviewed SQL) — two explicit phases behind flags: `--rename` and `--drop`.

- [ ] **Step 1:** `--rename`: `RENAME TABLE tm_x TO zz_archived_tm_x` for all 11 (RENAME preserves the internal FKs, which all point within the set). Views referencing them go stale but are not app-used. Report done.
- [ ] **Step 2:** Verify live: restart dev server; run the full app smoke (all dashboards + both reports, coach + player). Everything must still work (it reads CAPS only). Re-run `pytest -q` — still green (tests read CAPS; ingest tests are mocked). **If anything breaks, `RENAME` back — nothing is lost.**
- [ ] **Step 3:** **User go/no-go checkpoint** for the irreversible DROP.
- [ ] **Step 4:** `--drop`: drop the ~13 dependent views first, then `SET FOREIGN_KEY_CHECKS=0; DROP TABLE zz_archived_tm_*(×11); SET FOREIGN_KEY_CHECKS=1;` (or drop in FK-child-first order). Confirm `INFORMATION_SCHEMA` shows them gone and the survivors intact.
- [ ] **Step 5:** Final full-suite + live smoke on the post-drop DB. Commit: `chore(phase3): drop warehouse tables + dependent views (backup in instance/warehouse_archive)`.

---

## Post-plan verification

- `pytest -q` green; `tests/test_no_warehouse_refs.py` green.
- `INFORMATION_SCHEMA.TABLES`: the 11 `tm_*`/`fact_*`/`dim_*` tables and the 13 views are gone; `GAMES`/`BULLPEN`/`video_clips`/`VIDEO`/`roster_players` intact.
- Live: coach + player, all 5 dashboards + both report families render off CAPS.
- Backup manifest saved under `instance/warehouse_archive/` (gitignored).

## Self-review notes

- **Spec coverage:** program-spec Phase 3 ("archive/rename first, drop later; delete oracle modules + parity tests") = Parts A+B. The "3 rocks" from Phase 2 recon are already resolved (video rewired, velo views reimplemented in `pitching_caps`, team/name resolution baked into GAMES display cols) — Phase 3 only *removes* the now-dead originals.
- **Risk:** the one real risk is a candidate-remove function still having a live caller; every removal task gates on a grep + the full suite before commit. The purity guard (A5) is the backstop.
- **Reversibility:** irreversible only at B2/Step 4; everything before is a rename (revertable) or code on a branch. The gzip dump is the post-drop safety net.
