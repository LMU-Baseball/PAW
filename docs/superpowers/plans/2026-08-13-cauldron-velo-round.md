# Cauldron + Velo Board Round Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Competitive Cauldron a weekly challenge, give both boards a shared edit UX (buttons on top, grid hidden until Edit), add a cauldron team captain, fix scoreboard readability, and speed up the grid.

**Architecture:** Data-layer changes (week-window read, captain flag + setter, cached day-compute) feed presentation changes (week-bounded scoreboard, captain ★/sort, dark background) and UX changes in the two dashboards' grids/callbacks (top buttons, hide-until-edit). No `cauldron_daily` schema change — the weekly bound is a read-time date window; `cauldron_teams` gains an additive `is_captain` column.

**Tech Stack:** Flask + Dash (dash_table), SQLAlchemy/RDS MySQL, pandas, pytest.

**Spec:** `docs/superpowers/specs/2026-08-13-cauldron-velo-round-design.md`

## Global Constraints

- No `cauldron_daily` schema change. `cauldron_teams` migration is additive + idempotent (ALTER ADD COLUMN only if missing).
- `week_start` is a Monday ISO date; the week window is `week_start .. week_start+6` inclusive. Reuse `velo_board.week_start_for(d)`.
- Coach-write double gate stays: layout omits grid for players; callbacks re-check `current_user.is_coach`.
- Teams persist across weeks (keyed by season `cycle_id = f"{season}-c1"`); only scoring is week-bounded.
- One captain per team: setting a captain clears any prior captain on that team.

---

### Task 1: Cauldron data layer — week window, captain, cached compute

**Files:**
- Modify: `app/data/cauldron.py` (`ensure_tables`, `read_daily`, new `set_captain`, `@cached` on `compute_players_day`)
- Test: `tests/test_cauldron.py`

**Interfaces:**
- Produces: `read_daily(play_date=None, player_id=None, start=None, end=None) -> DataFrame` (adds `start`/`end` inclusive window on `play_date`); `set_captain(player_id, cycle_id, updated_by=None) -> None` (sets `is_captain=1` for the player, `0` for every other player on the same team in that cycle); `read_teams(cycle_id)` now returns an `is_captain` column; `compute_players_day` is `@cache.cached`.

- [ ] **Step 1: Failing tests**

```python
def test_read_daily_window_filters_by_date_range(monkeypatch):
    from app.data import cauldron
    captured = {}
    monkeypatch.setattr(cauldron, "query_df",
                        lambda sql, params=None: (captured.update(sql=sql, params=params or {}), __import__("pandas").DataFrame())[1])
    cauldron.read_daily(start="2026-03-02", end="2026-03-08")
    assert "play_date >= :start" in captured["sql"] and "play_date <= :end" in captured["sql"]
    assert captured["params"]["start"] == "2026-03-02" and captured["params"]["end"] == "2026-03-08"


def test_compute_players_day_is_memoized(monkeypatch):
    from app.data import cauldron, cache
    cache.clear_all()
    calls = []
    monkeypatch.setattr(cauldron, "query_df",
                        lambda sql, params=None: (calls.append(1), __import__("pandas").DataFrame())[1])
    cauldron.compute_players_day([1, 2], "2026-03-02")
    cauldron.compute_players_day([1, 2], "2026-03-02")
    assert len(calls) == 1
```

- [ ] **Step 2: Run — expect FAIL** (`read_daily` has no `start`/`end`; compute not cached).

