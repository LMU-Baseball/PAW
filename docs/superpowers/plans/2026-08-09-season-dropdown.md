# Season dropdown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development (recommended for the 3 parallel dashboard tasks) or executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add an academic-year Season filter (first, defaults to current) to Hitting/Pitching/Catching, scoping game list + dates + sidebar to that season, backed by per-(player, season) precalc so any season is a ~0.2 s read.

**Architecture:** New `app/data/seasons.py` (season math + available/current). Roster + rollup + sidebar reads become season-aware. The 3 precalc tables re-key on (player, season). The 3 dashboards gain a Season dropdown threaded through the selection store.

**Tech Stack:** Python, SQLAlchemy, Dash, pandas, pytest.

## Global Constraints

- **Academic year = Aug 1 → Jul 31**, label `"YYYY/YYYY+1"`. Default season = academic year of `MAX(GAMES.Date)` (latest *with data*), NOT calendar-today.
- **Back-compat via defaults:** season params default to `current_season()` so any un-migrated caller still works; the precalc read/compute default to the current season.
- Precalc stays a derived cache: schema change = drop + rebuild (no source data touched). Cache-clear + version-bump on rebuild unchanged.
- Return shapes of the sidebar dicts unchanged (same keys); only a `season` arg is added.
- Full suite green (637 as of `836b2e3`); keep the `_pa_count`, parity, caching, warmup behaviors.

---

### Task 1: `app/data/seasons.py` — season math (pure + one cached query)

**Files:** Create `app/data/seasons.py`; Test `tests/test_seasons.py`.

**Interfaces:** `season_label_for(date_str) -> str`; `season_bounds(label) -> (str, str)`; `available_seasons() -> list[str]` (newest-first, `@cached`); `current_season() -> str`.

- [ ] **Step 1 — failing tests:**
```python
from app.data import seasons as S
def test_season_math():
    assert S.season_bounds("2025/2026") == ("2025-08-01", "2026-07-31")
    assert S.season_label_for("2025-11-22") == "2025/2026"   # Nov -> that Aug-Jul year
    assert S.season_label_for("2026-05-16") == "2025/2026"   # May -> prior Aug's year
    assert S.season_label_for("2026-08-01") == "2026/2027"   # Aug -> new year
def test_available_and_current_live():
    seasons = S.available_seasons()
    assert seasons == sorted(seasons, reverse=True)          # newest first
    assert all(len(s) == 9 and s[4] == "/" for s in seasons)
    assert S.current_season() == seasons[0]                  # latest with data
```
- [ ] **Step 2:** Run → FAIL. **Step 3 — implement.** `season_label_for(d)`: parse `YYYY-MM-DD`; `y = year; ay = y if month>=8 else y-1`; return `f"{ay}/{ay+1}"`. `season_bounds(label)`: split on `/`; `(f"{a}-08-01", f"{int(b)}-07-31")`. `available_seasons()` (`@cached`): `SELECT DISTINCT Date FROM GAMES WHERE BatterTeam='LOY_LIO' AND Date REGEXP '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'` reduced to labels via `season_label_for`, sorted desc — or the GROUP BY query from the spec's grounding. `current_season()`: `season_label_for(MAX(GAMES.Date) among numeric LMU rows)`.
- [ ] **Step 4:** Run → PASS. **Step 5:** Commit `feat(season): seasons.py academic-year helpers`.

### Task 2: Season-aware rosters (`lmu_hitters/pitchers/catchers`)

**Files:** `app/data/hitting_caps.py`, `pitching_caps.py`, `catching_caps.py`; Tests in the existing caps test files.

- [ ] **Step 1 — failing test (per module):** `lmu_hitters(season="2024/2025")` returns only batters with numeric-GameID GAMES rows inside that season's bounds; `lmu_hitters()` defaults to `current_season()` and equals the previous current-window result set (same 25 hitters).
- [ ] **Step 2:** Run → FAIL. **Step 3 — implement.** Replace the `_RECENT_WINDOW_CLAUSE` scoping in `lmu_hitters` with a season-bounds `Date BETWEEN :s AND :e` (from `seasons.season_bounds(season or current_season())`), keeping the numeric-GameID guard + dedup. Same for `lmu_pitchers`/`lmu_catchers`. Keep `@cached` (key now includes the season arg).
- [ ] **Step 4:** Run → PASS. **Step 5:** Commit `feat(season): season-scoped lmu_* rosters`.

### Task 3: Per-season precalc (schema + compute + rebuild + read)

**Files:** `app/data/precalc.py`; `_compute_season_rollup` in the 3 caps modules; Test `tests/test_precalc.py`.

- [ ] **Step 1 — failing tests:** after `rebuild_hitting`, `read_hitting_season(WADAS, current_season())` is non-null and == `_compute_season_rollup(WADAS, current_season())`; a **past** season row exists for a player who played then and differs from the current-season row; every (player, season) in `lmu_hitters(season)` across `available_seasons()` has a row. (Same shape for pitching/catching.)
- [ ] **Step 2:** Run → FAIL. **Step 3 — implement:**
  - **DDL:** add `season_label VARCHAR(9)` to the PK of all 3 rollup tables (`PRIMARY KEY (batter_id, season_label)` etc.).
  - **Migration:** `ensure_tables` detects an existing rollup table whose PK is the old single column (query `INFORMATION_SCHEMA` / `SHOW KEYS`) and `DROP`s it before the `CREATE` (safe — derived). 
  - **Compute:** `_caps._compute_season_rollup(id, season_label)` computes over `seasons.season_bounds(season_label)` (date-bounded reads) instead of the rolling window; `season_label` stored from the arg. Default `season_label=None -> current_season()`.
  - **Rebuild:** `rebuild_hitting(engine)`: `for season in available_seasons(): for bid in lmu_hitters(season)["BatterId"]: rows.append(_compute_season_rollup(int(bid), season))`; replace-all + cache-clear + version-bump as today. Same for pitching/catching.
  - **Read:** `read_hitting_season(batter_id, season_label)` — `SELECT ... WHERE batter_id=:b AND season_label=:s`. Same for pitching/catching.
