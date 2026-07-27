# Hitting Balls-in-Play + Last-27-PA Tabs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add two analytical tabs to the hitting dashboard — **Balls in Play** (launch-angle radial + spray chart, hit-type filter) and **Last 27 PA** (recent-PA batting/batted-ball/swing-decision tables + BIP spray).

**Architecture:** Two pure data helpers in `app/data/hitting_wh.py` query the warehouse fact directly for BIP coordinates and the last-27-PA pitch set (reusing the existing `_finish` pipeline). Two Plotly figures in the hitting `charts.py` draw the radial and spray with no image assets. Two tab modules render them; the hitting `callbacks._render_tab` gains two branches that query fresh from the selection (like the video tab), plus a hit-type chip-filter trio mirroring the pitching `lm-*` pattern.

**Tech Stack:** Python, Dash (`dcc.Graph`, `dash_table`, pattern-matching callbacks), Plotly `graph_objects`, pandas, numpy, SQLAlchemy (`query_df`), pytest.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-27-hitting-bip-last27-design.md`. Branch `feat/pitch-level-video`.
- BIP fields on `fact_tm_game_pitch`: `exit_speed`, `la` (launch angle), `bearing`, `distance`, `tagged_hit_type`; BIP = `pitch_call='InPlay'`.
- Coord formulas (verbatim from legacy `src/app 1`): spray `x = sin(bearing°)·distance`, `y = cos(bearing°)·distance`; radial `rx = exit_speed/120·cos(la°)`, `ry = exit_speed/120·sin(la°)`.
- Reuse: `hitting.game_batting_line(df)->dict`, `hitting.batted_ball_profile(df, by_pitch_type=False)->df`, `hitting.swing_decisions_by_zone(df)->df`, `tables.stat_table(df, *, id=, color_col=)`, `hitting_wh._sibling_ids`, `hitting_wh._in_clause`, `hitting_wh._finish`, `hitting_wh._PITCH_SELECT`.
- Selection store key: `batter_id`; range sentinel `dr.ALL_IN_RANGE`. `suppress_callback_exceptions=True` is set.
- Colors: crimson `#9A0021`, font `Teko, sans-serif`. Tests hit the live DB (repo convention). Full suite stays green. Run `python -m pytest -q`.

---

### Task H1: Data helpers `wh_bip_points` + `wh_last_n_pas`

**Files:**
- Modify: `app/data/hitting_wh.py` (append two functions; `numpy as np` is already imported)
- Test: `tests/test_hitting_wh.py` (append)

**Interfaces — Produces:**
- `wh_bip_points(batter_tm_id, game_id) -> pd.DataFrame` — `game_id` int or list; columns `["hit_type","exit_speed","la","bearing","distance","x","y","rx","ry","Count","Result","PitchType","Pitcher"]`; one row per InPlay pitch; empty full-column frame when no games/BIP.
- `wh_last_n_pas(batter_tm_id, n=27) -> pd.DataFrame` — the batter's most recent `n` PAs' pitches, `_finish`ed (same shape as `wh_game_pitches`).

- [ ] **Step 1: Write the failing test** (append to `tests/test_hitting_wh.py`)

