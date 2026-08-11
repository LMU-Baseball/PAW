# Top Gun Velo Board Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A coach-editable pitcher-velo grid + a player-facing "Top Gun" heat leaderboard, backed by a new RDS MySQL table, auto-populated from Trackman.

**Architecture:** New `app/data/velo_board.py` (storage + auto-population) and a new Dash dashboard `app/dashboards/velo_board/` mounted at `/dash/velo_board/`. `serve_layout` branches on `current_user.is_coach`: coaches get the editable grid + Save-to-RDS; everyone gets the read-only leaderboard. Storage mirrors `precalc.py` (CREATE TABLE IF NOT EXISTS + `ON DUPLICATE KEY UPDATE`). Velo auto-fills from `_pitcher_velo_appearances` (games) + bullpen velo, keyed on raw `trackman_id`.

**Tech Stack:** Python, Dash/Plotly, `dash_table.DataTable` (first `editable=True` use in the repo), pandas, SQLAlchemy Core (`app.db.get_engine`/`query_df`), matplotlib not needed (leaderboard is HTML/Dash), inline SVG.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-10-top-gun-velo-board-design.md`.
- Locked: auto-populate day one; velo source = games (with opponent) + bullpen fallback; coach columns = Velo Goal + Assessment (coach may override auto cells); weekly stored snapshots; coach edits / player views; storage = new RDS table `velo_board_entries`.
- Velo = Fastball/Sinker `RelSpeed`. Pitcher id = raw `GAMES.PitcherId`/`BULLPEN.PitcherId` == `User.trackman_id`.
- Follow existing patterns: Dash mount (`app/dashboards/bullpen/index.py`), role read (`current_user.is_coach` in `serve_layout`), RDS DDL/upsert (`app/data/precalc.py`), brand shell (`app/dashboards/shell.py` `index_string()`/`header()`, `CRIMSON="#9A0021"`), hub card (`app/templates/main/pitching_hub.html`).
- LMU colors: crimson `#8C1D40`/`#9A0021`, blue `#2864A8`. Top Gun header = inline SVG, recolored to LMU (no external asset).
- Run tests in the FOREGROUND (env kills background bash ~5min); `PYTHONIOENCODING=utf-8 python -m pytest ...`.
- Commit per task. Do NOT push/merge (user reviews). Branch: `feat/velo-board`.

---

### Task 1: `velo_board_entries` storage layer

**Files:**
- Create: `app/data/velo_board.py`
- Test: `tests/data/test_velo_board.py`

**Interfaces:**
- Produces: `ensure_tables(engine=None)`; `upsert_entries(rows: list[dict], updated_by=None) -> None`; `read_entries(season_label, week_start=None) -> pd.DataFrame`; table `velo_board_entries` PK `(pitcher_id, season_label, week_start)` with cols `pitcher_id BIGINT, pitcher_name VARCHAR(128), season_label VARCHAR(32), week_start VARCHAR(10), velo_avg FLOAT, velo_max FLOAT, velo_goal FLOAT, assessment FLOAT, max_pr FLOAT, updated_by INT, updated_at DATETIME`.

- [ ] **Step 1: Failing test** — ensure_tables is idempotent; upsert inserts then updates in place.

```python
def test_upsert_inserts_then_updates():
    from app.data import velo_board as V
    V.ensure_tables()
    row = {"pitcher_id": 999999001, "pitcher_name": "Test, Guy",
           "season_label": "2025/2026", "week_start": "2026-03-02",
           "velo_avg": 90.1, "velo_max": 93.0, "velo_goal": 95.0,
           "assessment": 91.0, "max_pr": 93.0}
    V.upsert_entries([row], updated_by=1)
    got = V.read_entries("2025/2026", "2026-03-02")
    r = got[got["pitcher_id"] == 999999001]
    assert len(r) == 1 and float(r.iloc[0]["velo_goal"]) == 95.0
    row["velo_goal"] = 96.0
    V.upsert_entries([row], updated_by=1)          # same PK -> update, not dup
    got2 = V.read_entries("2025/2026", "2026-03-02")
    r2 = got2[got2["pitcher_id"] == 999999001]
    assert len(r2) == 1 and float(r2.iloc[0]["velo_goal"]) == 96.0
    # cleanup
    from app.db import get_engine
    from sqlalchemy import text
    with get_engine().begin() as c:
        c.execute(text("DELETE FROM velo_board_entries WHERE pitcher_id=999999001"))
```

- [ ] **Step 2: Verify failure** — module/table absent.

- [ ] **Step 3: Implement.** Mirror `precalc.ensure_tables` (CREATE TABLE IF NOT EXISTS with the PK above; no migration needed for a brand-new table). `upsert_entries`: `with get_engine().begin() as conn:` execute an `INSERT ... ON DUPLICATE KEY UPDATE velo_avg=VALUES(velo_avg), ... updated_at=VALUES(updated_at)` for each row (call `ensure_tables()` first). `read_entries`: `query_df` filtered by season_label (+ week_start if given). Use `app.db.get_engine`/`query_df`.