- [ ] **Step 4:** Run → PASS (allow the rebuild's extra time). **Step 5:** Commit `feat(season): per-(player,season) precalc rollups`.

### Task 4: Season-aware sidebar reads

**Files:** `hitting_caps.py` (`sidebar_stats`, `season_qab_rate`, `slash_line`, `_season_rollup`), `pitching_caps.py` (add `season_summary(pitcher_id, season)`; `range_summary` reads rollup when the range == season bounds), `catching_caps.py` (`framing_season_tiles(catcher_id, season)`); Tests in caps test files.

- [ ] **Step 1 — failing tests:** `sidebar_stats(WADAS, "2024/2025")` returns that season's `{qab,BA,SLG,OBP}` (a 1-row read; differs from `"2025/2026"`); missing row → compute fallback over the season bounds; default season arg == current.
- [ ] **Step 2:** Run → FAIL. **Step 3 — implement.** `_season_rollup(batter_id, season)` reads `precalc.read_hitting_season(batter_id, season)` else `_compute_season_rollup(batter_id, season)`. `sidebar_stats`/`season_qab_rate`/`slash_line` take `season` (default current). Pitching: `season_summary(pid, season)` reads `read_pitching_season(pid, season)` w/ fallback; the sidebar uses it. Catching: `framing_season_tiles(cid, season)` reads `read_catching_season(cid, season)` w/ fallback.
- [ ] **Step 4:** Run → PASS. **Step 5:** Commit `feat(season): sidebar KPIs read the (player,season) rollup`.

### Tasks 5–7: Season dropdown on the dashboards (Hitting, Pitching, Catching)

**Files (per dashboard):** `layout.py`, `callbacks.py`, `selectors.py`; Tests in the dash test files. These three are near-identical — build Hitting first (Task 5), then replicate to Pitching (6) + Catching (7). *(Parallelizable via subagents once Task 5 sets the pattern.)*

- [ ] **Step 1 — failing test:** `serve_layout` renders a `*-season` dropdown whose value == `current_season()` and options == `available_seasons()`; it's the first control in the selector row.
- [ ] **Step 2:** Run → FAIL. **Step 3 — implement (Hitting shown; P/C mirror):**
  - `serve_layout`: compute `season = seasons.current_season()`, `s0, e0 = seasons.season_bounds(season)`; `players = selectors.hitter_options(season=season, ...)`; `games_df = games_for_batter(default_batter, s0, e0)`; prepend `dcc.Dropdown(id="hit-season", options=[{"label":s,"value":s} for s in available_seasons()], value=season, clearable=False)` as the first item in the selector row; seed the `selection` store with `"season": season`, and the date control with `min_date=s0, max_date=e0, start=s0, end=e0`.
  - Callbacks: add `Input("hit-season","value")` to the preset/range refresh + selection callbacks; on season change recompute game options (season bounds) + date range (season bounds) + roster options (`lmu_hitters(season)`); thread `season` into the `selection` store; `_on_selection`/sidebar read `sidebar_stats(bid, sel["season"])`; scoreboard/game-data unchanged (game-scoped) except `ALL_IN_RANGE` uses season bounds.
  - `selectors.hitter_options`/`resolve_batter` gain `season` (pass to `lmu_hitters(season)`).
- [ ] **Step 4:** Run → PASS + the dashboard's existing tests green. **Step 5:** Commit `feat(season): Hitting season dropdown` (then `Pitching`, `Catching`).

### Task 8: Warm current season + verify

**Files:** `app/warmup.py`; final verification.

- [ ] Warm `available_seasons()`/`current_season()` + each module's **current-season** default player/game/sidebar (extend the existing warm to pass `current_season()`).
- [ ] `flask rebuild-precalc` → per-(player,season) rows (spot-check counts). `pytest -q` green. Live: restart; all 3 dashboards show the Season dropdown defaulting to current; pick a past season → game list + sidebar rescope; timing ~0.2 s. Commit `feat(season): warm current season`.

## Post-plan verification
- `pytest -q` green (637 + new). Season math + per-season precalc + dashboard-default tests pass.
- Live: Season dropdown is first, defaults to current; past seasons rescope + stay fast; `rebuild-precalc` populates per-season rows; `test_no_warehouse_refs` still green.

## Self-review notes
- **Spec coverage:** season model = Task 1; per-season precalc = Tasks 2–3; sidebar = Task 4; UI = Tasks 5–7; warm = Task 8.
- **Risk:** the precalc PK migration (drop+recreate) — safe because derived; the rebuild repopulates. Roster/rollup/sidebar all default to `current_season()` so partial deploys don't break.
- **Type consistency:** `season_label` is the `"YYYY/YYYY+1"` string everywhere; `season_bounds` returns ISO date strings matching `GAMES.Date`.
