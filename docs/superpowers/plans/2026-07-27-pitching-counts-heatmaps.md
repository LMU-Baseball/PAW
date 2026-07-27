# Pitching Counts + Heatmaps Tabs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add two analytical tabs to the pitching dashboard — **Counts** (pitch usage + location filtered by count state) and **Heatmaps** (2-D location density heatmap filtered by pitch type / batter side / count).

**Architecture:** One new Plotly figure (`fig_heatmap`) + one helper (`count_states`) in `app/data/pitching.py`; two tab modules; two `_render_tab` branches + two filter callbacks in the pitching `callbacks.py`. Both tabs render from the existing loaded game-data df (no new queries), reusing `fig_location`, `pitch_usage`, `pitch_type`, `_add_zone`, `_base_layout`, and `tables.df_table`.

**Tech Stack:** Python, Dash (`dcc.Dropdown`, `dcc.Graph`, `dash_table`), Plotly `graph_objects` (`Histogram2dContour`), pandas, pytest.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-27-pitching-counts-heatmaps-design.md`. Branch `feat/pitch-level-video`.
- The game-data df has columns: `balls`, `strikes`, `plate_loc_side`, `plate_loc_height`, `batter_side`, `tagged_pitch_type`, `pitch_call`, `rel_speed`, etc. (warehouse names).
- Count state string = `f"{balls}-{strikes}"`.
- Reuse (all in `app/data/pitching.py`): `pitch_type(df)`, `pitch_color(pt)`, `pitch_usage(df)` (cols `pitch`/`count`/`usage_pct`), `fig_location(df)`, `_add_zone(fig)`, `_base_layout(fig, title)`. In `app/dashboards/pitching`: `tables.df_table(df, id_=, color_col="Pitch")`, `shell.section(title)`.
- Colors: crimson `#9A0021`, font `Teko, sans-serif`. Tests may use synthetic DataFrames (no DB needed for figures). Full suite stays green. Run `python -m pytest -q`.
- The pitching `dcc.Tabs` already has tabs: `breakdown`, `location`, `splits`, `outings`, `pitchlevel` (Pitch Level from sub-project V). Add the two new tabs after `pitchlevel`.

---

### Task 1: `count_states` + `fig_heatmap` in `app/data/pitching.py`

**Files:**
- Modify: `app/data/pitching.py` (append near the other `fig_*` functions; `go`, `pd` and `_add_zone`/`_base_layout` are already defined in the module)
- Test: `tests/test_pitching.py` (append)

**Interfaces — Produces:**
- `count_states(df) -> list[str]` — sorted distinct `"{balls}-{strikes}"` present (drops NA counts).
- `fig_heatmap(df) -> go.Figure` — empty-safe density heatmap.

- [ ] **Step 1: Write the failing test** (append to `tests/test_pitching.py`)

```python
def test_count_states_and_heatmap():
    import pandas as pd
    import plotly.graph_objects as go
    from app.data import pitching as P
    df = pd.DataFrame({
        "balls": [0, 1, 0], "strikes": [0, 2, 0],
        "plate_loc_side": [0.1, -0.4, 0.2], "plate_loc_height": [2.5, 3.0, 2.2],
        "pitch_call": ["StrikeCalled", "BallCalled", "InPlay"],
        "tagged_pitch_type": ["Fastball", "Slider", "Fastball"]})
    assert P.count_states(df) == ["0-0", "1-2"]
    assert isinstance(P.fig_heatmap(df), go.Figure)
    # empty-safe
    assert isinstance(P.fig_heatmap(df.iloc[0:0]), go.Figure)
```

- [ ] **Step 2: Run test** — `python -m pytest tests/test_pitching.py -k count_states_and_heatmap -q` → FAIL.

- [ ] **Step 3: Implement** (append to `app/data/pitching.py`)