- [ ] **Step 3: Implement**
  - `read_daily`: add `start`/`end` params; append `play_date >= :start` / `play_date <= :end` clauses.
  - `@cache.cached` above `compute_players_day` (import already `from app.data import cache`; add `from app.data.cache import cached` or use `cache.cached`).
  - `ensure_tables`: after the CREATEs, ALTER `cauldron_teams` ADD `is_captain TINYINT(1) NOT NULL DEFAULT 0` guarded by an information_schema check:
    ```python
    def _ensure_column(conn, table, col, ddl):
        exists = conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = :t AND column_name = :c"),
            {"t": table, "c": col}).scalar()
        if not exists:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))
    ```
    call `_ensure_column(conn, TEAMS_TABLE, "is_captain", "is_captain TINYINT(1) NOT NULL DEFAULT 0")`.
  - `set_captain(player_id, cycle_id, updated_by=None)`: `UPDATE cauldron_teams SET is_captain = CASE WHEN player_id = :p THEN 1 ELSE 0 END WHERE cycle_id = :c AND team = (SELECT team FROM (SELECT team FROM cauldron_teams WHERE player_id=:p AND cycle_id=:c) t)`. (Two-step: read the player's team, then `UPDATE ... SET is_captain = (player_id = :p) WHERE cycle_id=:c AND team=:team`.)

- [ ] **Step 4: Run — expect PASS.** Also run `tests/test_cauldron.py -q`.

- [ ] **Step 5: Commit** `feat(cauldron-data): week-window read_daily, is_captain + set_captain, cache compute_players_day`

---

### Task 2: Cauldron visual — captain ★ + sort + dark scoreboard

**Files:**
- Modify: `app/dashboards/cauldron/visual.py` (`scoreboard_view`, styles)
- Test: `tests/test_cauldron_visual.py`

**Interfaces:**
- Consumes: `teams_df` now carries `is_captain`.
- Produces: `scoreboard_view` renders the captain first within their team with a leading `★`, and the table sits on a solid dark background.

- [ ] **Step 1: Failing test** — extend the fixture's `teams` with `is_captain` (1 for player 2 on Crimson), assert the Crimson team's FIRST player row is player 2 and its text contains `★`; assert the table/container style has a dark `backgroundColor` (e.g. contains `#161616` or `rgb(22`).

```python
def test_scoreboard_captain_first_with_star():
    import pandas as pd
    from app.dashboards.cauldron import visual as V
    scoring = pd.DataFrame([{"metric": "strike_pct", "label": "Strike%", "sort_order": 1, "is_manual": False}])
    teams = pd.DataFrame([
        {"player_id": 1, "team": "Crimson", "is_captain": 0},
        {"player_id": 2, "team": "Crimson", "is_captain": 1},
    ])
    daily = pd.DataFrame([
        {"player_id": 1, "play_date": "2026-08-01", "metric": "strike_pct", "points": 30, "source": "auto"},
        {"player_id": 2, "play_date": "2026-08-01", "metric": "strike_pct", "points": 10, "source": "auto"},
    ])
    names = {1: "Aaron, Bo", 2: "Cruz, Dan"}
    view = V.scoreboard_view(daily, teams, scoring, names)
    rows = [n for n in _flatten(view) if isinstance(n, html.Tr)]
    # first player row under Crimson header is the captain (player 2), despite fewer points
    player_rows = [r for r in rows if "Cruz, Dan" in _cell_text(_cells(r)[0]) or "Aaron, Bo" in _cell_text(_cells(r)[0])]
    assert "Cruz, Dan" in _cell_text(_cells(player_rows[0])[0])
    assert "★" in _cell_text(_cells(player_rows[0])[0])
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement**
  - Sort key within team: `key=lambda p: (0 if captain else 1, -total, name)` so captain floats above the points sort.
  - Prepend `"★ "` to the captain's display name.
  - Add a solid dark background: wrap the table container `style` with `backgroundColor: "#161616"` (and keep `overflowX`), and ensure player-row text stays `#fff` (already is) so it reads.
  - `is_captain` lookup: `captain_ids = set(teams.loc[teams.get("is_captain", 0) == 1, "player_id"].astype(int))` (guard when column absent).

- [ ] **Step 4: Run — expect PASS.** Run `tests/test_cauldron_visual.py -q`.

- [ ] **Step 5: Commit** `feat(cauldron-visual): captain star + top sort, dark scoreboard background`

---

### Task 3: Cauldron grid — captain control, top buttons, hide-until-edit, drop Recompute

**Files:**
- Modify: `app/dashboards/cauldron/grid.py` (`coach_grid`, `_grid_rows`, `save_grid`, columns)
- Modify: `app/dashboards/shell.py` if a shared toggle helper is cleaner (optional)
- Test: `tests/test_cauldron_grid.py`

**Interfaces:**
- Produces: `coach_grid(play_date, week_start, season)` (Cycle→Week; buttons first; grid inside a hidden wrapper `cauldron-grid-wrap`; no Recompute); `_grid_rows` includes a `captain` cell (bool); `save_grid(..., cycle_id)` calls `set_captain` for the row marked captain.

- [ ] **Step 1: Failing tests** — assert `coach_grid(...)` string contains `cauldron-grid-wrap` and does NOT contain `cauldron-recompute`; the wrapper's style has `display: none`; a `Captain` column exists. `save_grid` with a row `{"player_id": 2, "captain": True, ...}` calls `cauldron.set_captain(2, cycle_id)` (monkeypatch to record).

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement**
  - Add a `{"name": "Captain", "id": "captain", "editable": True, "presentation": "dropdown"}` column with options Yes/No (or a boolean checkbox column). `_grid_rows` sets `row["captain"] = bool(is_captain)` from `read_teams`.
  - Wrap the grid: `html.Div(grid, id="cauldron-grid-wrap", style={"display": "none", "padding": "0 16px"})`.
  - Layout order: `html.Div([buttons, filters, grid_wrap], ...)` — buttons FIRST.
  - Remove `recompute` button; `buttons = shell.edit_save_buttons("cauldron-edit", "cauldron-save", "cauldron-save-status")`.
  - `save_grid`: after team upsert, if the row's `captain` is truthy, `cauldron.set_captain(pid, cycle_id, updated_by)`. Add `"captain"` to `_NON_METRIC_KEYS`.

- [ ] **Step 4: Run — expect PASS.** Run `tests/test_cauldron_grid.py -q`.

- [ ] **Step 5: Commit** `feat(cauldron-grid): captain control, top buttons, hide-until-edit, drop Recompute`

---

### Task 4: Cauldron layout + callbacks — Week selector, week-bounded scoreboard, show/hide grid

**Files:**
- Modify: `app/dashboards/cauldron/layout.py` (`serve_layout`, week default, week-bounded scoreboard)
- Modify: `app/dashboards/cauldron/callbacks.py` (`_refresh` week-bounded; `_on_week` replaces `_on_date_or_cycle` cycle input; `_on_edit` shows wrapper; `_on_save` hides wrapper; remove `_on_recompute`)
- Test: `tests/test_cauldron_dash.py`

**Interfaces:**
- Consumes: `grid.coach_grid(play_date, week_start, season)`, `cauldron.read_daily(start, end)`, `velo_board.week_start_for`.
- Produces: `cauldron-week` (DatePickerSingle, id) drives the scoreboard; scoreboard = `scoreboard_view(read_daily(start=week_start, end=week_end), ...)`.

- [ ] **Step 1: Failing tests** — `serve_layout` (coach) string contains `cauldron-week` and not `cauldron-cycle`; the scoreboard callback is wired to `cauldron-week`; `_on_edit` returns a visible style for `cauldron-grid-wrap`; `_on_save` returns a hidden style.

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement**
  - `_week_bounds(week_start)` helper: `end = (date.fromisoformat(week_start) + timedelta(days=6)).isoformat()`.
  - `serve_layout`: compute `week = velo_board.week_start_for(today-clamped-into-season)` (reuse velo's `_default_week` logic or import it); pass `week` to `coach_grid`; scoreboard uses `read_daily(start=week, end=week_end)`.
  - `_refresh(play_date, week_start, cycle_id)`: grid rows for `play_date`; scoreboard from week-bounded daily.
  - Callbacks:
    - `_on_week` (Input `cauldron-week.date`, plus `cauldron-date.date`) → refresh.
    - `_on_edit` → also Output `cauldron-grid-wrap.style` = visible (`{"display":"block","padding":"0 16px"}`) + editable True.
    - `_on_save` → Output `cauldron-grid-wrap.style` hidden + editable False + persist.
    - Delete `_on_recompute`.
  - Cycle stays internal (`cycle = f"{season}-c1"`) for team reads/writes; not a visible control.

- [ ] **Step 4: Run — expect PASS.** Run `tests/test_cauldron_dash.py -q`.

- [ ] **Step 5: Commit** `feat(cauldron): weekly scoreboard + Week selector + show/hide grid`

---

### Task 5: Velo board — top buttons + hide-until-edit

**Files:**
- Modify: `app/dashboards/velo_board/grid.py` (`coach_grid`: buttons first, grid wrapper `velo-grid-wrap` hidden)
- Modify: `app/dashboards/velo_board/callbacks.py` (`_on_edit` shows wrapper; `_on_save` hides wrapper)
- Test: `tests/test_velo_board_grid.py`, `tests/test_velo_board_dash.py`

**Interfaces:**
- Produces: `velo-grid-wrap` hidden wrapper; Edit shows + unlocks, Save hides + re-locks.

- [ ] **Step 1: Failing tests** — `coach_grid(...)` string contains `velo-grid-wrap`; wrapper style `display: none`; buttons rendered before the grid; `_on_edit` returns a visible wrapper style, `_on_save` hidden.

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement**
  - Wrap grid: `html.Div(grid, id="velo-grid-wrap", style={"display":"none","padding":"0 16px"})`.
  - Layout order: `html.Div([buttons, filters, grid_wrap], ...)`.
  - Callbacks `_on_edit`/`_on_save`: add Output `velo-grid-wrap.style` (visible/hidden) alongside the existing editable toggle.

- [ ] **Step 4: Run — expect PASS.** Run `tests/test_velo_board_grid.py tests/test_velo_board_dash.py -q`.

- [ ] **Step 5: Commit** `feat(velo-board): top buttons + hide-until-edit grid`

---

### Task 6: Full regression, live verify, previews

- [ ] **Step 1:** Run the touched suites: `pytest tests/test_cauldron.py tests/test_cauldron_visual.py tests/test_cauldron_grid.py tests/test_cauldron_dash.py tests/test_velo_board_grid.py tests/test_velo_board_dash.py tests/test_velo_board.py tests/test_warmup.py -q`. Then the full suite minus `test_precalc` in the background.
- [ ] **Step 2:** Restart the dev server; confirm `/dash/cauldron/` and `/dash/velo_board/` serve (302 to login) with no boot error.
- [ ] **Step 3:** Render a faithful preview PNG of the dark scoreboard with a captain (★, first) to eyeball readability.
- [ ] **Step 4:** Commit any preview/verification notes if needed.

---

## Self-Review

- **Spec coverage:** weekly model (Task 4), shared edit UX both boards (Tasks 3/5), captain (Tasks 1/2/3), readability (Task 2), speed via cache + weekly bound (Tasks 1/4). All covered.
- **Placeholders:** none — each task has concrete signatures, SQL, and test assertions.
- **Type consistency:** `set_captain(player_id, cycle_id, updated_by)`, `read_daily(..., start, end)`, `coach_grid(play_date, week_start, season)`, `cauldron-grid-wrap` / `velo-grid-wrap` ids consistent across tasks.
