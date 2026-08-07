# Phase 2 (Catching Slice) — Data Layer onto CAPS GAMES — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Move the **catching** data layer off the `tm_*` warehouse to read CAPS `GAMES`, proven identical by parity tests vs `app/data/catching.py` (kept as oracle), then cut the catching dashboard over — and fix video's CATCHER path to raw ids (finishing the video/id coupling).

**Architecture:** New module `app/data/catching_caps.py` = GAMES-based reimplementations of catching.py's QUERY functions, aliasing GAMES CamelCase → the snake_case names the catching.py TRANSFORMS expect (transforms imported unchanged). Catcher identity flips warehouse **surrogate `catcher_id`** → **raw `GAMES.CatcherId`** (== trackman id), mirroring the pitching slice. Parity bridges id-spaces via `catching.catcher_tm_id_for`. `catching.py` stays as the parity oracle (deleted in Phase 3). NO prod write (GAMES.Zone already backfilled; catching computes its own zone/in-zone from plate coords).

**Tech Stack:** Python, pandas, SQLAlchemy (`app.db.query_df`), MySQL, pytest. Reuses catching.py transforms (`add_framing_cols`, `apply_framing_filters`, `framing_table`, `caught_stealing_events/summary/trend`) + `hitting_wh.attack_zone` + `pitching_caps.game_context`/`_NUMERIC_GAME_ID_CLAUSE`.

## Global Constraints