```python
def _a_hitting_bip_batter():
    from app.db import query_df
    r = query_df(
        """
        SELECT batter_tm_id, game_id FROM fact_tm_game_pitch
         WHERE batter_team='LOY_LIO' AND pitch_call='InPlay'
           AND bearing IS NOT NULL AND distance IS NOT NULL
           AND exit_speed IS NOT NULL AND la IS NOT NULL
         LIMIT 1
        """
    ).iloc[0]
    return int(r["batter_tm_id"]), int(r["game_id"])


def test_wh_bip_points_shape_and_coords():
    import math
    from app.data import hitting_wh
    bid, gid = _a_hitting_bip_batter()
    df = hitting_wh.wh_bip_points(bid, gid)
    assert not df.empty
    for c in ["hit_type", "x", "y", "rx", "ry", "exit_speed", "la"]:
        assert c in df.columns
    # coords match the legacy formula for the first fully-populated row
    row = df.dropna(subset=["bearing", "distance"]).iloc[0]
    exp_x = math.sin(math.radians(row["bearing"])) * row["distance"]
    assert abs(row["x"] - exp_x) < 1e-6


def test_wh_bip_points_empty_game_list():
    from app.data import hitting_wh
    bid, _ = _a_hitting_bip_batter()
    df = hitting_wh.wh_bip_points(bid, [])
    assert df.empty and "hit_type" in df.columns


def test_wh_last_n_pas_shape():
    from app.data import hitting_wh
    bid, _ = _a_hitting_bip_batter()
    df = hitting_wh.wh_last_n_pas(bid, 27)
    # same column shape as a game df (goes through _finish)
    assert "PlateLocSide" in df.columns and "PAofInning" in df.columns
    # at most 27 distinct PAs
    if not df.empty:
        pas = df[["GameID", "Inning", "PAofInning"]].drop_duplicates()
        assert len(pas) <= 27
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_hitting_wh.py -k "bip or last_n" -q`
Expected: FAIL (`AttributeError: module ... has no attribute 'wh_bip_points'`).

- [ ] **Step 3: Implement** (append to `app/data/hitting_wh.py`)

```python
_BIP_COLS = ["hit_type", "exit_speed", "la", "bearing", "distance",
             "x", "y", "rx", "ry", "Count", "Result", "PitchType", "Pitcher"]


def wh_bip_points(batter_tm_id, game_id) -> pd.DataFrame:
    """Balls-in-play landing (x,y) + launch-radial (rx,ry) for a batter and
    game(s). `game_id` is an int or a list. Empty full-column frame when none."""
    gids = [int(g) for g in (game_id if isinstance(game_id, (list, tuple)) else [game_id])]
    if not gids:
        return pd.DataFrame(columns=_BIP_COLS)
    ph, idp = _in_clause(_sibling_ids(batter_tm_id))
    gph = ", ".join(f":g{i}" for i in range(len(gids)))
    idp.update({f"g{i}": g for i, g in enumerate(gids)})
    df = query_df(
        f"""
        SELECT tagged_hit_type AS hit_type, exit_speed, la, bearing, distance,
               play_result AS PlayResult, pitch_call AS PitchCall,
               tagged_pitch_type AS PitchType, pitcher_name AS Pitcher,
               balls AS Balls, strikes AS Strikes
          FROM fact_tm_game_pitch
         WHERE game_id IN ({gph}) AND batter_tm_id IN ({ph})
           AND pitch_call = 'InPlay'
         ORDER BY game_id, pitch_no
        """,
        idp,
    )
    if df.empty:
        return pd.DataFrame(columns=_BIP_COLS)
    df["hit_type"] = df["hit_type"].fillna("Undefined").replace("", "Undefined")
    br = np.radians(df["bearing"].astype(float))
    df["x"] = np.sin(br) * df["distance"].astype(float)
    df["y"] = np.cos(br) * df["distance"].astype(float)
    la = np.radians(df["la"].astype(float))
    ev = df["exit_speed"].astype(float)
    df["rx"] = ev / 120.0 * np.cos(la)
    df["ry"] = ev / 120.0 * np.sin(la)
    df["Count"] = (df["Balls"].astype("Int64").astype(str) + "-"
                   + df["Strikes"].astype("Int64").astype(str))
    undefined = df["PlayResult"].isna() | df["PlayResult"].isin(["Undefined"])
    df["Result"] = np.where(undefined, df["PitchCall"],
                            df["hit_type"] + " - " + df["PlayResult"].astype(str))
    return df[_BIP_COLS]


def wh_last_n_pas(batter_tm_id, n: int = 27) -> pd.DataFrame:
    """The batter's most recent `n` plate appearances (across all games),
    returned through _finish so the shared hitting transforms apply."""
    ph, idp = _in_clause(_sibling_ids(batter_tm_id))
    pas = query_df(
        f"""
        SELECT d.game_id, d.inning, d.pa_of_inning FROM (
          SELECT DISTINCT f.game_id, f.inning, f.pa_of_inning, g.game_date
            FROM fact_tm_game_pitch f
            JOIN dim_tm_game g ON g.game_id = f.game_id
           WHERE f.batter_tm_id IN ({ph})
        ) d
        ORDER BY d.game_date DESC, d.inning DESC, d.pa_of_inning DESC
        LIMIT {int(n)}
        """,
        idp,
    )
    all_df = _finish(query_df(
        f"SELECT {_PITCH_SELECT} FROM fact_tm_game_pitch "
        f"WHERE batter_tm_id IN ({ph}) ORDER BY game_id, pitch_no",
        idp,
    ))
    if all_df.empty or pas.empty:
        return all_df
    keys = set(zip(pas["game_id"].astype(int), pas["inning"].astype(int),
                   pas["pa_of_inning"].astype(int)))
    mask = [(int(g), int(i), int(p)) in keys
            for g, i, p in zip(all_df["GameID"], all_df["Inning"], all_df["PAofInning"])]
    return all_df[mask].reset_index(drop=True)
```