- [ ] **Step 4: Run** — `pytest tests/data/test_velo_board.py -k upsert -v` → PASS.

- [ ] **Step 5: Commit** — `git commit -am "feat(velo-board): velo_board_entries RDS table + upsert/read"`.

---

### Task 2: Auto-population — weekly velo + max PR + change

**Files:**
- Modify: `app/data/velo_board.py`
- Test: `tests/data/test_velo_board.py`

**Interfaces:**
- Consumes: `pitching_caps._pitcher_velo_appearances`, `pitching_caps.lmu_pitchers`, `bullpen.trend_by_session`/session velo, `seasons`.
- Produces: `week_start_for(date) -> str` (Monday, ISO); `weekly_velo(pitcher_id, week_start) -> {"velo_avg","velo_max"}` (games+bullpens in `[week_start, +6d]`, None if no pitches); `running_max_pr(pitcher_id, upto_week=None) -> float|None`; `grid_rows(season_label, week_start) -> pd.DataFrame` (one row per rostered pitcher: auto `velo_avg`/`velo_max`/`max_pr` + stored `velo_goal`/`assessment` if present + computed `change_avg`/`change_max` vs the pitcher's previous stored week).

- [ ] **Step 1: Failing test.**

```python
def test_week_start_is_monday():
    from app.data.velo_board import week_start_for
    assert week_start_for("2026-03-04") == "2026-03-02"   # Wed -> Mon

def test_grid_rows_prefills_auto_velo_for_roster():
    from app.data import velo_board as V, seasons
    season = seasons.current_season()
    # a week inside the season that has data; use the season end week
    import datetime as d
    _, e = seasons.season_bounds(season)
    wk = V.week_start_for(e)
    df = V.grid_rows(season, wk)
    assert set(["pitcher_id","pitcher_name","velo_avg","velo_max","velo_goal",
                "assessment","max_pr","change_avg","change_max"]).issubset(df.columns)
    assert len(df) > 0   # roster present
```

- [ ] **Step 2: Verify failure** — functions absent.

- [ ] **Step 3: Implement.**
  - `week_start_for`: `date.fromisoformat(str(d)[:10])`; subtract `weekday()` days; return ISO.
  - `weekly_velo`: union Fastball/Sinker RelSpeed from GAMES (query PitcherId sibling union in `[week_start, +6]`) and BULLPEN (same window); `velo_avg=mean`, `velo_max=max`; None if empty. Reuse the sibling-id + team clauses already in `pitching_caps`/`bullpen` where practical (a direct windowed query is fine).
  - `running_max_pr`: max of stored `velo_max` (`read_entries`) unioned with live `weekly_velo` history up to `upto_week` — simplest correct version: max over the pitcher's all-time Fastball/Sinker RelSpeed from GAMES+BULLPEN up to the week end.
  - `grid_rows`: roster from `lmu_pitchers(season)`; for each pitcher compute `weekly_velo(pid, week_start)` + `running_max_pr`; merge any stored row's `velo_goal`/`assessment`; `change_avg`/`change_max` = this week's auto velo minus the pitcher's previous stored week's velo (via `read_entries(season)` sorted by week_start).

- [ ] **Step 4: Run** — `pytest tests/data/test_velo_board.py -k "week_start or grid_rows" -v` → PASS.

- [ ] **Step 5: Commit** — `git commit -am "feat(velo-board): weekly velo auto-population + max PR + change"`.

---

### Task 3: Player leaderboard data

**Files:**
- Modify: `app/data/velo_board.py`
- Test: `tests/data/test_velo_board.py`

**Interfaces:**
- Produces: `leaderboard(season_label) -> pd.DataFrame` — one row per rostered pitcher, sorted by `season_max` desc, cols: `pitcher_name, season_max, season_max_date, season_avg, last_velo, last_date, versus, trend` (`trend` = signed float, last-appearance `velo_change`; NaN if unknown).

- [ ] **Step 1: Failing test.**

```python
def test_leaderboard_sorted_and_has_opponent_for_games():
    from app.data import velo_board as V, seasons
    lb = V.leaderboard(seasons.current_season())
    assert list(lb.columns)[:4] == ["pitcher_name","season_max","season_max_date","season_avg"]
    # sorted desc by season_max (nulls last)
    vals = lb["season_max"].dropna().tolist()
    assert vals == sorted(vals, reverse=True)
```

- [ ] **Step 2: Verify failure** — function absent.

- [ ] **Step 3: Implement.** For each rostered pitcher (`lmu_pitchers(season)`): `season_max`/`season_avg` over the season's Fastball/Sinker RelSpeed (games+bullpens); `season_max_date` = date of that max; last **game** appearance from `_pitcher_velo_appearances` (newest in season) → `last_velo`=avg, `last_date`, `versus` = the non-LMU team (`home_team_name` if LMU is away else `away_team_name`; LMU HomeTeamForeignID 78 — derive opponent by "the team name that isn't LMU's"); if no game this season, last bullpen velo with `versus` blank. `trend` = `velo_trend(pid)`'s last `velo_change`. Sort by `season_max` desc, NaN last.

- [ ] **Step 4: Run** — `pytest tests/data/test_velo_board.py -k leaderboard -v` → PASS.

- [ ] **Step 5: Commit** — `git commit -am "feat(velo-board): player leaderboard data (season max/avg, last outing, trend)"`.

---

### Task 4: Top Gun visual — inline-SVG header + heat leaderboard

**Files:**
- Create: `app/dashboards/velo_board/__init__.py`, `app/dashboards/velo_board/visual.py`
- Test: `tests/dashboards/test_velo_board_visual.py`

**Interfaces:**
- Consumes: `velo_board.leaderboard`.
- Produces: `top_gun_header() -> dash html/​svg component` (LMU-recolored Top Gun wings + "COMPETE EVERYDAY"); `leaderboard_view(lb_df) -> html.Div` (ranked table, crimson→blue heat gradient down the rows, columns Pitcher/Season Max/Max Date/Season Avg/Last Outing/Date/Versus/Trend with ▲/▼).

- [ ] **Step 1: Failing test.**

```python
def test_leaderboard_view_renders_rows_and_header():
    import pandas as pd
    from app.dashboards.velo_board import visual as V
    lb = pd.DataFrame([
        {"pitcher_name":"A, B","season_max":95.8,"season_max_date":"2026-03-15",
         "season_avg":92.8,"last_velo":93.0,"last_date":"2026-03-21","versus":"Portland","trend":-0.5},
        {"pitcher_name":"C, D","season_max":90.0,"season_max_date":"2026-02-10",
         "season_avg":87.0,"last_velo":85.3,"last_date":"2026-03-03","versus":"UCSB","trend":2.3},
    ])
    view = V.leaderboard_view(lb)
    s = str(view)
    assert "TOP GUN" in str(V.top_gun_header())
    assert "A, B" in s and "Portland" in s
```

- [ ] **Step 2: Verify failure** — module absent.

- [ ] **Step 3: Implement.** `top_gun_header`: inline `<svg>` (via `dash.html` / `dash_svg` if available, else an `html.Div` wrapping an SVG string in `dangerously_allow_html`-free way — simplest: build with `dash.html` elements, or embed the SVG as a data-URI `html.Img`). Recolor the Top Gun wings/text to LMU crimson `#8C1D40` + blue `#2864A8`, subtitle "COMPETE EVERYDAY," title "TOP GUN." `leaderboard_view`: an `html.Table` (or `dash_table.DataTable` read-only) ranked by season_max; per-row background interpolated crimson→blue by rank (heat gradient); Trend cell shows ▲(green/blue)/▼(red) + delta; format velos to 1 decimal, dates as "M/D". Use brand tokens from `shell.py`.

- [ ] **Step 4: Run** — `pytest tests/dashboards/test_velo_board_visual.py -v` → PASS.

- [ ] **Step 5: Commit** — `git commit -am "feat(velo-board): Top Gun inline-SVG header + heat leaderboard visual"`.

---

### Task 5: Coach editable grid + save-to-RDS

**Files:**
- Create: `app/dashboards/velo_board/grid.py`
- Test: `tests/dashboards/test_velo_board_grid.py`

**Interfaces:**
- Consumes: `velo_board.grid_rows`, `velo_board.upsert_entries`.
- Produces: `coach_grid(season_label, week_start) -> html.Div` — an editable `dash_table.DataTable` (id `velo-grid`) with `velo_goal`/`assessment` editable (auto columns shown, overridable), a Season dropdown (`velo-season`), a Week picker (`velo-week`), and a **Save week** button (`velo-save`). `save_rows(grid_data, season, week_start, updated_by) -> None` (thin wrapper that maps grid rows → entry dicts → `upsert_entries`).

- [ ] **Step 1: Failing test.**

```python
def test_coach_grid_is_editable_and_save_maps_rows(monkeypatch):
    from app.dashboards.velo_board import grid as G
    comp = G.coach_grid("2025/2026", "2026-03-02")
    assert "velo-grid" in str(comp) and "velo-save" in str(comp)
    captured = {}
    monkeypatch.setattr("app.data.velo_board.upsert_entries",
                        lambda rows, updated_by=None: captured.setdefault("rows", rows))
    G.save_rows([{"pitcher_id": 823008, "pitcher_name":"Behrens, Adam",
                  "velo_avg":90.0,"velo_max":93.0,"velo_goal":95.0,"assessment":91.0,
                  "max_pr":93.0}], "2025/2026", "2026-03-02", updated_by=1)
    assert captured["rows"][0]["season_label"] == "2025/2026"
    assert captured["rows"][0]["week_start"] == "2026-03-02"
```

- [ ] **Step 2: Verify failure** — module absent.

- [ ] **Step 3: Implement.** `coach_grid`: build the DataTable from `grid_rows(season, week_start)` with `editable=True`; mark only `velo_goal`/`assessment` columns `editable` (others display-only) — or allow all editable per the override requirement; conditional highlight for new-PR (velo_max == max_pr). Season dropdown = `seasons.available_seasons()`, Week picker default = current week. `save_rows`: attach `season_label`/`week_start`/`updated_by`, call `upsert_entries`.

- [ ] **Step 4: Run** — `pytest tests/dashboards/test_velo_board_grid.py -v` → PASS.

- [ ] **Step 5: Commit** — `git commit -am "feat(velo-board): coach editable grid + save-to-RDS mapping"`.

---

### Task 6: Dashboard assembly, registration, auth, hub card

**Files:**
- Create: `app/dashboards/velo_board/index.py`, `layout.py`, `callbacks.py`
- Modify: `app/dashboards/__init__.py` (register), `app/templates/main/pitching_hub.html` (card)
- Test: `tests/dashboards/test_velo_board_dash.py`

**Interfaces:**
- Consumes: everything above; `shell.index_string()`/`header()`.
- Produces: `build_velo_board_dash(server) -> Dash` at `/dash/velo_board/`; `serve_layout()` (role-branched); `register_callbacks(dash_app)`.

- [ ] **Step 1: Failing test.**

```python
def test_velo_board_route_registered_and_role_branches():
    from app import create_app
    app = create_app()
    # route mounted + login-protected
    rv = app.test_client().get("/dash/velo_board/")
    assert rv.status_code in (302, 200)   # redirect to login when anon
    # serve_layout renders leaderboard for a player, grid only for coach
    from app.dashboards.velo_board import layout
    # (render under a faked current_user in the test app context — mirror
    #  tests/test_bullpen_dash.py's login/render approach)
```

- [ ] **Step 2: Verify failure** — dashboard absent / not registered.

- [ ] **Step 3: Implement.**
  - `index.py`: `build_velo_board_dash(server)` → `Dash(__name__, server=server, url_base_pathname="/dash/velo_board/", suppress_callback_exceptions=True)`; `index_string()`; `layout.serve_layout`; `callbacks.register_callbacks`.
  - `layout.serve_layout()`: auth guard; `is_coach = current_user.is_coach`; always render `header(back_href="/pitching")` + `visual.top_gun_header()` + `visual.leaderboard_view(velo_board.leaderboard(season))`; if `is_coach`, ALSO render `grid.coach_grid(season, week)` above/below the visual.
  - `callbacks.register_callbacks`: season/week change → refresh grid + leaderboard; `velo-save` `n_clicks` + `State("velo-grid","data")` → `grid.save_rows(...)` (coach-gated: re-check `current_user.is_coach` inside the callback; ignore if not coach) → re-read grid.
  - Register in `app/dashboards/__init__.py` `register_dashboards`.
  - Add hub card to `pitching_hub.html`: `{"title":"Velo Board","desc":"Top Gun pitcher velocity leaderboard.","href":"/dash/velo_board/"}`.

- [ ] **Step 4: Run** — `pytest tests/dashboards/test_velo_board_dash.py -v` and the full velo-board tests → PASS. Also assert a player render contains NO editable grid id and a coach render DOES (mirror `tests/test_bullpen_dash.py` login pattern).

- [ ] **Step 5: Commit** — `git commit -am "feat(velo-board): mount dashboard, role-branched layout, save callback, hub card"`.

---

## Final verification

- [ ] `PYTHONIOENCODING=utf-8 pytest tests/ -k velo_board -v` green.
- [ ] Live smoke: `/dash/velo_board/` as coach (grid editable, Save persists to RDS, leaderboard updates); as player (leaderboard only, no grid); hub card links correctly.
- [ ] Do NOT push/merge — hand back for review.

## Self-review notes

- Spec coverage: storage (T1), auto-population incl. both sources + weekly + PR + change (T2), leaderboard/opponent/trend (T3), Top Gun visual + inline SVG (T4), coach grid + Goal/Assessment + save-to-RDS (T5), assembly + role gate + registration + hub card (T6).
- `velo_board_entries` PK `(pitcher_id, season_label, week_start)` and column names are consistent across T1/T2/T5.
- Coach-only write is enforced twice: layout only renders the grid for coaches, AND the save callback re-checks `is_coach`.