- Return shapes are the contract — every `catching_caps` query returns the SAME columns/keys/types as its `catching.py` counterpart; transforms/figures/dashboard unchanged.
- **Aliasing** (`_CATCHER_SELECT`): GAMES → snake_case the transforms read: `PlateLocSide AS plate_loc_side, PlateLocHeight AS plate_loc_height, TaggedPitchType AS tagged_pitch_type, PitchCall AS pitch_call, BatterSide AS batter_side, PitcherThrows AS pitcher_throws, PlayResult AS play_result, PopTime AS pop_time, ExchangeTime AS exchange_time, ThrowSpeed AS throw_speed, CatcherId AS catcher_id, GameID AS game_id, Date AS game_date`. (`catcher_id` alias carries the RAW id — the transforms only ever read it, never map it.)
- **Catcher identity = raw `GAMES.CatcherId`.** LMU catchers: rows where `PitcherTeam='LOY_LIO'` (the catcher is on the pitching team — same rule as the oracle). Name from `GAMES.Catcher` ("Last, First"). Sibling union by name over GAMES.
- **Numeric-GameID guard:** apply `pitching_caps._NUMERIC_GAME_ID_CLAUSE` (`GameID REGEXP '^[0-9]+$'`) to whole-career/season/window queries (lmu_catchers, framing_season_tiles, game_pitches_season, range_pitches_for bounded) to exclude legacy composite-GameID rows + match oracle scope, AND to `games_for_catcher` (its `.astype(int)`-free but keep consistent; the tie-break there is `game_date DESC, game_id DESC` — guard so a legacy string GameID can't break ordering).
- `game_context` delegates to `pitching_caps.game_context` (already on GAMES).
- Parity tests hit the live DB; oracle = `catching.py`; bridge surrogate→raw via `catching.catcher_tm_id_for`. Pick a real LMU catcher with data (from `catching.wh_lmu_catchers()`).
- TDD, DRY, YAGNI, frequent commits. Branch `feat/caps-migration`. No prod write in this slice.

---

### Task 1: `catching_caps` loaders + sibling + game_context + framing parity

**Files:** Create `app/data/catching_caps.py`; Test `tests/test_catching_caps.py`.

**Interfaces (shapes identical to catching.py):** `_sibling_catcher_ids(catcher_id)` (raw GAMES.CatcherId sharing this id's `Catcher` name where `PitcherTeam='LOY_LIO'`), `_CATCHER_SELECT` (alias list above), `game_pitches_for(game_id, catcher_id)`, `range_pitches_for(catcher_id, start, end)`, `game_pitches_season(catcher_id)`, `game_context(game_id)` (delegate to `pitching_caps.game_context`).

**Parity approach:** `wh = catching.wh_lmu_catchers()`; pick surrogate `cid` with data; `raw = catching.catcher_tm_id_for(cid)`; `gid` from `catching.games_for_catcher(cid)`. Oracle df = `catching.game_pitches_for(gid, cid)`; caps df = `catching_caps.game_pitches_for(gid, raw)`. Assert equality on the TRANSFORM OUTPUTS the dashboard uses: `framing_table(add_framing_cols(df))`, `caught_stealing_summary(df)`, and `add_framing_cols(df)`'s CallType/Zone/InZone value_counts. (Output-level parity, tolerant of incidental raw-column diffs.)

- [ ] Step 1: write the failing parity test (`framing_table` on caps vs oracle for the fixture). Step 2: run, verify RED (module missing). Step 3: implement `_CATCHER_SELECT` + `_sibling_catcher_ids` + the three loaders + `game_context`. Step 4: GREEN. Step 5: add parity tests for `caught_stealing_summary` + `apply_framing_filters` (e.g. bat_side='Right') + `range_pitches_for` row-count. Step 6: commit.

> Notes: the transforms read `plate_loc_side`/`plate_loc_height` (snake) directly — the aliases supply them. `caught_stealing_events` already handles pop/exch/throw via `_col()` (both cases), but alias them to snake anyway for cleanliness. `game_pitches_for`/`range_pitches_for` include `game_date` (aliased from `Date`).

---

### Task 2: `catching_caps` identity + roster + season tiles + parity

**Files:** Modify `app/data/catching_caps.py`; Test `tests/test_catching_caps.py`.

**Interfaces:** `lmu_catchers()` (cols `CatcherId, Catcher` — RAW ids, name-deduped via ROW_NUMBER, scoped to the rolling recent window like pitching's `lmu_pitchers`; `WHERE PitcherTeam='LOY_LIO'`), `catcher_name(catcher_id)` (from `GAMES.Catcher`, "Last, First"), `catcher_tm_id_for(catcher_id)` (identity — returns the raw id), `catcher_profile(catcher_id)` (name + position 'C' + jersey/photo from `roster_media.player_media(raw_id)` directly), `games_for_catcher(catcher_id, start, end)` (cols game_id/game_date/GameLabel — GameLabel `"YYYY-MM-DD vs/@ OPP"`, LMU home via HomeTeamForeignID==78, matching the oracle format), `framing_season_tiles(catcher_id)` (dict games/pitches/net_strikes/steal_pct — reimplement the oracle's SQL aggregate on GAMES: the InZone box `ABS(PlateLocSide*12)<=10 AND ABS(PlateLocHeight*12-30)<=13`, stolen=out-of-zone StrikeCalled, lost=in-zone BallCalled, steal_pct=lost/valid_loc; sibling-union + numeric-GameID guard).

**Parity:** bridge via `catcher_tm_id_for`; `lmu_catchers` superset+window test (like pitching); `games_for_catcher` GameLabel-set equality (order-independent); `framing_season_tiles` dict equality vs oracle for the fixture (scope to shared season if GAMES-has-more-history diverges — document).

- [ ] Steps: failing parity tests → RED → implement → GREEN → commit. Verify `GAMES.Catcher` is "Last, First" (query live); match the oracle's exact GameLabel format.

---

### Task 3: Cut the catching DASHBOARD over + fix video CATCHER path + smoke

**Files:** `app/dashboards/catching/{selectors,callbacks,layout,tables}.py` + `tabs/*.py`; `app/data/video.py`.

- [ ] **Step 1:** grep `app/dashboards/catching/` for the `catching`-alias data-query calls (likely `from app.data import catching as C`); classify each as DATA query (repoint to `catching_caps`) vs TRANSFORM/figure (keep on `catching`). Data queries to repoint: `wh_lmu_catchers`→`lmu_catchers`, `catcher_name`, `catcher_profile`, `games_for_catcher`, `game_pitches_for`, `range_pitches_for`, `game_pitches_season`, `game_context`, `framing_season_tiles`, `catcher_tm_id_for`, `_sibling_catcher_ids`. KEEP on `catching`: `add_framing_cols`, `apply_framing_filters`, `framing_table`, `caught_stealing_events/summary/trend`, `PITCH_SPEED_MAP`, constants.
- [ ] **Step 2:** id-space flip in `selectors.py` — `resolve_catcher` (or equivalent) returns RAW ids (player→own_trackman_id, coach→requested raw); options from `catching_caps.lmu_catchers()`; drop any surrogate `catcher_tm_id`-mapping. Keep the resolver PURE (is_coach + own_trackman_id args).
- [ ] **Step 3:** fix video CATCHER path in `app/data/video.py` `_sibling_ids` — the catcher branch currently uses `catching._sibling_catcher_ids` (surrogate) + filters `fact.catcher_id` (surrogate). Change to `catching_caps._sibling_catcher_ids` (raw) + filter column `catcher_tm_id` (raw), mirroring the pitcher-path fix. (The catching dashboard now passes raw catcher ids to video.) Add a regression test like the pitcher one.
- [ ] **Step 4:** update `tests/test_catching*.py` monkeypatches → `catching_caps`; assert raw-id reality. Full suite FOREGROUND (`PYTHONIOENCODING=utf-8 python -m pytest -q`), all green.
- [ ] **Step 5:** commit.
- [ ] **Step 6 (controller):** live both-role smoke — coach picks any catcher / player locked to self; framing table + static-framing facets + caught-stealing render from GAMES; video catcher path returns data for a raw id.

---

## Self-Review notes
- Mirrors the pitching slice exactly (aliasing, raw-id flip, numeric-GameID guard, window-scoped list, parity-on-outputs). No report consumer (catching has none). No prod write.
- After this + video's catcher fix, ALL THREE game modules read CAPS for their subject; the video model's pitch metadata still comes via `vw_pitch_video`⋈fact — the FULL video-off-warehouse rewire (join `video_clips`⋈GAMES) is the separate **video slice** (next), required before Phase 3 drops `tm_*`.
- **Provisional/verify:** `GAMES.Catcher` "Last, First" format; framing_season_tiles GAMES aggregate matches oracle; GAMES-has-more-history divergence on season tiles (scope + document if needed).