- [ ] **Step 4: Run tests** — `python -m pytest tests/test_hitting_wh.py -q` → PASS.
- [ ] **Step 5: Commit**

```bash
git add app/data/hitting_wh.py tests/test_hitting_wh.py
git commit -m "feat(hitting): wh_bip_points + wh_last_n_pas warehouse helpers"
```

---

### Task H2: Charts `radial_fig` + `spray_fig`

**Files:**
- Modify: `app/dashboards/hitting/charts.py` (append; `plotly.graph_objects as go` is imported — add `import numpy as np` at the top if absent)
- Test: `tests/test_hitting_dash.py` (append)

**Interfaces — Produces:** `charts._HIT_COLORS: dict`, `charts.radial_fig(bip_df) -> go.Figure`, `charts.spray_fig(bip_df) -> go.Figure` (both empty-safe).

- [ ] **Step 1: Write the failing test** (append to `tests/test_hitting_dash.py`)

```python
def test_bip_figs_empty_and_nonempty():
    import pandas as pd
    import plotly.graph_objects as go
    from app.dashboards.hitting import charts
    empty = pd.DataFrame(columns=["hit_type", "x", "y", "rx", "ry", "exit_speed", "la", "distance"])
    assert isinstance(charts.radial_fig(empty), go.Figure)
    assert isinstance(charts.spray_fig(empty), go.Figure)
    df = pd.DataFrame({
        "hit_type": ["LineDrive", "FlyBall"], "x": [50.0, -60.0], "y": [200.0, 180.0],
        "rx": [0.6, 0.5], "ry": [0.2, 0.5], "exit_speed": [95.0, 88.0],
        "la": [12.0, 30.0], "distance": [300.0, 280.0]})
    assert len(charts.radial_fig(df).data) >= 2
    assert len(charts.spray_fig(df).data) >= 2
```

- [ ] **Step 2: Run test** — `python -m pytest tests/test_hitting_dash.py -k bip_figs -q` → FAIL.

- [ ] **Step 3: Implement** (append to `app/dashboards/hitting/charts.py`; ensure `import numpy as np` is present near the top imports)