```python
def count_states(df: pd.DataFrame) -> list[str]:
    """Sorted distinct '{balls}-{strikes}' count states present in df."""
    if df is None or df.empty:
        return []
    cs = (df["balls"].astype("Int64").astype(str) + "-"
          + df["strikes"].astype("Int64").astype(str))
    return sorted(c for c in cs.dropna().unique() if "<NA>" not in c)


def fig_heatmap(df: pd.DataFrame) -> go.Figure:
    """White->yellow->red 2-D density heatmap of plate locations, over the zone."""
    d = df.dropna(subset=["plate_loc_side", "plate_loc_height"]) if df is not None else None
    fig = go.Figure()
    if d is not None and not d.empty:
        fig.add_trace(go.Histogram2dContour(
            x=d["plate_loc_side"], y=d["plate_loc_height"],
            colorscale=[[0.0, "white"], [0.5, "yellow"], [1.0, "red"]],
            contours=dict(coloring="fill"), line=dict(width=0),
            showscale=False, ncontours=18, hoverinfo="skip"))
    _add_zone(fig)
    fig.update_xaxes(title="Plate Side (ft)", range=[-2.5, 2.5])
    fig.update_yaxes(title="Plate Height (ft)", range=[0, 5], scaleanchor="x")
    return _base_layout(fig, "Location Heatmap (Catcher View)")
```

- [ ] **Step 4: Run tests** — `python -m pytest tests/test_pitching.py -k count_states_and_heatmap -q` → PASS.
- [ ] **Step 5: Commit**

```bash
git add app/data/pitching.py tests/test_pitching.py
git commit -m "feat(pitching): count_states helper + fig_heatmap density figure"
```

---

### Task 2: Tab modules `counts` + `heatmaps`

**Files:**
- Create: `app/dashboards/pitching/tabs/counts.py`
- Create: `app/dashboards/pitching/tabs/heatmaps.py`
- Test: `tests/test_pitching_dash.py` (append)

**Interfaces — Produces:**
- `counts.count_options(df)`, `counts.body(df)`, `counts.render(df)`.
- `heatmaps.body(df)`, `heatmaps.render(df)`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_pitching_dash.py`)

```python
def _pitch_df():
    import pandas as pd
    return pd.DataFrame({
        "balls": [0, 1], "strikes": [0, 2],
        "plate_loc_side": [0.1, -0.3], "plate_loc_height": [2.5, 3.0],
        "pitch_call": ["StrikeCalled", "BallCalled"], "batter_side": ["Right", "Left"],
        "tagged_pitch_type": ["Fastball", "Slider"], "rel_speed": [92.0, 84.0]})


def test_counts_tab_render_has_dropdown_and_body():
    from app.dashboards.pitching.tabs import counts
    out = counts.render(_pitch_df())
    s = str(out)
    assert "counts-dd" in s and "counts-body" in s
    # empty df -> empty state, no exception
    import pandas as pd
    assert "No pitches" in str(counts.body(pd.DataFrame(
        {"balls": [], "strikes": [], "plate_loc_side": [], "plate_loc_height": [],
         "pitch_call": [], "tagged_pitch_type": []})))


def test_heatmaps_tab_render_has_controls_and_body():
    from app.dashboards.pitching.tabs import heatmaps
    out = heatmaps.render(_pitch_df())
    s = str(out)
    assert "hm-pt" in s and "hm-side" in s and "hm-count" in s and "hm-body" in s
