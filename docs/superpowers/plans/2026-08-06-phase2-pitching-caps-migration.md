# Phase 2 (Pitching Slice) — Data Layer onto CAPS GAMES — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Move the **pitching** data layer off the `tm_*` warehouse to read CAPS `GAMES` — for BOTH consumers (the pitching dashboard AND the pitcher postgame report) — proven identical by parity tests against `app/data/pitching.py` (the warehouse module, kept as oracle) before cutover.

**Architecture:** New module `app/data/pitching_caps.py` holds GAMES-based reimplementations of pitching.py's QUERY functions only; it **imports the transforms + figures from `pitching.py` unchanged**. The transforms consume `snake_case` fact columns, so the GAMES queries **alias CamelCase → snake_case** (a shared `_PITCH_SELECT`) — the inverse of what hitting needed, and the lever that keeps every transform/figure/test untouched. Parity tests compare `pitching_caps.*` vs `pitching.*` live. Then the dashboard AND the report repoint their query calls to `pitching_caps`. `pitching.py` stays as the parity oracle until Phase 3 deletes its warehouse queries. Pitcher identity flips from the warehouse **surrogate** `pitcher_id` to the **raw** `GAMES.PitcherId` (== `trackman_id`), which simplifies role-gating (drops `_pitcher_id_for_tm`).

**Tech Stack:** Python, pandas, SQLAlchemy (`app.db.query_df`), MySQL, pytest, Playwright (report PDF smoke).

## Global Constraints