```python
_HIT_COLORS = {"FlyBall": "#c0392b", "GroundBall": "#4a7fb5", "LineDrive": "#e08a1e",
               "PopUp": "#6b8e23", "Undefined": "#888888"}


def _empty_bip_fig(title: str) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        title=title, height=440, margin=dict(l=10, r=10, t=50, b=10),
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"),
        annotations=[dict(text="No balls in play for this selection.",
                          showarrow=False, font=dict(size=18, family="Teko, sans-serif"))])
    return fig


def radial_fig(bip_df) -> go.Figure:
    """Launch-angle radial: EV rings (40/90/120 mph) + LA guide lines, points at
    (rx, ry) colored by hit type."""
    d = None
    if bip_df is not None and not bip_df.empty:
        d = bip_df[bip_df["rx"].notna() & bip_df["ry"].notna()]
    if d is None or d.empty:
        return _empty_bip_fig("Launch Angle / Exit Velo")
    fig = go.Figure()
    th = np.linspace(-np.pi / 2, np.pi / 2, 200)
    for r, fill in [(1.0, "#e8e8e8"), (2 / 3, "#c8c8c8"), (1 / 3, "#9a9a9a")]:
        fig.add_trace(go.Scatter(
            x=np.concatenate([r * np.cos(th), [0.0]]),
            y=np.concatenate([r * np.sin(th), [-r]]),
            fill="toself", fillcolor=fill, line=dict(width=0),
            hoverinfo="skip", showlegend=False))
    for ang, color in [(8, "green"), (25, "green"), (45, "#777"), (90, "#777")]:
        a = np.radians(ang)
        fig.add_trace(go.Scatter(x=[0, np.cos(a)], y=[0, np.sin(a)], mode="lines",
                                 line=dict(color=color, width=1), hoverinfo="skip",
                                 showlegend=False))
    for ht, sub in d.groupby("hit_type"):
        fig.add_trace(go.Scatter(
            x=sub["rx"], y=sub["ry"], mode="markers", name=str(ht), showlegend=False,
            marker=dict(size=9, color=_HIT_COLORS.get(str(ht), "#888"),
                        line=dict(width=0.5, color="#555")),
            customdata=sub[["exit_speed", "la"]].to_numpy(),
            hovertemplate=(f"{ht}<br>EV: %{{customdata[0]:.1f}} mph"
                           "<br>LA: %{customdata[1]:.0f}°<extra></extra>")))
    fig.update_layout(
        title="Launch Angle / Exit Velo", height=440, margin=dict(l=10, r=10, t=50, b=10),
        xaxis=dict(range=[0, 1.15], visible=False),
        yaxis=dict(range=[-1.15, 1.15], visible=False, scaleanchor="x", scaleratio=1),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"))
    return fig


def spray_fig(bip_df) -> go.Figure:
    """Spray chart: foul lines + outfield arc + infield diamond, points at (x, y)
    colored by hit type."""
    d = None
    if bip_df is not None and not bip_df.empty:
        d = bip_df[bip_df["x"].notna() & bip_df["y"].notna()]
    if d is None or d.empty:
        return _empty_bip_fig("Spray Chart")
    fig = go.Figure()
    L = 400.0
    for sgn in (-1, 1):
        t = np.radians(45.0) * sgn
        fig.add_shape(type="line", x0=0, y0=0, x1=L * np.sin(t), y1=L * np.cos(t),
                      line=dict(color="#888", width=1))
    arc = np.radians(np.linspace(-45, 45, 80))
    fig.add_trace(go.Scatter(x=L * np.sin(arc), y=L * np.cos(arc), mode="lines",
                             line=dict(color="#888", width=1), hoverinfo="skip",
                             showlegend=False))
    b = 63.6
    fig.add_shape(type="path", path=f"M 0,0 L {b},{b} L 0,{2 * b} L {-b},{b} Z",
                  line=dict(color="#bbb", width=1), fillcolor="rgba(0,0,0,0)")
    for ht, sub in d.groupby("hit_type"):
        fig.add_trace(go.Scatter(
            x=sub["x"], y=sub["y"], mode="markers", name=str(ht), showlegend=False,
            marker=dict(size=9, color=_HIT_COLORS.get(str(ht), "#888"),
                        line=dict(width=0.5, color="#555")),
            customdata=sub[["distance", "exit_speed"]].to_numpy(),
            hovertemplate=(f"{ht}<br>Dist: %{{customdata[0]:.0f}} ft"
                           "<br>EV: %{customdata[1]:.1f} mph<extra></extra>")))
    fig.update_layout(
        title="Spray Chart", height=440, margin=dict(l=10, r=10, t=50, b=10),
        xaxis=dict(range=[-250, 250], visible=False),
        yaxis=dict(range=[-20, 430], visible=False, scaleanchor="x", scaleratio=1),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"))
    return fig
```

- [ ] **Step 4: Run tests** — `python -m pytest tests/test_hitting_dash.py -k bip_figs -q` → PASS.
- [ ] **Step 5: Commit**

```bash
git add app/dashboards/hitting/charts.py tests/test_hitting_dash.py
git commit -m "feat(hitting): radial + spray Plotly figures for balls in play"
```

---

### Task H3: Tab modules `balls_in_play` + `last_27`

