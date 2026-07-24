# Global Date-Range Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a calendar date-range picker to all four stats dashboards; on the game dashboards (Pitching/Catching/Hitting) the range scopes the game dropdown and adds an opt-in "All games in range" option that pools those games.

**Architecture:** A shared pure helper `app/dashboards/date_range.py` provides the picker component, the game-options builder (with the `ALL_IN_RANGE` sentinel), and the range scoreboard text. Each game dashboard's data layer gains a date-bounded `games_for_*` variant plus a pooled `range_pitches_for` loader (reusing the existing sibling-id union); its layout/callbacks gain the picker, a range→games callback, and an aggregate branch in the data-load + scoreboard. Practice wires the calendar into its existing `start`/`end` filter, keeping presets.

**Tech Stack:** Python, Flask, Dash (`dcc.DatePickerRange`), Plotly, pandas, SQLAlchemy; pytest.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-07-23-global-date-range-filter-design.md`. Base branch `feat/dashboards-date-range` (off `feat/catching-dashboard-rebuild`).
- **Sentinel:** `ALL_IN_RANGE = "__all_in_range__"` (defined once in `app/dashboards/date_range.py`; import it — never re-literal).
- **Default:** range = the selected player's full season span; game dropdown defaults to the **most recent single game**. Aggregation is **opt-in** only via the "All games in range" entry.
- **No caching** — single indexed query per selection. Do not add a cache layer.
- **Backward compatible:** existing single-game functions keep working; new date params are optional/additive; existing callers unchanged.
- **No DB in tabs/charts/`date_range.py`** — pure `df → components`. DB only in data layer + selectors/callbacks.
- **Warehouse:** `fact_tm_game_pitch` / `dim_tm_game`; LMU pitcher/catcher team `LOY_LIO`, batter team `LOY_LIO`, `LMU_TEAM_ID = 78`. Sibling-id union helpers already exist per module.
- **Brand:** Teko font, crimson `#9A0021`, banner `rgba(154,0,33,0.82)`.
- **Tests:** `python -m pytest -q`; Windows headless launches prefix `PYTHONIOENCODING=utf-8`. Live-DB tests follow each module's existing unguarded convention.

---

### Task 1: Shared `date_range` helper

**Files:**
- Create: `app/dashboards/date_range.py`
- Test: `tests/test_date_range.py`

**Interfaces:**
- Produces:
  - `ALL_IN_RANGE: str`
  - `date_picker(id_prefix: str, start, end, min_date=None, max_date=None) -> dcc.DatePickerRange` (id `f"{id_prefix}-daterange"`)
  - `game_options(games_df: pd.DataFrame) -> list[dict]` — prepends the sentinel option; `[]` when empty
  - `range_scoreboard_text(games_df: pd.DataFrame, start, end) -> str`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_date_range.py`:

```python
import pandas as pd
from app.dashboards import date_range as dr


def _games():
    return pd.DataFrame([
        {"game_id": 10, "GameLabel": "2026-04-02 vs USD"},
        {"game_id": 9, "GameLabel": "2026-04-01 @ ASU"},
    ])


def test_game_options_prepends_sentinel():
    opts = dr.game_options(_games())
    assert opts[0]["value"] == dr.ALL_IN_RANGE
    assert opts[0]["label"] == "All games in range (2)"
    assert [o["value"] for o in opts[1:]] == [10, 9]


def test_game_options_empty():
    assert dr.game_options(pd.DataFrame()) == []


def test_range_scoreboard_text():
    assert dr.range_scoreboard_text(_games(), "2026-04-01", "2026-04-02") == \
        "2026-04-01 – 2026-04-02 · 2 games"
    assert dr.range_scoreboard_text(pd.DataFrame(), "2026-04-01", "2026-04-02") == \
        "2026-04-01 – 2026-04-02 · 0 games"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_date_range.py -v`
Expected: FAIL (`ModuleNotFoundError: app.dashboards.date_range`).

- [ ] **Step 3: Create `app/dashboards/date_range.py`**

```python
"""Shared date-range selection helpers for the stats dashboards (pure)."""
from __future__ import annotations

import pandas as pd
from dash import dcc

ALL_IN_RANGE = "__all_in_range__"


def date_picker(id_prefix: str, start, end, min_date=None, max_date=None):
    """A styled calendar range picker. Component id = f'{id_prefix}-daterange'."""
    return dcc.DatePickerRange(
        id=f"{id_prefix}-daterange",
        start_date=start,
        end_date=end,
        min_date_allowed=min_date,
        max_date_allowed=max_date,
        display_format="YYYY-MM-DD",
        first_day_of_week=1,
        style={"backgroundColor": "white", "borderRadius": "6px"},
    )


def game_options(games_df: pd.DataFrame) -> list[dict]:
    """Dropdown options for in-range games, prepended with the aggregate sentinel.
    Empty df -> [] (caller shows an empty state)."""
    if games_df is None or games_df.empty:
        return []
    opts = [{"label": f"All games in range ({len(games_df)})", "value": ALL_IN_RANGE}]
    for r in games_df.itertuples():
        opts.append({"label": str(r.GameLabel), "value": int(r.game_id)})
    return opts


def range_scoreboard_text(games_df: pd.DataFrame, start, end) -> str:
    n = 0 if games_df is None or games_df.empty else len(games_df)
    return f"{start} – {end} · {n} games"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_date_range.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/date_range.py tests/test_date_range.py