```

- [ ] **Step 2: Run test** — `python -m pytest tests/test_pitching_dash.py -k "counts_tab or heatmaps_tab" -q` → FAIL.

- [ ] **Step 3: Implement**

```python
# app/dashboards/pitching/tabs/counts.py
"""Counts tab: count-state multiselect -> pitch usage table + location scatter."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import pitching as P
from app.dashboards.pitching import tables
from app.dashboards.shell import section


def count_options(df: pd.DataFrame) -> list[dict]:
    return [{"label": c, "value": c} for c in P.count_states(df)]


def _usage_display(df: pd.DataFrame) -> pd.DataFrame:
    return P.pitch_usage(df).rename(
        columns={"pitch": "Pitch", "count": "Count", "usage_pct": "Usage %"})


def body(df: pd.DataFrame) -> html.Div:
    if df is None or df.empty:
        return html.Div("No pitches for the selected counts.",
                        style={"padding": "12px", "color": "#555"})
    return html.Div([
        html.Div([section("Pitch Usage"),
                  tables.df_table(_usage_display(df), id_="counts-usage", color_col="Pitch")],
                 style={"flex": "1"}),
        html.Div([section("Location"), dcc.Graph(figure=P.fig_location(df))],
                 style={"flex": "1"}),
    ], style={"display": "flex", "gap": "16px"})


def render(df: pd.DataFrame) -> html.Div:
    opts = count_options(df)
    return html.Div([
        dcc.Dropdown(id="counts-dd", options=opts, value=[o["value"] for o in opts],
                     multi=True, placeholder="Count state(s)",
                     style={"maxWidth": "460px", "margin": "6px 0"}),
        html.Div(id="counts-body", children=body(df)),
    ])
```

```python
# app/dashboards/pitching/tabs/heatmaps.py
"""Heatmaps tab: pitch-type / batter-side / count filters -> density heatmap."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import pitching as P


def body(df: pd.DataFrame) -> html.Div:
    return html.Div(dcc.Graph(figure=P.fig_heatmap(df)))


def render(df: pd.DataFrame) -> html.Div:
    pts = list(P.pitch_type(df).dropna().unique()) if df is not None and not df.empty else []
    counts = P.count_states(df) if df is not None else []
    return html.Div([
        html.Div([
            dcc.Dropdown(id="hm-pt", options=[{"label": p, "value": p} for p in pts],
                         value=pts, multi=True, placeholder="Pitch type(s)",
                         style={"minWidth": "220px"}),
            dcc.Dropdown(id="hm-side",
                         options=[{"label": s, "value": s} for s in ("All", "Right", "Left")],
                         value="All", clearable=False, style={"minWidth": "140px"}),
            dcc.Dropdown(id="hm-count", options=[{"label": c, "value": c} for c in counts],
                         value=counts, multi=True, placeholder="Count(s)",
                         style={"minWidth": "220px"}),
        ], style={"display": "flex", "gap": "12px", "margin": "6px 0",
                  "flexWrap": "wrap"}),
        html.Div(id="hm-body", children=body(df)),
    ])
```

- [ ] **Step 4: Run tests** — `python -m pytest tests/test_pitching_dash.py -k "counts_tab or heatmaps_tab" -q` → PASS.
- [ ] **Step 5: Commit**

```bash
git add app/dashboards/pitching/tabs/counts.py app/dashboards/pitching/tabs/heatmaps.py tests/test_pitching_dash.py
git commit -m "feat(pitching): Counts + Heatmaps tab modules"
```

---

### Task 3: Wire tabs into the pitching dashboard

**Files:**
- Modify: `app/dashboards/pitching/layout.py` (tabs list ~line 105)
- Modify: `app/dashboards/pitching/callbacks.py` (tab imports; `_render_tab` branches; two new callbacks)
- Test: `tests/test_pitching_dash.py` (append)

- [ ] **Step 1: Write the failing test** (append to `tests/test_pitching_dash.py`)

```python
def test_pitching_tabs_include_counts_and_heatmaps():
    import inspect
    from app.dashboards.pitching import layout
    src = inspect.getsource(layout.serve_layout)
    assert '"counts"' in src and "Counts" in src
    assert '"heatmaps"' in src and "Heatmaps" in src
```

- [ ] **Step 2: Run test** — `python -m pytest tests/test_pitching_dash.py -k counts_and_heatmaps -q` → FAIL.

- [ ] **Step 3: Implement**

In `app/dashboards/pitching/layout.py`, extend the tabs (keep existing ones incl. Pitch Level):

```python
    tabs = dcc.Tabs(id="tabs", value="breakdown", children=[
        dcc.Tab(label="Pitch Breakdown", value="breakdown"),
        dcc.Tab(label="Location / Movement", value="location"),
        dcc.Tab(label="RHH v. LHH", value="splits"),
        dcc.Tab(label="Last Outings", value="outings"),
        dcc.Tab(label="Pitch Level", value="pitchlevel"),
        dcc.Tab(label="Counts", value="counts"),
        dcc.Tab(label="Heatmaps", value="heatmaps"),
    ])