**Files:**
- Create: `app/dashboards/hitting/tabs/balls_in_play.py`
- Create: `app/dashboards/hitting/tabs/last_27.py`
- Test: `tests/test_hitting_dash.py` (append)

**Interfaces — Produces:**
- `balls_in_play.chip_row(bip_df)`, `balls_in_play.body(bip_df)`, `balls_in_play.render(bip_df)`.
- `last_27.render(last_df, bip_df)`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_hitting_dash.py`)

```python
def test_bip_tab_render_has_chip_store_and_graph():
    import pandas as pd
    from app.dashboards.hitting.tabs import balls_in_play
    df = pd.DataFrame({
        "hit_type": ["LineDrive"], "x": [50.0], "y": [200.0], "rx": [0.6], "ry": [0.2],
        "exit_speed": [95.0], "la": [12.0], "distance": [300.0],
        "Count": ["1-1"], "Result": ["LineDrive - Single"], "PitchType": ["Fastball"],
        "Pitcher": ["X"]})
    out = balls_in_play.render(df)
    s = str(out)
    assert "bip-active" in s and "bip-body" in s and "bip-chip" in s


def test_last27_render_empty_ok():
    import pandas as pd
    from app.dashboards.hitting.tabs import last_27
    out = last_27.render(pd.DataFrame(), pd.DataFrame())
    assert "No recent plate appearances" in str(out)
```

- [ ] **Step 2: Run test** — `python -m pytest tests/test_hitting_dash.py -k "bip_tab or last27_render" -q` → FAIL.

- [ ] **Step 3: Implement**

```python
# app/dashboards/hitting/tabs/balls_in_play.py
"""Balls in Play tab: hit-type chip filter -> launch-angle radial + spray chart."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.dashboards.hitting import charts


def _chip_style(color: str, on: bool) -> dict:
    return {"border": f"2px solid {color}", "background": color if on else "#fff",
            "color": "#fff" if on else color, "borderRadius": "14px",
            "padding": "3px 12px", "margin": "0 6px 6px 0", "cursor": "pointer",
            "opacity": "1" if on else ".55", "fontFamily": "Teko, sans-serif",
            "fontSize": "15px"}


def chip_row(bip_df: pd.DataFrame) -> html.Div:
    types = list(pd.unique(bip_df["hit_type"])) if bip_df is not None and not bip_df.empty else []
    chips = [html.Button(str(ht), id={"type": "bip-chip", "index": str(ht)}, n_clicks=0,
                         style=_chip_style(charts._HIT_COLORS.get(str(ht), "#888"), True))
             for ht in types]
    return html.Div([dcc.Store(id="bip-active", data=[str(t) for t in types]),
                     html.Div(chips)], style={"margin": "6px 0"})


def body(bip_df: pd.DataFrame) -> html.Div:
    if bip_df is None or bip_df.empty:
        return html.Div("No balls in play for this selection.",
                        style={"padding": "12px", "color": "#555"})
    return html.Div([
        html.Div(dcc.Graph(figure=charts.radial_fig(bip_df)), style={"flex": "1"}),
        html.Div(dcc.Graph(figure=charts.spray_fig(bip_df)), style={"flex": "1"}),
    ], style={"display": "flex", "gap": "16px"})


def render(bip_df: pd.DataFrame) -> html.Div:
    return html.Div([chip_row(bip_df), html.Div(id="bip-body", children=body(bip_df))])
```

```python
# app/dashboards/hitting/tabs/last_27.py
"""Last 27 PA tab: recent-PA batting/batted-ball/swing tables + BIP spray."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import hitting
from app.dashboards.hitting import charts, tables

_H = {"color": "#9A0021", "margin": "16px 0 6px"}