git commit -m "feat(dashboards): shared date-range helper (picker, game options, sentinel)"
```

---

### Task 2: Pitching data layer — date-bounded games + pooled loader

**Files:**
- Modify: `app/data/pitching.py` (`games_for_pitcher`; add `range_pitches_for`)
- Test: `tests/test_pitching.py` (append)

**Interfaces:**
- Consumes: `_sibling_pitcher_ids`, `LMU_TEAM_ID`, `query_df` (existing).
- Produces:
  - `games_for_pitcher(pitcher_id, start=None, end=None) -> df[game_id, game_date, GameLabel]` (adds `game_date`; optional date filter)
  - `range_pitches_for(pitcher_id, start, end) -> df` (same columns as `game_pitches_for`; unions in-range games)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pitching.py` (live-DB, matching the file's existing convention — it already queries the warehouse):

```python
def test_games_for_pitcher_date_filter():
    from app.data import pitching as P
    pit = P.wh_lmu_pitchers()
    if pit.empty:
        import pytest; pytest.skip("no LMU pitchers")
    pid = int(pit.iloc[0]["PitcherId"])
    allg = P.games_for_pitcher(pid)
    assert {"game_id", "game_date", "GameLabel"} <= set(allg.columns)
    if len(allg) >= 2:
        lo = str(allg["game_date"].min())
        hi = str(allg["game_date"].max())
        bounded = P.games_for_pitcher(pid, start=lo, end=hi)
        assert len(bounded) == len(allg)  # full span == all games
        # narrow to only the most recent game's date
        recent = str(allg["game_date"].max())
        narrowed = P.games_for_pitcher(pid, start=recent, end=recent)
        assert len(narrowed) >= 1 and len(narrowed) <= len(allg)


def test_range_pitches_for_unions_range():
    from app.data import pitching as P
    pit = P.wh_lmu_pitchers()
    if pit.empty:
        import pytest; pytest.skip("no LMU pitchers")
    pid = int(pit.iloc[0]["PitcherId"])
    allg = P.games_for_pitcher(pid)
    if allg.empty:
        import pytest; pytest.skip("no games")
    lo, hi = str(allg["game_date"].min()), str(allg["game_date"].max())
    pooled = P.range_pitches_for(pid, lo, hi)
    # pooled equals the sum of single-game loads across the range
    single_total = sum(len(P.game_pitches_for(int(g), pid)) for g in allg["game_id"])
    assert len(pooled) == single_total
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_pitching.py -k "date_filter or range_pitches" -v`
Expected: FAIL (`game_date` not in columns / `range_pitches_for` missing).

- [ ] **Step 3: Implement in `app/data/pitching.py`**

Replace `games_for_pitcher` with the date-aware version (keep the body, add the `game_date` output column + optional date clause):

```python
def games_for_pitcher(pitcher_id: int, start=None, end=None) -> pd.DataFrame:
    """A pitcher's outings, newest first. GameLabel = 'YYYY-MM-DD vs/@ OPP'.
    Optional start/end (inclusive) bound game_date."""
    ids = _sibling_pitcher_ids(pitcher_id)
    marks = ", ".join(f":id{i}" for i in range(len(ids)))
    params = {f"id{i}": v for i, v in enumerate(ids)}
    params["lmu"] = LMU_TEAM_ID
    date_clause = ""
    if start is not None and end is not None:
        date_clause = " AND g.game_date BETWEEN :start AND :end"
        params["start"] = str(start)
        params["end"] = str(end)
    df = query_df(
        f"""
        SELECT DISTINCT g.game_id, g.game_date,
               ht.team_name AS home_team, at.team_name AS away_team,
               g.home_team_id
          FROM fact_tm_game_pitch f
          JOIN dim_tm_game g ON g.game_id = f.game_id
          LEFT JOIN tm_team ht ON ht.team_id = g.home_team_id
          LEFT JOIN tm_team at ON at.team_id = g.away_team_id
         WHERE f.pitcher_id IN ({marks}){date_clause}
         ORDER BY g.game_date DESC, g.game_id DESC
        """,
        params,
    )
    if df.empty:
        return pd.DataFrame(columns=["game_id", "game_date", "GameLabel"])
    lmu_home = df["home_team_id"] == LMU_TEAM_ID
    opp = df["away_team"].where(lmu_home, df["home_team"])
    loc = pd.Series("vs", index=df.index).where(lmu_home, "@")
    df["GameLabel"] = (df["game_date"].astype(str) + " " + loc + " " + opp.fillna("?"))
    return df[["game_id", "game_date", "GameLabel"]].reset_index(drop=True)
```

Add `range_pitches_for` next to `game_pitches_for`:

```python
def range_pitches_for(pitcher_id: int, start, end) -> pd.DataFrame:
    """All of a pitcher's pitches across in-range games (sibling-id union)."""
    ids = _sibling_pitcher_ids(pitcher_id)
    marks = ", ".join(f":id{i}" for i in range(len(ids)))
    params = {f"id{i}": v for i, v in enumerate(ids)}
    params["start"] = str(start)
    params["end"] = str(end)
    return query_df(
        f"""
        SELECT f.* FROM fact_tm_game_pitch f
          JOIN dim_tm_game g ON g.game_id = f.game_id
         WHERE f.pitcher_id IN ({marks})
           AND g.game_date BETWEEN :start AND :end
         ORDER BY f.game_id, f.pitch_no
        """,
        params,
    )
```

Note: `selectors.outing_options` and any existing `games_for_pitcher(pid)` callers keep working (they use `r.GameLabel`/`r.game_id`; the added `game_date` column is harmless).

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_pitching.py -k "date_filter or range_pitches" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/data/pitching.py tests/test_pitching.py
git commit -m "feat(pitching-data): date-bounded games_for_pitcher + range_pitches_for"
```

---

### Task 3: Pitching dashboard wiring (picker + range→games + aggregate branch)

**Files:**
- Modify: `app/dashboards/pitching/layout.py` (selector row + default range + scoreboard)
- Modify: `app/dashboards/pitching/callbacks.py` (range callback + aggregate load/scoreboard)
- Test: `tests/test_pitching_dash.py` (append)

**Interfaces:**
- Consumes: `date_range.date_picker`, `date_range.game_options`, `date_range.ALL_IN_RANGE`, `date_range.range_scoreboard_text`; `P.games_for_pitcher(pid,start,end)`, `P.range_pitches_for`, `P.game_pitches_for`, `P.game_context`.
- Component ids: existing `pitcher-dd`, `outing-dd`, `scoreboard`, `selection`, `game-data`; new `pit-daterange`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pitching_dash.py`:

```python
def test_pitching_aggregate_load_live():
    from app import create_app
    from config import Config
    from app.data import pitching as P
    from app.dashboards.date_range import ALL_IN_RANGE
    class T(Config):
        TESTING = True; SECRET_KEY = "t"; SQLALCHEMY_DATABASE_URI = "sqlite://"
    app = create_app(T)
    with app.app_context():
        pit = P.wh_lmu_pitchers()
        if pit.empty:
            import pytest; pytest.skip("no pitchers")
        pid = int(pit.iloc[0]["PitcherId"])
        g = P.games_for_pitcher(pid)
        if g.empty:
            import pytest; pytest.skip("no games")
        lo, hi = str(g["game_date"].min()), str(g["game_date"].max())
        pooled = P.range_pitches_for(pid, lo, hi)
        assert not pooled.empty
        # sentinel is what the callback routes on
        assert ALL_IN_RANGE == "__all_in_range__"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_pitching_dash.py -k aggregate_load -v`
Expected: FAIL (import of `range_pitches_for`/sentinel or assertion) until Task 2 present — if Task 2 done it may pass; then strengthen by asserting the layout/callbacks below. (If it already passes, proceed; the substantive checks are the wiring edits.)

- [ ] **Step 3: Edit `layout.py`**

Add imports at top:

```python
from app.dashboards import date_range as dr
```

In `serve_layout`, after computing `outings`/`default_game`, seed the range from the default pitcher's game span and build the selector row with the picker. Replace the `outings = selectors.outing_options(default_pitcher)` / `default_game = ...` lines and the `selector_row` block with:

```python
    games_df = P.games_for_pitcher(default_pitcher) if default_pitcher else None
    if games_df is not None and not games_df.empty:
        start_d = str(games_df["game_date"].min())
        end_d = str(games_df["game_date"].max())
        outings = dr.game_options(games_df)
        default_game = int(games_df.iloc[0]["game_id"])  # most recent single game
    else:
        start_d = end_d = None
        outings = []
        default_game = None

    selector_row = html.Div([
        html.Div([
            html.Label("Pitcher", style={"color": "white", "fontWeight": "bold"}),
            dcc.Dropdown(id="pitcher-dd", options=pitchers, value=default_pitcher,
                         clearable=False, disabled=not is_coach,
                         style={"minWidth": "220px"}),
        ]),
        html.Div([
            html.Label("Date range", style={"color": "white", "fontWeight": "bold"}),
            dr.date_picker("pit", start_d, end_d),
        ]),
        html.Div([
            html.Label("Outing", style={"color": "white", "fontWeight": "bold"}),
            dcc.Dropdown(id="outing-dd", options=outings, value=default_game,
                         clearable=False, style={"minWidth": "260px"}),
        ]),
        html.Div(id="scoreboard"),
    ], style={"display": "flex", "gap": "16px", "alignItems": "flex-end",
              "padding": "12px 16px", "backgroundColor": BANNER})
```

Add `P` import if not present (`from app.data import pitching as P`) — check the top of the file; `selectors` is imported, `P` may not be. Add it.

Update the initial `selection` store to include the range:

```python
        dcc.Store(id="selection", data={"pitcher_id": default_pitcher,
                                        "game_id": default_game,
                                        "start": start_d, "end": end_d}),
```

Update `scoreboard(game_id)` to accept the aggregate case. Change its signature to `scoreboard(game_id, start=None, end=None, games_df=None)` and, at the top:

```python
def scoreboard(game_id, start=None, end=None, games_df=None) -> html.Div:
    from app.dashboards import date_range as dr
    if game_id == dr.ALL_IN_RANGE:
        return html.Div(dr.range_scoreboard_text(games_df, start, end),
                        style={"color": "white", "fontWeight": "bold",
                               "fontSize": "20px", "alignSelf": "center"})
    if not game_id:
        return html.Div()
    # ... existing single-game body unchanged ...
```

- [ ] **Step 4: Edit `callbacks.py`**

Add import: `from app.dashboards import date_range as dr` and ensure `State`, `ctx` are imported from dash (State already is; add nothing if present).

Replace `_on_pitcher` (the outing-options callback) with two callbacks — one resets the range on pitcher change, one populates games from the range:

```python
    @dash_app.callback(
        Output("pit-daterange", "start_date"), Output("pit-daterange", "end_date"),
        Input("pitcher-dd", "value"), prevent_initial_call=True,
    )
    def _on_pitcher_range(pitcher_id):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        pid = selectors.resolve_pitcher(pitcher_id, is_coach=is_coach, own_trackman_id=own)
        g = P.games_for_pitcher(pid) if pid else None
        if g is None or g.empty:
            return None, None
        return str(g["game_date"].min()), str(g["game_date"].max())

    @dash_app.callback(
        Output("outing-dd", "options"), Output("outing-dd", "value"),
        Input("pit-daterange", "start_date"), Input("pit-daterange", "end_date"),
        State("pitcher-dd", "value"), prevent_initial_call=True,
    )
    def _on_range(start, end, pitcher_id):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        pid = selectors.resolve_pitcher(pitcher_id, is_coach=is_coach, own_trackman_id=own)
        if not pid or not start or not end:
            return [], None
        g = P.games_for_pitcher(pid, start=start, end=end)
        opts = dr.game_options(g)
        value = int(g.iloc[0]["game_id"]) if not g.empty else dr.ALL_IN_RANGE
        return opts, value
```

Ensure `P` is imported in callbacks.py (`from app.data import pitching as P`). Add if missing.

Update `_on_selection` to carry the range + aggregate scoreboard. Replace it with:

```python
    @dash_app.callback(
        Output("selection", "data"), Output("sidebar", "children"),
        Output("scoreboard", "children"),
        Input("pitcher-dd", "value"), Input("outing-dd", "value"),
        State("pit-daterange", "start_date"), State("pit-daterange", "end_date"),
    )
    def _on_selection(pitcher_id, game_id, start, end):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        pid = selectors.resolve_pitcher(pitcher_id, is_coach=is_coach, own_trackman_id=own)
        if game_id == dr.ALL_IN_RANGE:
            g = P.games_for_pitcher(pid, start=start, end=end) if pid else None
            sb = layout.scoreboard(dr.ALL_IN_RANGE, start, end, g)
        else:
            sb = layout.scoreboard(game_id)
        return ({"pitcher_id": pid, "game_id": game_id, "start": start, "end": end},
                layout.sidebar(pid), sb)
```

Update the data-load callback to branch on the sentinel:

```python
    @dash_app.callback(Output("game-data", "data"), Input("selection", "data"))
    def _on_load_data(sel):
        if not sel or sel.get("pitcher_id") is None:
            return None
        gid = sel.get("game_id")
        if gid == dr.ALL_IN_RANGE:
            if not sel.get("start") or not sel.get("end"):
                return None
            df = P.range_pitches_for(int(sel["pitcher_id"]), sel["start"], sel["end"])
        elif gid is None:
            return None
        else:
            df = P.game_pitches_for(int(gid), int(sel["pitcher_id"]))
        return None if df.empty else df.to_json(orient="split")
```

For the **Last Outings** tab (`_render_tab` `outings` branch calls `last_outings.render(sel.get("pitcher_id"), sel.get("game_id"), 5)`): when `game_id == ALL_IN_RANGE`, pass the most-recent in-range game as the anchor. Update that branch:

```python
        if tab == "outings":
            sel = sel or {}
            anchor = sel.get("game_id")
            if anchor == dr.ALL_IN_RANGE:
                g = P.games_for_pitcher(int(sel["pitcher_id"]),
                                        start=sel.get("start"), end=sel.get("end")) \
                    if sel.get("pitcher_id") else None
                anchor = int(g.iloc[0]["game_id"]) if g is not None and not g.empty else None
            return last_outings.render(sel.get("pitcher_id"), anchor, 5)
```

- [ ] **Step 5: Run tests + live smoke**

Run: `python -m pytest tests/test_pitching_dash.py -q` and `python -m pytest -q`
Expected: PASS (all). Then in-process smoke:

```bash
PYTHONIOENCODING=utf-8 python -c "
from app import create_app
from app.data import pitching as P
from app.dashboards.pitching import callbacks  # import ok
app=create_app()
with app.app_context():
    pid=int(P.wh_lmu_pitchers().iloc[0]['PitcherId'])
    g=P.games_for_pitcher(pid); lo,hi=str(g.game_date.min()),str(g.game_date.max())
    print('games', len(g), 'pooled', len(P.range_pitches_for(pid,lo,hi)))
"
```
Expected: prints game count + non-zero pooled count, no error.

- [ ] **Step 6: Commit**

```bash
git add app/dashboards/pitching/ tests/test_pitching_dash.py
git commit -m "feat(pitching-dash): date-range picker + All-games-in-range aggregate"
```

---

### Task 4: Catching data layer — date-bounded games + pooled loader

**Files:**
- Modify: `app/data/catching.py` (`games_for_catcher`; add `range_pitches_for`)
- Test: `tests/test_catching.py` (append; live-DB convention)

**Interfaces:**
- Consumes: `_sibling_catcher_ids`, `_in_clause`, `LMU_TEAM_ID`, `query_df` (existing).
- Produces:
  - `games_for_catcher(catcher_id, start=None, end=None) -> df[game_id, game_date, GameLabel]`
  - `range_pitches_for(catcher_id, start, end) -> df`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_catching.py`:

```python
def test_catching_games_date_filter_and_range():
    from app.data import catching as C
    cats = C.wh_lmu_catchers()
    if cats.empty:
        import pytest; pytest.skip("no catchers")
    cid = int(cats.iloc[0]["CatcherId"])
    allg = C.games_for_catcher(cid)
    assert {"game_id", "game_date", "GameLabel"} <= set(allg.columns)
    if allg.empty:
        import pytest; pytest.skip("no games")
    lo, hi = str(allg["game_date"].min()), str(allg["game_date"].max())
    assert len(C.games_for_catcher(cid, start=lo, end=hi)) == len(allg)
    pooled = C.range_pitches_for(cid, lo, hi)
    single = sum(len(C.game_pitches_for(int(g), cid)) for g in allg["game_id"])
    assert len(pooled) == single
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_catching.py -k "date_filter_and_range" -v`
Expected: FAIL (`game_date` missing / `range_pitches_for` missing).

- [ ] **Step 3: Implement in `app/data/catching.py`**

Replace `games_for_catcher` with the date-aware version (add `game_date` output + optional clause):

```python
def games_for_catcher(catcher_id: int, start=None, end=None) -> pd.DataFrame:
    """A catcher's games, newest first. GameLabel = 'YYYY-MM-DD vs/@ OPP'.
    Optional start/end (inclusive) bound game_date."""
    ids = _sibling_catcher_ids(catcher_id)
    marks, params = _in_clause(ids)
    params["lmu"] = LMU_TEAM_ID
    date_clause = ""
    if start is not None and end is not None:
        date_clause = " AND g.game_date BETWEEN :start AND :end"
        params["start"] = str(start)
        params["end"] = str(end)
    df = query_df(
        f"""
        SELECT DISTINCT g.game_id, g.game_date,
               ht.team_name AS home_team, at.team_name AS away_team,
               g.home_team_id
          FROM fact_tm_game_pitch f
          JOIN dim_tm_game g ON g.game_id = f.game_id
          LEFT JOIN tm_team ht ON ht.team_id = g.home_team_id
          LEFT JOIN tm_team at ON at.team_id = g.away_team_id
         WHERE f.catcher_id IN ({marks}){date_clause}
         ORDER BY g.game_date DESC, g.game_id DESC
        """,
        params,
    )
    if df.empty:
        return pd.DataFrame(columns=["game_id", "game_date", "GameLabel"])
    lmu_home = df["home_team_id"] == LMU_TEAM_ID
    opp = df["away_team"].where(lmu_home, df["home_team"])
    loc = pd.Series("vs", index=df.index).where(lmu_home, "@")
    df["GameLabel"] = (df["game_date"].astype(str) + " " + loc + " " + opp.fillna("?"))
    return df[["game_id", "game_date", "GameLabel"]].reset_index(drop=True)
```

Add `range_pitches_for` next to `game_pitches_for`:

```python
def range_pitches_for(catcher_id: int, start, end) -> pd.DataFrame:
    """All of a catcher's pitches across in-range games (sibling-id union)."""
    ids = _sibling_catcher_ids(catcher_id)
    marks, params = _in_clause(ids)
    params["start"] = str(start)
    params["end"] = str(end)
    return query_df(
        f"""
        SELECT f.* FROM fact_tm_game_pitch f
          JOIN dim_tm_game g ON g.game_id = f.game_id
         WHERE f.catcher_id IN ({marks})
           AND g.game_date BETWEEN :start AND :end
         ORDER BY f.game_id, f.pitch_no
        """,
        params,
    )
```

Note: `games_for_catcher` previously returned `[game_id, GameLabel]`; adding `game_date` is safe (selectors use `r.GameLabel`/`r.game_id`).

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_catching.py -k "date_filter_and_range" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/data/catching.py tests/test_catching.py
git commit -m "feat(catching-data): date-bounded games_for_catcher + range_pitches_for"
```

---

### Task 5: Catching dashboard wiring

**Files:**
- Modify: `app/dashboards/catching/layout.py`
- Modify: `app/dashboards/catching/callbacks.py`
- Test: `tests/test_catching_dash.py` (append)

**Interfaces:**
- Consumes: `date_range` helper; `C.games_for_catcher(cid,start,end)`, `C.range_pitches_for`, `C.game_pitches_for`, `C.game_context`.
- Component ids: existing `catcher-dd`, `game-dd`, `scoreboard`, `selection`, `game-data`; new `cat-daterange`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_catching_dash.py`:

```python
def test_catching_range_pooled_render_live(real_catcher):
    from app.data import catching as C
    from app.dashboards.catching.tabs import framing, static_framing, caught_stealing
    g = C.games_for_catcher(real_catcher)
    if g.empty:
        import pytest; pytest.skip("no games")
    lo, hi = str(g["game_date"].min()), str(g["game_date"].max())
    pooled = C.range_pitches_for(real_catcher, lo, hi)
    if pooled.empty:
        import pytest; pytest.skip("no pooled pitches")
    assert framing.render(pooled) is not None
    assert static_framing.render(pooled) is not None
    assert caught_stealing.render(pooled) is not None
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_catching_dash.py -k range_pooled -v`
Expected: FAIL (`range_pitches_for` missing) until Task 4; if Task 4 present, this checks pooled render — proceed to wiring.

- [ ] **Step 3: Edit `layout.py`**

Add `from app.dashboards import date_range as dr` at top (alongside the existing shell import). In `serve_layout`, replace the `games = selectors.game_options(default_catcher)` / `default_game = ...` lines and the `selector_row` block with:

```python
    games_df = C.games_for_catcher(default_catcher) if default_catcher else None
    if games_df is not None and not games_df.empty:
        start_d = str(games_df["game_date"].min())
        end_d = str(games_df["game_date"].max())
        games = dr.game_options(games_df)
        default_game = int(games_df.iloc[0]["game_id"])
    else:
        start_d = end_d = None
        games = []
        default_game = None

    selector_row = html.Div([
        html.Div([
            html.Label("Catcher", style={"color": "white", "fontWeight": "bold"}),
            dcc.Dropdown(id="catcher-dd", options=catchers, value=default_catcher,
                         clearable=False, disabled=not is_coach,
                         style={"minWidth": "220px"}),
        ]),
        html.Div([
            html.Label("Date range", style={"color": "white", "fontWeight": "bold"}),
            dr.date_picker("cat", start_d, end_d),
        ]),
        html.Div([
            html.Label("Game", style={"color": "white", "fontWeight": "bold"}),
            dcc.Dropdown(id="game-dd", options=games, value=default_game,
                         clearable=False, style={"minWidth": "260px"}),
        ]),
        html.Div(id="scoreboard"),
    ], style={"display": "flex", "gap": "16px", "alignItems": "flex-end",
              "padding": "12px 16px", "backgroundColor": BANNER})
```

Update the `selection` store initial data to include `"start": start_d, "end": end_d`.

Update `scoreboard(game_id)` to the aggregate-aware form (same shape as pitching Task 3):

```python
def scoreboard(game_id, start=None, end=None, games_df=None) -> html.Div:
    from app.dashboards import date_range as dr
    if game_id == dr.ALL_IN_RANGE:
        return html.Div(dr.range_scoreboard_text(games_df, start, end),
                        style={"color": "white", "fontWeight": "bold",
                               "fontSize": "20px", "alignSelf": "center"})
    if not game_id:
        return html.Div()
    # ... existing single-game body unchanged ...
```

- [ ] **Step 4: Edit `callbacks.py`**

Add `from app.dashboards import date_range as dr`; ensure `State` imported (it is, from Task 8 of the rebuild). Replace `_on_catcher` with the range pair:

```python
    @dash_app.callback(
        Output("cat-daterange", "start_date"), Output("cat-daterange", "end_date"),
        Input("catcher-dd", "value"), prevent_initial_call=True,
    )
    def _on_catcher_range(catcher_id):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        cid = selectors.resolve_catcher(catcher_id, is_coach=is_coach, own_trackman_id=own)
        g = C.games_for_catcher(cid) if cid else None
        if g is None or g.empty:
            return None, None
        return str(g["game_date"].min()), str(g["game_date"].max())

    @dash_app.callback(
        Output("game-dd", "options"), Output("game-dd", "value"),
        Input("cat-daterange", "start_date"), Input("cat-daterange", "end_date"),
        State("catcher-dd", "value"), prevent_initial_call=True,
    )
    def _on_range(start, end, catcher_id):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        cid = selectors.resolve_catcher(catcher_id, is_coach=is_coach, own_trackman_id=own)
        if not cid or not start or not end:
            return [], None
        g = C.games_for_catcher(cid, start=start, end=end)
        opts = dr.game_options(g)
        value = int(g.iloc[0]["game_id"]) if not g.empty else dr.ALL_IN_RANGE
        return opts, value
```

Replace `_on_selection` to carry the range + aggregate scoreboard:

```python
    @dash_app.callback(
        Output("selection", "data"), Output("sidebar", "children"),
        Output("scoreboard", "children"),
        Input("catcher-dd", "value"), Input("game-dd", "value"),
        State("cat-daterange", "start_date"), State("cat-daterange", "end_date"),
    )
    def _on_selection(catcher_id, game_id, start, end):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        cid = selectors.resolve_catcher(catcher_id, is_coach=is_coach, own_trackman_id=own)
        if game_id == dr.ALL_IN_RANGE:
            g = C.games_for_catcher(cid, start=start, end=end) if cid else None
            sb = layout.scoreboard(dr.ALL_IN_RANGE, start, end, g)
        else:
            sb = layout.scoreboard(game_id)
        return ({"catcher_id": cid, "game_id": game_id, "start": start, "end": end},
                layout.sidebar(cid), sb)
```

Replace `_on_load_data` to branch:

```python
    @dash_app.callback(Output("game-data", "data"), Input("selection", "data"))
    def _on_load_data(sel):
        if not sel or sel.get("catcher_id") is None:
            return None
        gid = sel.get("game_id")
        if gid == dr.ALL_IN_RANGE:
            if not sel.get("start") or not sel.get("end"):
                return None
            df = C.range_pitches_for(int(sel["catcher_id"]), sel["start"], sel["end"])
        elif gid is None:
            return None
        else:
            df = C.game_pitches_for(int(gid), int(sel["catcher_id"]))
        return None if df.empty else df.to_json(orient="split")
```

- [ ] **Step 5: Run tests + full suite**

Run: `python -m pytest tests/test_catching_dash.py -q` then `python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/dashboards/catching/ tests/test_catching_dash.py
git commit -m "feat(catching-dash): date-range picker + All-games-in-range aggregate"
```

---

### Task 6: Hitting data layer — date-bounded games + pooled loader

**Files:**
- Modify: `app/data/hitting_wh.py` (`wh_games_for_batter`; add `wh_range_pitches`)
- Test: `tests/test_hitting_wh.py` (append)

**Interfaces:**
- Consumes: `_sibling_ids`, `_in_clause`, `_PITCH_SELECT`, `_finish`, `LMU_TEAM_ID`, `query_df` (existing).
- Produces:
  - `wh_games_for_batter(batter_tm_id, start=None, end=None) -> df[game_id, game_date, GameLabel]` (already returns game_date)
  - `wh_range_pitches(batter_tm_id, start, end) -> df` (same shape as `wh_game_pitches`)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_hitting_wh.py`:

```python
def test_hitting_games_date_filter_and_range():
    from app.data import hitting_wh as H
    hitters = H.wh_lmu_hitters()
    if hitters.empty:
        import pytest; pytest.skip("no hitters")
    bid = int(hitters.iloc[0]["BatterId"])
    allg = H.wh_games_for_batter(bid)
    if allg.empty:
        import pytest; pytest.skip("no games")
    lo, hi = str(allg["game_date"].min()), str(allg["game_date"].max())
    assert len(H.wh_games_for_batter(bid, start=lo, end=hi)) == len(allg)
    pooled = H.wh_range_pitches(bid, lo, hi)
    single = sum(len(H.wh_game_pitches(int(g), bid)) for g in allg["game_id"])
    assert len(pooled) == single
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_hitting_wh.py -k "date_filter_and_range" -v`
Expected: FAIL (`wh_range_pitches` missing / start,end not accepted).

- [ ] **Step 3: Implement in `app/data/hitting_wh.py`**

Replace `wh_games_for_batter` with a date-aware version (keep the shape; add optional clause). The existing query builds an inner `bg` subselect of `game_id`s; add the date bound in the OUTER where on `g.game_date`:

```python
def wh_games_for_batter(batter_tm_id, start=None, end=None) -> pd.DataFrame:
    ph, idp = _in_clause(_sibling_ids(batter_tm_id))
    date_clause = ""
    if start is not None and end is not None:
        date_clause = " AND g.game_date BETWEEN :start AND :end"
        idp["start"] = str(start)
        idp["end"] = str(end)
    df = query_df(
        f"""
        SELECT g.game_id, g.game_date, g.home_team_id,
               CASE WHEN g.home_team_id = :lmu THEN 'vs' ELSE '@' END AS loc,
               t.team_name AS opp
          FROM (SELECT DISTINCT game_id FROM fact_tm_game_pitch
                 WHERE batter_tm_id IN ({ph})) bg
          JOIN dim_tm_game g ON g.game_id = bg.game_id
          JOIN tm_team t ON t.team_id = CASE WHEN g.home_team_id = :lmu
                                             THEN g.away_team_id ELSE g.home_team_id END
         WHERE 1=1{date_clause}
         ORDER BY g.game_date DESC
        """,
        {"lmu": LMU_TEAM_ID, **idp},
    )
    if df.empty:
        return pd.DataFrame(columns=["game_id", "game_date", "GameLabel"])
    df["GameLabel"] = [f"{pd.to_datetime(d).strftime('%m/%d/%y')} {l} {o}"
                       for d, l, o in zip(df["game_date"], df["loc"], df["opp"])]
    return df[["game_id", "game_date", "GameLabel"]]
```

Add `wh_range_pitches` next to `wh_season_pitches`:

```python
def wh_range_pitches(batter_tm_id, start, end) -> pd.DataFrame:
    """All of a batter's pitches across in-range games (sibling-id union)."""
    ph, idp = _in_clause(_sibling_ids(batter_tm_id))
    idp["start"] = str(start)
    idp["end"] = str(end)
    df = query_df(
        f"""
        SELECT {_PITCH_SELECT}
          FROM fact_tm_game_pitch f
          JOIN dim_tm_game g ON g.game_id = f.game_id
         WHERE f.batter_tm_id IN ({ph})
           AND g.game_date BETWEEN :start AND :end
         ORDER BY f.game_id, f.pitch_no
        """,
        idp,
    )
    return _finish(df)
```

NOTE: `_PITCH_SELECT` columns are unqualified (e.g. `PlateLocSide`) — verify they don't collide with `dim_tm_game` columns under the join. If any column in `_PITCH_SELECT` is ambiguous (exists in both tables), prefix those with `f.` in a local copy of the select for this function. Check by running Step 4; if a "column ambiguous" error appears, prefix the offending column(s) with `f.` in this query only (do not change the shared `_PITCH_SELECT`).

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_hitting_wh.py -k "date_filter_and_range" -v`
Expected: PASS. If a "column ... ambiguous" OperationalError occurs, prefix the ambiguous column(s) in this function's SELECT with `f.` and re-run.

- [ ] **Step 5: Commit**

```bash
git add app/data/hitting_wh.py tests/test_hitting_wh.py
git commit -m "feat(hitting-data): date-bounded wh_games_for_batter + wh_range_pitches"
```

---

### Task 7: Hitting dashboard wiring (+ combined Game-Level line, PA facet cap)

**Files:**
- Modify: `app/dashboards/hitting/layout.py`
- Modify: `app/dashboards/hitting/callbacks.py`
- Modify: `app/dashboards/hitting/tabs/plate_appearances.py` (facet cap when aggregating)
- Test: `tests/test_hitting_dash.py` (append)

**Interfaces:**
- Consumes: `date_range` helper; `hitting_wh.wh_games_for_batter(bid,start,end)`, `wh_range_pitches`, `wh_game_pitches`.
- Component ids: existing `hitter-dd`, `game-dd`, `scoreboard`, `selection`, `game-data`; new `hit-daterange`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_hitting_dash.py`:

```python
def test_hitting_range_pooled_render_live():
    from app import create_app
    from config import Config
    from app.data import hitting_wh as H
    from app.dashboards.hitting.tabs import game_level, plate_appearances as pa, zone_location as zl
    class T(Config):
        TESTING = True; SECRET_KEY = "t"; SQLALCHEMY_DATABASE_URI = "sqlite://"
    with create_app(T).app_context():
        hitters = H.wh_lmu_hitters()
        if hitters.empty:
            import pytest; pytest.skip("no hitters")
        bid = int(hitters.iloc[0]["BatterId"])
        g = H.wh_games_for_batter(bid)
        if g.empty:
            import pytest; pytest.skip("no games")
        lo, hi = str(g["game_date"].min()), str(g["game_date"].max())
        pooled = H.wh_range_pitches(bid, lo, hi)
        if pooled.empty:
            import pytest; pytest.skip("no pooled")
        assert game_level.render(pooled, note="") is not None
        assert pa.render_all_pas(pooled) is not None
        assert zl.render(pooled, "All Swings") is not None
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_hitting_dash.py -k range_pooled -v`
Expected: FAIL until Task 6; then it checks pooled render.

- [ ] **Step 3: Edit `layout.py`** (mirror Task 3/5 with hitting ids)

Add `from app.dashboards import date_range as dr` and ensure `from app.data import hitting_wh` is imported. In `serve_layout`, replace the games/`default_game` computation + the game dropdown portion of the selector row so the row is Hitter · Date range · Game:

```python
    games_df = hitting_wh.wh_games_for_batter(default_batter) if default_batter else None
    if games_df is not None and not games_df.empty:
        start_d = str(games_df["game_date"].min())
        end_d = str(games_df["game_date"].max())
        games = dr.game_options(games_df)
        default_game = int(games_df.iloc[0]["game_id"])
    else:
        start_d = end_d = None
        games = []
        default_game = None
```

Insert the date picker `html.Div` (label "Date range" + `dr.date_picker("hit", start_d, end_d)`) between the Hitter dropdown Div and the Game dropdown Div in `selector_row`. Set the Game dropdown `options=games, value=default_game`. Update the `selection` store initial data to include `"start": start_d, "end": end_d`. Update `scoreboard(...)` to the aggregate-aware form (same as Task 3/5).

(The exact `selector_row`/store/`scoreboard` structure matches `app/dashboards/hitting/layout.py` — read the current file and apply the same three edits shown in Task 3: add the picker Div, seed the range, aggregate-aware `scoreboard`.)

- [ ] **Step 4: Edit `callbacks.py`**

Add `from app.dashboards import date_range as dr`. Replace `_on_hitter` with the range pair, and update `_on_selection` + `_on_load_data`:

```python
    @dash_app.callback(
        Output("hit-daterange", "start_date"), Output("hit-daterange", "end_date"),
        Input("hitter-dd", "value"), prevent_initial_call=True,
    )
    def _on_hitter_range(batter_id):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        bid = selectors.resolve_batter(batter_id, is_coach=is_coach, own_trackman_id=own)
        g = hitting_wh.wh_games_for_batter(bid) if bid else None
        if g is None or g.empty:
            return None, None
        return str(g["game_date"].min()), str(g["game_date"].max())

    @dash_app.callback(
        Output("game-dd", "options"), Output("game-dd", "value"),
        Input("hit-daterange", "start_date"), Input("hit-daterange", "end_date"),
        State("hitter-dd", "value"), prevent_initial_call=True,
    )
    def _on_range(start, end, batter_id):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        bid = selectors.resolve_batter(batter_id, is_coach=is_coach, own_trackman_id=own)
        if not bid or not start or not end:
            return [], None
        g = hitting_wh.wh_games_for_batter(bid, start=start, end=end)
        opts = dr.game_options(g)
        value = int(g.iloc[0]["game_id"]) if not g.empty else dr.ALL_IN_RANGE
        return opts, value

    @dash_app.callback(
        Output("selection", "data"), Output("sidebar", "children"),
        Output("scoreboard", "children"),
        Input("hitter-dd", "value"), Input("game-dd", "value"),
        State("hit-daterange", "start_date"), State("hit-daterange", "end_date"),
    )
    def _on_selection(batter_id, game_id, start, end):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        bid = selectors.resolve_batter(batter_id, is_coach=is_coach, own_trackman_id=own)
        if game_id == dr.ALL_IN_RANGE:
            g = hitting_wh.wh_games_for_batter(bid, start=start, end=end) if bid else None
            sb = layout.scoreboard(dr.ALL_IN_RANGE, start, end, g)
        else:
            sb = layout.scoreboard(game_id)
        return ({"batter_id": bid, "game_id": game_id, "start": start, "end": end},
                layout.sidebar(bid), sb)
```

Replace `_load_game_df` so the load callback branches on the sentinel:

```python
def _load_game_df(store) -> pd.DataFrame:
    if not store or store.get("batter_id") is None:
        return pd.DataFrame()
    gid = store.get("game_id")
    from app.dashboards import date_range as dr
    if gid == dr.ALL_IN_RANGE:
        if not store.get("start") or not store.get("end"):
            return pd.DataFrame()
        return hitting_wh.wh_range_pitches(int(store["batter_id"]),
                                           store["start"], store["end"])
    if gid is None:
        return pd.DataFrame()
    return hitting_wh.wh_game_pitches(int(gid), int(store["batter_id"]))
```

The Game-Level tab already renders a batting line from the pooled df (`game_level.render(df, note="")`), which naturally becomes the **combined line over the range** — no change needed beyond the caption. In `_render_tab`'s `game` branch, when the selection is aggregate, pass a caption; simplest: leave `game_level.render(df, note="")` as-is (the combined line is correct); the range context shows in the scoreboard.

- [ ] **Step 5: Edit `plate_appearances.py` — cap facets when aggregating**

In `render_all_pas(df)`, before building the faceted figure, cap to the 12 most recent PAs and add a caption when capped. Find where PAs are enumerated (grouped by Inning/PAofInning across the df) and limit to the last 12 by game/PA order. Concretely, at the top of `render_all_pas`:

```python
def render_all_pas(df):
    # Cap to the 12 most recent PAs so a pooled multi-game range doesn't wall.
    capped_note = None
    if not df.empty:
        keys = df[["game_id", "Inning", "PAofInning"]].drop_duplicates() \
            if "game_id" in df.columns else df[["Inning", "PAofInning"]].drop_duplicates()
        if len(keys) > 12:
            recent = keys.tail(12)
            df = df.merge(recent, on=list(recent.columns), how="inner")
            capped_note = f"showing 12 most recent of {len(keys)} PAs"
    # ... existing figure-building on df ...
    # if capped_note: prepend/append a small caption Div to the returned component
```

Read the current `render_all_pas` body and integrate the cap + caption without changing its per-PA facet logic. If `game_id` is not a column on the pooled df, fall back to Inning/PAofInning keys (single game) — the cap is a no-op for single games (≤ a handful of PAs).

- [ ] **Step 6: Run tests + full suite**

Run: `python -m pytest tests/test_hitting_dash.py -q` then `python -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/dashboards/hitting/ tests/test_hitting_dash.py
git commit -m "feat(hitting-dash): date-range picker + All-games-in-range aggregate + PA facet cap"
```

---

### Task 8: Practice dashboard — calendar picker (presets kept)

**Files:**
- Modify: `app/dashboards/hitting_practice/layout.py`
- Modify: `app/dashboards/hitting_practice/callbacks.py`
- Test: `tests/test_hitting_practice_dash.py` (append)

**Interfaces:**
- Consumes: `date_range.date_picker`; `P.date_bounds()`, `P.preset_date_range`, `P.apply_filters` (existing).
- Component ids: existing `prac-date-preset`, `prac-filters`, `prac-player`, `prac-session`, `prac-exclude-test`; new `prac-daterange`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_hitting_practice_dash.py`:

```python
def test_practice_layout_has_daterange():
    from app import create_app
    from config import Config
    class T(Config):
        TESTING = True; SECRET_KEY = "t"; SQLALCHEMY_DATABASE_URI = "sqlite://"
    app = create_app(T)
    with app.test_request_context():
        from flask_login import login_user
        # layout references current_user; just assert the component tree builds
        from app.dashboards.hitting_practice import layout
        # serve_layout requires auth; assert the picker id is wired in the module
        import inspect
        src = inspect.getsource(layout)
        assert "prac-daterange" in src
```

(A light structural test — the substantive behavior is covered by the live smoke in Task 9. Matches the repo's practice-dash test style.)

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_hitting_practice_dash.py -k daterange -v`
Expected: FAIL (`prac-daterange` not in layout source).

- [ ] **Step 3: Edit `layout.py`**

Add `from app.dashboards import date_range as dr` and `from app.data import practice as P` (P is already imported). Seed bounds and add the picker Div to the `filters` row (after the Date-range preset Div):

```python
    min_d, max_d = P.date_bounds()
```

Add this Div into the `filters` children list, right after the `prac-date-preset` Div:

```python
        html.Div([
            html.Label("Calendar", style={"color": "white", "fontWeight": "bold"}),
            dr.date_picker("prac", start.isoformat(), end.isoformat(),
                           min_date=str(min_d), max_date=str(max_d)),
        ]),
```

(`start`/`end` already computed in `serve_layout` via `P.preset_date_range("Custom")`.)

- [ ] **Step 4: Edit `callbacks.py`**

Wire the picker both ways with the preset in the existing `_on_filters` callback. The current callback is:

```python
    @dash_app.callback(
        Output("prac-filters", "data"),
        Output("prac-player", "options"),
        Output("prac-session", "options"),
        Input("prac-date-preset", "value"),
        Input("prac-player", "value"),
        Input("prac-session", "value"),
        Input("prac-exclude-test", "value"),
    )
    def _on_filters(preset, player, session, exclude_vals):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own_name = getattr(current_user, "name", None)
        exclude_test = "exclude" in (exclude_vals or [])
        pitch, _, _, _ = _load_all(exclude_test)
        start, end = P.preset_date_range(preset or "Custom")
        windowed = P.apply_filters(pitch, player=None, start=start, end=end, session=None)
        base = windowed if not windowed.empty else pitch
        popts = selectors.player_options(base, is_coach=is_coach, own_name=own_name)
        sopts = [{"label": s, "value": s} for s in P.session_options(base)]
        player = selectors.resolve_player(player, is_coach=is_coach, own_name=own_name)
        if player not in {o["value"] for o in popts} and popts:
            player = popts[0]["value"]
        return (
            {"player": player, "preset": preset or "Custom",
             "session": session or "All session types",
             "exclude_test": exclude_test,
             "start": start.isoformat(), "end": end.isoformat()},
            popts, sopts,
        )
```

Replace it with the picker-synced version (adds the calendar as two Inputs and two Outputs; the calendar wins when it triggered, otherwise the preset drives, and the resolved window is echoed back into the calendar). Add `from dash import ctx` and `from datetime import date as _date` to the imports (or use module-qualified `dash.ctx`):

```python
    @dash_app.callback(
        Output("prac-filters", "data"),
        Output("prac-player", "options"),
        Output("prac-session", "options"),
        Output("prac-daterange", "start_date"),
        Output("prac-daterange", "end_date"),
        Input("prac-date-preset", "value"),
        Input("prac-player", "value"),
        Input("prac-session", "value"),
        Input("prac-exclude-test", "value"),
        Input("prac-daterange", "start_date"),
        Input("prac-daterange", "end_date"),
    )
    def _on_filters(preset, player, session, exclude_vals, ds, de):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own_name = getattr(current_user, "name", None)
        exclude_test = "exclude" in (exclude_vals or [])
        pitch, _, _, _ = _load_all(exclude_test)
        # Calendar edit wins when it fired; otherwise the preset drives the window.
        if ctx.triggered_id == "prac-daterange" and ds and de:
            start = _date.fromisoformat(ds[:10])
            end = _date.fromisoformat(de[:10])
        else:
            start, end = P.preset_date_range(preset or "Custom")
        windowed = P.apply_filters(pitch, player=None, start=start, end=end, session=None)
        base = windowed if not windowed.empty else pitch
        popts = selectors.player_options(base, is_coach=is_coach, own_name=own_name)
        sopts = [{"label": s, "value": s} for s in P.session_options(base)]
        player = selectors.resolve_player(player, is_coach=is_coach, own_name=own_name)
        if player not in {o["value"] for o in popts} and popts:
            player = popts[0]["value"]
        return (
            {"player": player, "preset": preset or "Custom",
             "session": session or "All session types",
             "exclude_test": exclude_test,
             "start": start.isoformat(), "end": end.isoformat()},
            popts, sopts, start.isoformat(), end.isoformat(),
        )
```

The store still carries `start`/`end`; `P.apply_filters` already consumes them, so `_load_pitch`/`_render` need no change.

- [ ] **Step 5: Run tests + live smoke**

Run: `python -m pytest tests/test_hitting_practice_dash.py -q` then `python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/dashboards/hitting_practice/ tests/test_hitting_practice_dash.py
git commit -m "feat(practice-dash): calendar date-range picker synced with presets"
```

---

### Task 9: Live both-role smoke + review prep

**Files:** none (verification only; scratchpad allowed).

- [ ] **Step 1: Live smoke each dashboard's aggregate path**

Write a scratchpad script (not committed) that, in `create_app().app_context()`, for pitching/catching/hitting: picks the first LMU player, gets `games_for_*`, computes `[min,max]` range, loads `range_pitches_for(...)`, and asserts non-empty + that each tab's render fn runs without error on the pooled df. For practice: `P.apply_filters` over a wide range returns rows.

Run: `PYTHONIOENCODING=utf-8 python <scratchpad>/smoke_daterange.py`
Expected: all print non-zero pooled counts and render OK.

- [ ] **Step 2: Restart the dev server by port owner (if a live browser check is wanted)**

Per MEMORY §3b, kill by port owner before relaunch; only one instance. In-process smoke (Step 1) is authoritative.

- [ ] **Step 3: Update memory + request final review**

Append the outcome to `memory/MEMORY.md` (date-range feature: which dashboards, suite count, any Minors). Then request a whole-branch code review (superpowers:requesting-code-review) before merge.

---

## Notes for the implementer

- The two-callback range pattern (reset-range-on-player + populate-games-from-range) with `prevent_initial_call=True` avoids a duplicate-Output conflict and initial clobbering; the layout seeds the initial picker + game dropdown so the dashboard opens on the most recent game with no callback needed.
- Every game dashboard follows the identical shape — read the current `layout.py`/`callbacks.py` for the dashboard you're editing and apply the shown edits with that dashboard's ids (`pit`/`cat`/`hit`, `pitcher/catcher/hitter-dd`, `outing/game-dd`, loader names).
- Do not add caching. Do not change single-game behavior.
- After all tasks: full suite green; each dashboard opens on the most recent game and offers "All games in range".