```

In `app/dashboards/pitching/callbacks.py`:

(a) Extend the tabs import to add the two modules:
```python
from app.dashboards.pitching.tabs import (last_outings, location_movement,
                                          pitch_breakdown, rhh_lhh, counts, heatmaps)
```

(b) Add two branches to `_render_tab`, after the existing `splits` branch and before the final `return html.Div()` (they use the game-data `df`, so they belong after the `df.empty` guard):
```python
        if tab == "counts":
            return counts.render(df)
        if tab == "heatmaps":
            return heatmaps.render(df)
```

(c) Add two callbacks inside `register_callbacks` (before the final `videotab.register_callbacks(...)` / `notes_ui.register_note_callbacks(...)` lines):
```python
    @dash_app.callback(
        Output("counts-body", "children"),
        Input("counts-dd", "value"), State("game-data", "data"),
    )
    def _counts_body(sel_counts, data_json):
        df = _read_game_df(data_json)
        if df.empty:
            return html.Div("No pitch data.")
        if sel_counts is not None:
            cs = (df["balls"].astype("Int64").astype(str) + "-"
                  + df["strikes"].astype("Int64").astype(str))
            df = df[cs.isin(sel_counts)]
        return counts.body(df)

    @dash_app.callback(
        Output("hm-body", "children"),
        Input("hm-pt", "value"), Input("hm-side", "value"), Input("hm-count", "value"),
        State("game-data", "data"),
    )
    def _hm_body(pts, side, sel_counts, data_json):
        df = _read_game_df(data_json)
        if df.empty:
            return html.Div("No pitch data.")
        if pts is not None:
            df = df[P.pitch_type(df).isin(pts)]
        if side and side != "All":
            df = df[df["batter_side"] == side]
        if sel_counts is not None:
            cs = (df["balls"].astype("Int64").astype(str) + "-"
                  + df["strikes"].astype("Int64").astype(str))
            df = df[cs.isin(sel_counts)]
        return heatmaps.body(df)
```

- [ ] **Step 4: Run tests** — `python -m pytest tests/test_pitching_dash.py -q` → PASS.
- [ ] **Step 5: Commit**

```bash
git add app/dashboards/pitching/layout.py app/dashboards/pitching/callbacks.py tests/test_pitching_dash.py
git commit -m "feat(pitching): wire Counts + Heatmaps tabs"
```

---

### Task 4: Full-suite + live smoke

- [ ] **Step 1:** `python -m pytest -q` → all green.
- [ ] **Step 2: In-process smoke:**

```python
from app.data import pitching as P
from app.db import query_df
# a game/pitcher with pitches
gp = query_df("SELECT game_id, pitcher_id FROM fact_tm_game_pitch WHERE pitcher_team='LOY_LIO' LIMIT 1").iloc[0]
df = P.game_pitches_for(int(gp["game_id"]), int(gp["pitcher_id"]))
print("count states:", P.count_states(df))
print("heatmap ok:", type(P.fig_heatmap(df)).__name__)
from app.dashboards.pitching.tabs import counts, heatmaps
print("counts body ok:", "Usage" in str(counts.body(df)))
print("heatmaps render ok:", "hm-body" in str(heatmaps.render(df)))
```
Expected: non-empty count states, a `Figure`, both tabs render.

- [ ] **Step 3:** Commit any smoke fixes if needed.

## Notes for the implementer
- `_render_tab` in pitching keeps its existing `outings`/`pitchlevel` branches (which run before the empty guard) untouched; the new `counts`/`heatmaps` branches go with the df-based branches (after the guard).
- Do not remove or reorder existing tabs or callbacks.
- `P` (`app.data.pitching`) and `_read_game_df` are already imported in `callbacks.py`.