def render(last_df: pd.DataFrame, bip_df: pd.DataFrame) -> html.Div:
    if last_df is None or last_df.empty:
        return html.Div("No recent plate appearances.",
                        style={"padding": "12px", "color": "#555"})
    line_df = pd.DataFrame([hitting.game_batting_line(last_df)])
    _drop = ["Avg QC+", "Avg PathQ+"]
    bb = hitting.batted_ball_profile(last_df).drop(columns=_drop, errors="ignore")
    sd = hitting.swing_decisions_by_zone(last_df)
    return html.Div([
        html.H3("Last 27 PA — Batting Line", style=_H),
        tables.stat_table(line_df, id="l27-line"),
        html.H3("Batted Ball Profile", style=_H),
        tables.stat_table(bb, id="l27-bb"),
        html.H3("Swing Decisions by Zone", style=_H),
        tables.stat_table(sd, id="l27-sd"),
        html.H3("Balls in Play — Spray", style=_H),
        dcc.Graph(figure=charts.spray_fig(bip_df)),
    ], style={"padding": "10px 4px"})
```

- [ ] **Step 4: Run tests** — `python -m pytest tests/test_hitting_dash.py -k "bip_tab or last27_render" -q` → PASS.
- [ ] **Step 5: Commit**

```bash
git add app/dashboards/hitting/tabs/balls_in_play.py app/dashboards/hitting/tabs/last_27.py tests/test_hitting_dash.py
git commit -m "feat(hitting): Balls in Play + Last 27 PA tab modules"
```

---

### Task H4: Wire tabs into the hitting dashboard

**Files:**
- Modify: `app/dashboards/hitting/layout.py` (tabs list ~line 109)
- Modify: `app/dashboards/hitting/callbacks.py` (imports; `_render_tab`; new chip trio; a `_resolve_gids` helper)
- Test: `tests/test_hitting_dash.py` (append)

**Interfaces — Consumes:** Task H1 (`wh_bip_points`, `wh_last_n_pas`), Task H3 tabs.

- [ ] **Step 1: Write the failing test** (append to `tests/test_hitting_dash.py`)

```python
def test_hitting_tabs_include_bip_and_last27():
    import inspect
    from app.dashboards.hitting import layout
    src = inspect.getsource(layout.serve_layout)
    assert '"bip"' in src and "Balls in Play" in src
    assert '"last27"' in src and "Last 27 PA" in src
```

- [ ] **Step 2: Run test** — `python -m pytest tests/test_hitting_dash.py -k "bip_and_last27" -q` → FAIL.

- [ ] **Step 3: Implement**

In `app/dashboards/hitting/layout.py`, extend the tabs:

```python
    tabs = dcc.Tabs(id="tabs", value="game", children=[
        dcc.Tab(label="Game Level", value="game"),
        dcc.Tab(label="Plate Appearances", value="pa"),
        dcc.Tab(label="Zone Location", value="zone"),
        dcc.Tab(label="Video", value="video"),
        dcc.Tab(label="Balls in Play", value="bip"),
        dcc.Tab(label="Last 27 PA", value="last27"),
    ])
```
(The `Video` tab is already present from sub-project V; add the two new tabs after it.)

In `app/dashboards/hitting/callbacks.py`:

(a) Ensure the dash import line includes `ALL` and `ctx`:
```python
from dash import ALL, Input, Output, State, ctx, dcc, html
```
and the tab imports include the new modules:
```python
from app.dashboards.hitting.tabs import (game_level, plate_appearances as pa,
                                         zone_location as zl, balls_in_play, last_27)
```

(b) Add a module-level helper (top of file, after imports):
```python
def _resolve_gids(sel):
    """Selection -> list of game_ids (single game, or all games in range)."""
    sel = sel or {}
    bid = sel.get("batter_id")
    gid = sel.get("game_id")
    if bid is None:
        return []
    if gid == dr.ALL_IN_RANGE:
        g = hitting_wh.wh_games_for_batter(int(bid), start=sel.get("start"), end=sel.get("end"))
        return [int(x) for x in g["game_id"]] if not g.empty else []
    if gid is None:
        return []
    return [int(gid)]
```

(c) Add two branches at the TOP of `_render_tab` (they use `sel`, not `df`):
```python
        if tab == "bip":
            sel = sel or {}
            bid = sel.get("batter_id")
            if bid is None:
                return html.Div("Select a hitter.", style={"padding": "12px", "color": "#555"})
            bip = hitting_wh.wh_bip_points(int(bid), _resolve_gids(sel))
            return balls_in_play.render(bip)
        if tab == "last27":
            sel = sel or {}
            bid = sel.get("batter_id")
            if bid is None:
                return html.Div("Select a hitter.", style={"padding": "12px", "color": "#555"})
            last = hitting_wh.wh_last_n_pas(int(bid), 27)
            gids = sorted({int(g) for g in last["GameID"]}) if not last.empty else []
            bip = hitting_wh.wh_bip_points(int(bid), gids)
            return last_27.render(last, bip)