- **Return shapes are the contract.** Every `pitching_caps` query returns the SAME columns/keys/types as its `pitching.py` counterpart (the transforms/figures/report/dashboard must not change).
- **Aliasing:** GAMES queries alias to the snake_case names the transforms expect: `PitchCall AS pitch_call, RelSpeed AS rel_speed, PlateLocSide AS plate_loc_side, InducedVertBreak AS induced_vert_break, HorzBreak AS horz_break, VertApprAngle AS vert_appr_angle, TaggedHitType AS tagged_hit_type, TaggedPitchType AS tagged_pitch_type, AutoPitchType AS auto_pitch_type, PlayResult AS play_result, KorBB AS korbb, Balls AS balls, Strikes AS strikes, Inning AS inning, PAofInning AS pa_of_inning, PitchofPA AS pitch_of_pa, PitchNo AS pitch_no, OutsOnPlay AS outs_on_play, RunsScored AS runs_scored, BatterSide AS batter_side, SpinRate AS spin_rate, RelHeight AS rel_height, RelSide AS rel_side, Extension AS extension, ExitSpeed AS exit_speed, Zone AS izt_zone, GameID AS game_id, PitcherId AS pitcher_id, Top.Bottom AS top_bottom` (note: backtick `` `Top.Bottom` `` in SQL). `batters_faced` has no GAMES column → see Task 2.
- **Pitcher identity = raw `GAMES.PitcherId`.** LMU pitchers: `PitcherTeam='LOY_LIO'`. Names from `GAMES.Pitcher` ("Last, First" — verify format). Sibling union by name over GAMES.
- **Dates:** `GAMES.Date` is ISO (from the hitting slice's Task 1). Team names in `HomeTeam`/`AwayTeam`, LMU = `HomeTeamForeignID==78`.
- **Parity tests hit the live DB.** Oracle = `app/data/pitching.py`. Use a real LMU pitcher with data (derive from `pitching.wh_lmu_pitchers()` — its surrogate id maps to a raw id via `pitcher_tm_id_for`; the parity test bridges the id-spaces, see Task 2).
- **Two cutovers:** the pitching dashboard (Task 6) AND the postgame report (Task 7). Both must smoke green.
- TDD, DRY, YAGNI, frequent commits. Branch `feat/caps-migration`. Prod write (Task 1) is dry-run-first + user-approved.

---

### Task 1: Backfill `GAMES.Zone` from `fact.izt_zone` (shared prep, prod write)

Preserves in-zone% (`zone_location`) for pitching AND the video Zone column. `GAMES.Zone` exists but is NULL for backfilled rows; `fact.izt_zone` is fully populated (41,188 rows, values '1'..'9'/'Shadow'/'Ball').

**Files:** Create `app/ingest/backfill_zone.py`; Test `tests/test_backfill_zone.py`.

**Interfaces:** `backfill_zone(engine, *, dry_run=True) -> {"would_update": int}` — sets `GAMES.Zone = fact.izt_zone` joined on `GAMES.PitchUID = fact.pitch_uid`, only where they differ; dry-run counts, writes nothing.

- [ ] **Step 1: Failing test** — sqlite: a GAMES row + a fact row sharing PitchUID; `backfill_zone(dry_run=False)` sets GAMES.Zone to the fact value; dry-run leaves it unchanged. (Model on `tests/test_add_game_type.py`.)
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** (mirror `add_game_type.py`: read-only count in dry-run; `UPDATE GAMES g JOIN fact_tm_game_pitch f ON f.pitch_uid = g.PitchUID SET g.Zone = f.izt_zone WHERE g.Zone IS NULL OR g.Zone <> f.izt_zone` on the real run). Add `backfill-zone` CLI command.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit.**
- [ ] **Step 6: Dry-run → report `would_update` (~41,188) → USER APPROVAL → `--no-dry-run` → verify** `SELECT COUNT(*) FROM GAMES WHERE Zone IS NOT NULL AND Date>='2025-11-01'` ≈ 41,188 and distinct Zone values match fact's 11.

---

### Task 2: `pitching_caps` core pitch loaders + game_context + parity

**Files:** Create `app/data/pitching_caps.py`; Test `tests/test_pitching_caps.py`.

**Interfaces (return shapes identical to pitching.py):**
- `_PITCH_SELECT` (the aliased column list above).
- `game_pitches(game_id, pitcher_id)`, `game_pitches_for(game_id, pitcher_id)`, `range_pitches_for(pitcher_id, start, end)` → snake_case pitch frames (same cols the transforms read).
- `game_context(game_id) -> dict` (game_date/season_label/game_type/home_team/away_team/lmu_runs/opp_runs/lmu_is_home) from GAMES (+ GameType; teams from HomeTeam/AwayTeam; runs from `SUM(RunsScored)` by `Top.Bottom`).
- `_sibling_pitcher_ids(pitcher_id)` — all `GAMES.PitcherId` sharing this id's `Pitcher` name where `PitcherTeam='LOY_LIO'`.

**`batters_faced` gap:** GAMES has no `batters_faced` column (warehouse-derived running counter). `game_overall_line` reads `df["batters_faced"].max()`. Fix in caps: the aliased frame won't have `batters_faced`; add a computed `batters_faced` column in the loader = a running count of distinct (inning, pa_of_inning) ordered by pitch_no (reproduce the warehouse semantics), OR confirm `game_overall_line`'s only use is `.max()` and synthesize that as `_pa_count`. Simplest: in the loaders, after aliasing, add `df["batters_faced"] = (df.groupby(["inning","pa_of_inning"]).ngroup()+1).cummax()`-style running distinct-PA count. Verify `game_overall_line(caps_df)["batters_faced"] == game_overall_line(oracle_df)["batters_faced"]` in parity.

**Parity approach (bridges id-spaces):** pick a real LMU pitcher via the oracle: `wh = pitching.wh_lmu_pitchers()`; take a surrogate `pid`, its raw id `raw = pitching.pitcher_tm_id_for(pid)`, and a game `gid` from `pitching.games_for_pitcher(pid)`. Oracle df = `pitching.game_pitches_for(gid, pid)`; caps df = `pitching_caps.game_pitches_for(gid, raw)`. Assert equality on the transform OUTPUTS the report/dashboard use: `game_overall_line`, `pitch_characteristics`, `pitch_usage`, `zone_location`, `movement_summary`, `process_metrics`, `outcome_metrics`, `header_stat_line`, `splits_by_batter_side`. (Output-level parity, tolerant of incidental raw-column diffs.)

- [ ] Step 1: failing parity test on `game_overall_line` + `pitch_characteristics`. Step 2: RED. Step 3: implement `_PITCH_SELECT`, loaders, `game_context`, `_sibling_pitcher_ids`, batters_faced synthesis. Step 4: GREEN. Step 5: add parity tests for `zone_location` (proves the Zone backfill works), `movement_summary`, `header_stat_line`, `range_pitches_for`. Step 6: commit.

---

### Task 3: Reimplement the velo views (recent_outings, velo_trend) as GAMES queries + parity

The warehouse views: `vw_pitcher_appearance_velo` = per (game, pitcher) `COUNT(*)`, `AVG/MAX/MIN(rel_speed)` **filtered to `tagged_pitch_type IN ('Fastball','Sinker')`**, joined to dim/tm_team; `vw_pitcher_recent_outings` = that ⋈ active-players + `ROW_NUMBER`; `vw_pitcher_velo_trend` = recent_outings + `velo_change = avg − LAG(avg) OVER (PARTITION BY pitcher, season ORDER BY date)`.

**Interfaces (same columns as pitching.py):** `recent_outings(pitcher_id, game_id, n=5)`, `velo_trend(pitcher_id)`, `report_data_version(pitcher_id)`.

**GAMES reimplementation** (raw pitcher id, sibling union): per-appearance aggregate = `SELECT g.GameID AS game_id, g.Date AS game_date, g.GameType AS game_type, <home/away names>, AVG(RelSpeed) appearance_avg_velo, MAX(RelSpeed) appearance_max_velo, MIN(RelSpeed) appearance_min_velo, COUNT(*) pitch_count FROM GAMES g WHERE PitcherId IN (siblings) AND TaggedPitchType IN ('Fastball','Sinker') GROUP BY g.GameID, g.Date, ...`. `velo_trend` wraps it with a pandas or SQL `LAG` for `velo_change` (season boundary: derive season_label from Date via the existing season-block helper, or per-pitcher chronological LAG — match the oracle's PARTITION). **`report_data_version`** = `MAX(game_date)` of the pitcher's fastball/sinker appearances.

**Active-players divergence (note):** the warehouse filtered to roster-active players; GAMES has no status table, so caps uses the LMU-pitcher filter (`PitcherTeam='LOY_LIO'`). Document as a provisional, coach-confirmable difference.

- [ ] Steps: failing parity test (`recent_outings(pid,gid)` vs `pitching_caps.recent_outings(raw,gid)` on avg/max velo + pitch_count + order) → RED → implement → GREEN → add `velo_trend` parity (avg_velo/velo_change) + `report_data_version` → commit.

---

### Task 4: Pitcher identity + roster functions + parity

**Interfaces (same columns):** `lmu_pitchers()` (cols `PitcherId, Pitcher` — now RAW ids, deduped by name via ROW_NUMBER, scoped to the same rolling recent window as hitting's `lmu_hitters` for dropdown parity), `pitcher_name(pitcher_id)` (from `GAMES.Pitcher`), `pitcher_profile(pitcher_id)` (name/throws from GAMES + roster_media by raw id directly — drop `pitcher_tm_id_for` mapping), `pitcher_tm_id_for(pitcher_id)` (now identity — returns the raw id, kept for API compat), `games_for_pitcher(pitcher_id, start, end)`, `pitchers_for_game(game_id, sort)` (LMU pitchers in a game; reimplement `vw_game_pitchers` as `SELECT DISTINCT PitcherId, Pitcher FROM GAMES WHERE GameID=:gid AND PitcherTeam='LOY_LIO'`; sort by MIN(PitchNo) or name), `recent_games(limit)` (LMU games newest-first from GAMES).

**Name format:** `GAMES.Pitcher` — verify it's "Last, First". pitching.py builds "First Last" from tm_player for `pitcher_name` but "Last, First" for `wh_lmu_pitchers`/`pitchers_for_game`. Match EACH function's existing output format exactly (parity asserts it).

- [ ] Steps: parity tests for `lmu_pitchers` (superset+window, like hitting), `games_for_pitcher` (GameLabel equality), `pitchers_for_game` (player_id set + order), `recent_games` → RED → implement → GREEN → commit.

---

### Task 5: Season / range summaries + parity

**Interfaces:** `season_summary(pitcher_id)` (apps/pitches/k/bb), `range_summary(pitcher_id, start, end)` (Appearances/IP/K%/Walk%/Barrel% via the shared transforms). Both from GAMES (raw id, sibling union), reusing the pitching.py transforms (`k_pct`, `bb_pct`, `barrel_pct_ev`, `format_ip`) unchanged.

- [ ] Steps: parity tests vs oracle (dict equality for a real pitcher) → RED → implement → GREEN → commit.

---

### Task 6: Cut the pitching DASHBOARD over to `pitching_caps` (raw ids) + smoke

**Files:** `app/dashboards/pitching/{selectors,callbacks,layout}.py`.

**Key change — id-space:** `selectors.resolve_pitcher(requested, is_coach, own_trackman_id)` currently maps a player's `trackman_id` → surrogate `pitcher_id` via `_pitcher_id_for_tm`. With raw ids, `GAMES.PitcherId == trackman_id`, so resolution is direct (coach → requested raw id; player → own_trackman_id). Remove/retire `_pitcher_id_for_tm`. Repoint all `pitching.<query>` calls to `pitching_caps.<query>` (transforms/figures still import from `pitching`). Update any test monkeypatches from `pitching.*` to `pitching_caps.*`.

- [ ] Steps: grep `pitching\.` under `app/dashboards/pitching/`; repoint queries; fix resolver; full suite green; **live both-role smoke** (coach picks any pitcher / player locked to self; all tabs render from GAMES; velo trend + zone freq populate); commit.

---

### Task 7: Cut the pitcher REPORT over to `pitching_caps` + PDF smoke

**Files:** `app/reports/pitcher_postgame.py`, `app/reports/routes.py` (+ any report data calls). The report uses `pitching.{game_pitches_for or game_pitches, game_context, recent_outings, velo_trend, pitchers_for_game, recent_games, report_data_version}` + transforms.

- [ ] Steps: grep the report package for `pitching\.` query calls; repoint to `pitching_caps` (keep transforms/figures on `pitching`); role gate uses raw id (player self = `trackman_id == PitcherId`). Bump `pitcher_postgame._CODE_VERSION` (cache key) and clear `instance/report_cache/`. Build a real PDF for a known LMU pitcher/game via `pitching_caps` and confirm it renders (Playwright screenshot or byte-size sanity) + matches the warehouse-built one. Full suite green. Commit.

---

## Self-Review notes
- **Spec coverage:** Zone backfill (T1) closes the izt_zone gap for pitching + video; every `pitching.py` query reimplemented on GAMES + parity (T2–T5); both consumers cut over (T6 dashboard, T7 report). `pitching.py` retained as oracle → Phase 3 deletes its warehouse queries. Catching + video are separate follow-on plans (video now unblocked by the raw-id + Zone work here).
- **Parity philosophy:** assert on transform/figure OUTPUTS + report render, bridging the surrogate↔raw id-spaces via `pitcher_tm_id_for`.
- **Provisional/verify during execution:** `GAMES.Pitcher` name format ("Last, First"?); active-players→LMU-filter divergence in recent_outings; `batters_faced` synthesis matches the warehouse counter; velo-trend season-partition boundary; `GAMES.Zone` values equal `fact.izt_zone` post-backfill.
- **Deferred (carried):** GameID int-cast fragility for the future FileZilla loader; `_roster_lookup` '2025%' hardcode.