```

(d) Add the hit-type chip trio at the end of `register_callbacks` (before the `notes_ui`/`videotab` registration lines):
```python
    @dash_app.callback(
        Output("bip-active", "data"),
        Input({"type": "bip-chip", "index": ALL}, "n_clicks"),
        State("bip-active", "data"), prevent_initial_call=True,
    )
    def _bip_toggle(_clicks, active):
        tid = ctx.triggered_id
        if not tid:
            return active
        ht = tid["index"]; active = list(active or [])
        return [c for c in active if c != ht] if ht in active else active + [ht]

    @dash_app.callback(
        Output("bip-body", "children"),
        Input("bip-active", "data"), State("selection", "data"),
    )
    def _bip_body(active, sel):
        sel = sel or {}
        bid = sel.get("batter_id")
        if bid is None:
            return html.Div("Select a hitter.", style={"padding": "12px", "color": "#555"})
        bip = hitting_wh.wh_bip_points(int(bid), _resolve_gids(sel))
        if active is not None and not bip.empty:
            bip = bip[bip["hit_type"].isin(active)]
        return balls_in_play.body(bip)

    @dash_app.callback(
        Output({"type": "bip-chip", "index": ALL}, "style"),
        Input("bip-active", "data"),
        State({"type": "bip-chip", "index": ALL}, "id"),
    )
    def _bip_chip_styles(active, ids):
        active = set(active or [])
        out = []
        for i in ids:
            ht = i["index"]; col = balls_in_play.charts._HIT_COLORS.get(ht, "#888")
            on = ht in active
            out.append(balls_in_play._chip_style(col, on))
        return out
```

- [ ] **Step 4: Run tests** — `python -m pytest tests/test_hitting_dash.py -q` → PASS.
- [ ] **Step 5: Commit**

```bash
git add app/dashboards/hitting/layout.py app/dashboards/hitting/callbacks.py tests/test_hitting_dash.py
git commit -m "feat(hitting): wire Balls in Play + Last 27 PA tabs with hit-type filter"
```

---

### Task H5: Full-suite + live smoke

- [ ] **Step 1:** `python -m pytest -q` → all green.
- [ ] **Step 2: In-process smoke** (do not disturb any running server):

```python
from app.data import hitting_wh
from app.db import query_df
r = query_df("SELECT batter_tm_id, game_id FROM fact_tm_game_pitch WHERE batter_team='LOY_LIO' AND pitch_call='InPlay' AND bearing IS NOT NULL LIMIT 1").iloc[0]
bid, gid = int(r["batter_tm_id"]), int(r["game_id"])
bip = hitting_wh.wh_bip_points(bid, gid)
print("bip rows:", len(bip), "| cols:", list(bip.columns))
last = hitting_wh.wh_last_n_pas(bid, 27)
print("last27 pitches:", len(last), "| distinct PAs:", len(last[["GameID","Inning","PAofInning"]].drop_duplicates()) if not last.empty else 0)
from app.dashboards.hitting import charts
print("radial ok:", type(charts.radial_fig(bip)).__name__, "| spray ok:", type(charts.spray_fig(bip)).__name__)
```
Expected: non-zero bip rows, ≤27 distinct PAs, both figures are `Figure`.

- [ ] **Step 3:** Commit any smoke fixes if needed.

## Notes for the implementer
- `_render_tab` in hitting already receives `sel` as a `State`; the two new branches go before the existing `game`/`pa`/`zone` branches.
- `balls_in_play._chip_style` and `charts._HIT_COLORS` are reused by the style callback — reference them as shown (`balls_in_play._chip_style`, `balls_in_play.charts._HIT_COLORS`).
- Do not modify existing transforms or `_finish`; the BIP charts use the dedicated `wh_bip_points` query.
