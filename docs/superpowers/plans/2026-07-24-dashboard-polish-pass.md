# Dashboard Polish Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply nine grouped UI/UX refinements across the four Dash dashboards (chrome, HitTrax practice, pitching, catching) driven by coach screenshots.

**Architecture:** Small targeted edits to existing pure data helpers (`app/data/*.py`), Plotly chart builders (`charts.py` / figure functions in `pitching.py`), Dash tab render functions, layouts, and callbacks. One substantial new component: the HitTrax batted-ball distribution fan. Data helpers stay pure and unit-tested; Dash render/layout functions get structural smoke tests following the existing repo convention (`inspect.getsource` + "renders without error").

**Tech Stack:** Python, Flask + Dash, Plotly (graph_objects / make_subplots), pandas, numpy, pytest.

## Global Constraints

- Brand crimson = `#9A0021`; brand blue = `#0076A5`. Do not introduce new brand hues.
- Fan color scale = brand crimson sequential (light `rgb(253,234,238)` → `#9A0021`). NOT the mockup's brown.
- Hit-type colors (canonical, one source): Ground Ball `#7a5230`, Line Drive `#9A0021`, Fly Ball `#0076A5`, Miss/Foul `#5a5a5a`.
- Pitching conventions (colored pitch column, labeled hovers, movement ellipses) apply to the **pitching dashboard only** this round.
- Font family on all figures stays `"Teko, sans-serif"`.
- Fan geometry constants are provisional (coach-confirmable): direction wedge edges `[-45,-27,-9,9,27,45]°`; ring distance edges `Infield 0–150 / Outfield 150–330 / Deep+HR >330 ft`.
- No new dependencies. No new DB queries. No role/permission changes.
- Do NOT run `git stash/reset/checkout/clean` (Memory §3c process lesson). Only `git add <named files>` + commit.
- Restart the dev server by **port owner** (`Get-NetTCPConnection -LocalPort 8050 -State Listen`), never by process name (Memory §3b GOTCHA).
- Run the full suite with `python -m pytest -q` (currently 271 passing; must stay green).

---

### Task 1: Global chrome — hitting back-link + footnote colors

**Files:**
- Modify: `app/dashboards/hitting/layout.py` (the `header()` call ~line 120; footnote `#888` ~line 49-50)
- Modify: `app/dashboards/pitching/layout.py` (footnote `#888` ~line 41-42)
- Test: `tests/test_hitting_dash.py` (append)

**Interfaces:**
- Consumes: `shell.header(back_href, back_label)` (already supports both params).
- Produces: nothing new; behavioral tweak only.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_hitting_dash.py`:

```python
def test_hitting_layout_has_back_link_and_dark_footnote():
    import inspect
    from app.dashboards.hitting import layout
    src = inspect.getsource(layout)
    # header called with the /hitting back-link
    assert 'back_href="/hitting"' in src
    # provisional footnote no longer uses the too-light #888
    assert '"Slash line = warehouse game data (provisional)."' in src
    footnote_idx = src.index('"Slash line = warehouse game data (provisional)."')
    # the style dict immediately after the footnote uses #555, not #888
    tail = src[footnote_idx:footnote_idx + 300]
    assert '"#555"' in tail and '"#888"' not in tail
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_hitting_dash.py::test_hitting_layout_has_back_link_and_dark_footnote -v`
Expected: FAIL (currently `header()` has no back_href and footnote is `#888`).

- [ ] **Step 3: Implement**

In `app/dashboards/hitting/layout.py`, change the header call inside `serve_layout`:

```python
        header(back_href="/hitting", back_label="← Hitting"),
```

Change the hitting sidebar footnote style:

```python
        html.Div("Slash line = warehouse game data (provisional).",
                 style={"fontSize": "12px", "color": "#555", "marginTop": "4px"}),
```

In `app/dashboards/pitching/layout.py`, change the pitching sidebar footnote style:

```python
        html.Div("Season totals = warehouse (provisional).",
                 style={"fontSize": "12px", "color": "#555", "marginTop": "4px"}),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_hitting_dash.py::test_hitting_layout_has_back_link_and_dark_footnote -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/hitting/layout.py app/dashboards/pitching/layout.py tests/test_hitting_dash.py
git commit -m "feat(dash): hitting back-link + darker sidebar footnote"
```

---

### Task 2: Catching Static Framing — max two facets per row

**Files:**
- Modify: `app/dashboards/catching/charts.py::framing_facets`
- Test: `tests/test_catching_dash.py` (append)

**Interfaces:**
- Consumes: existing `_zone_frame`, `_scatter_traces`, `_base_axes`, `C.add_framing_cols`.
- Produces: `framing_facets(df, by, title)` unchanged signature; now a `ceil(n/2)`-row × `min(2,n)`-col grid.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_catching_dash.py` (add `import math` / `import pandas as pd` if not present):

```python
def test_framing_facets_wraps_to_two_columns():
    import pandas as pd
    from app.dashboards.catching import charts
    # four Zone values -> should be a 2x2 grid (2 rows), not 1x4
    df = pd.DataFrame([
        {"plate_loc_side": s, "plate_loc_height": h, "izt_zone": z,
         "pitch_call": "StrikeCalled", "batter_side": "Right",
         "pitcher_throws": "Right", "rel_speed": 90.0}
        for s, h, z in [(-0.5, 2.5, "1"), (0.5, 2.5, "Ball"),
                        (-0.9, 2.0, "Shadow"), (0.9, 3.0, "5")]
    ])
    fig = charts.framing_facets(df, by="Zone", title="Zone Location")
    # 4 subplots across 2 columns => 2 rows => 4 xaxis objects, y range spans 2 rows
    n_xaxes = len([k for k in fig.layout if k.startswith("xaxis")])
    assert n_xaxes == 4
    # rows=2 => the grid height grows beyond a single-row figure
    assert fig.layout.height and fig.layout.height >= 700
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_catching_dash.py::test_framing_facets_wraps_to_two_columns -v`
Expected: FAIL (currently `rows=1`, height 380).

- [ ] **Step 3: Implement**

Replace `framing_facets` in `app/dashboards/catching/charts.py` with:

```python
def framing_facets(df: pd.DataFrame, by: str, title: str) -> go.Figure:
    import math
    d = C.add_framing_cols(df) if not df.empty and "CallType" not in df.columns else df
    vals = sorted(d[by].dropna().unique()) if not d.empty and by in d.columns else []
    n = max(1, len(vals))
    ncols = min(2, n)
    nrows = math.ceil(n / ncols)
    fig = make_subplots(rows=nrows, cols=ncols,
                        subplot_titles=[str(v) for v in vals] or [title],
                        vertical_spacing=0.12, horizontal_spacing=0.06)
    shown = set()
    for i, v in enumerate(vals):
        r, c = i // ncols + 1, i % ncols + 1
        _zone_frame(fig, row=r, col=c)
        _scatter_traces(fig, d[d[by] == v], row=r, col=c, shown=shown)
        _base_axes(fig, row=r, col=c)
        idx = (r - 1) * ncols + c  # make_subplots axis numbering (row-major)
        fig.update_yaxes(scaleanchor=("x" if idx == 1 else f"x{idx}"),
                         scaleratio=1, row=r, col=c)
    if not vals:
        _zone_frame(fig, row=1, col=1); _base_axes(fig, row=1, col=1)
        fig.update_yaxes(scaleanchor="x", scaleratio=1, row=1, col=1)
    fig.update_layout(
        title=title, height=360 * nrows, margin=dict(l=10, r=10, t=60, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"),
    )
    return fig
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_catching_dash.py::test_framing_facets_wraps_to_two_columns -v`
Expected: PASS

- [ ] **Step 5: Run the catching suite to confirm no regressions**

Run: `python -m pytest tests/test_catching_dash.py tests/test_catching.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/dashboards/catching/charts.py tests/test_catching_dash.py
git commit -m "feat(catching): wrap static-framing facets to two per row"
```

---

### Task 3: Pitching — colored pitch names in tables

**Files:**
- Modify: `app/dashboards/pitching/tables.py::df_table`
- Test: `tests/test_pitching_dash.py` (append)

**Interfaces:**
- Consumes: `app.data.pitching.pitch_color(pt) -> str`.
- Produces: `df_table(df, id_=None, color_col="Pitch")` — adds `style_data_conditional` coloring the `color_col` cell text per pitch type; no-op when `color_col` not in `df.columns`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pitching_dash.py`:

```python
def test_df_table_colors_pitch_column():
    import pandas as pd
    from app.dashboards.pitching import tables
    from app.data import pitching as P
    df = pd.DataFrame({"Pitch": ["Fastball", "Sweeper"], "Velo": [90.0, 80.0]})
    tbl = tables.df_table(df, id_="t")
    conds = tbl.style_data_conditional or []
    # one colored rule per distinct pitch, each carrying that pitch's color
    colored = {c.get("color") for c in conds if c.get("column_id") == "Pitch"}
    assert P.pitch_color("Fastball") in colored
    assert P.pitch_color("Sweeper") in colored


def test_df_table_no_pitch_column_no_color_rules():
    import pandas as pd
    from app.dashboards.pitching import tables
    df = pd.DataFrame({"Metric": ["Strike%"], "Value": [55.0]})
    tbl = tables.df_table(df, id_="t2")
    conds = tbl.style_data_conditional or []
    assert not any(c.get("column_id") == "Pitch" for c in conds)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pitching_dash.py::test_df_table_colors_pitch_column -v`
Expected: FAIL (`style_data_conditional` not set; `color_col` param absent).

- [ ] **Step 3: Implement**

Replace `app/dashboards/pitching/tables.py` with:

```python
"""Dash DataTable builders for the pitching dashboard."""
from __future__ import annotations

import pandas as pd
from dash import dash_table

from app.data import pitching as P


def df_table(df: pd.DataFrame, id_: str | None = None, color_col: str = "Pitch"):
    conditional = []
    if color_col in df.columns:
        for pt in df[color_col].dropna().unique():
            conditional.append({
                "if": {"filter_query": f'{{{color_col}}} = "{pt}"',
                       "column_id": color_col},
                "color": P.pitch_color(str(pt)),
                "fontWeight": "bold",
            })
    return dash_table.DataTable(
        id=id_ or "pitching-table",
        columns=[{"name": str(c), "id": str(c)} for c in df.columns],
        data=df.to_dict("records"),
        style_table={"overflowX": "auto"},
        style_cell={"fontFamily": "Teko, sans-serif", "fontSize": "15px",
                    "padding": "4px 8px", "textAlign": "center"},
        style_header={"backgroundColor": "#9A0021", "color": "white",
                      "fontWeight": "bold"},
        style_data_conditional=conditional,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_pitching_dash.py::test_df_table_colors_pitch_column tests/test_pitching_dash.py::test_df_table_no_pitch_column_no_color_rules -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/pitching/tables.py tests/test_pitching_dash.py
git commit -m "feat(pitching): color pitch-column cell text to match chart colors"
```

---

### Task 4: Pitching — labeled hover tooltips

**Files:**
- Modify: `app/data/pitching.py` (`fig_velo_by_pitch`, `fig_movement`, `fig_velo_by_inning`, `fig_outings_velo_trend`)
- Test: `tests/test_pitching.py` (append)

**Interfaces:**
- Produces: each listed figure's data traces carry an explicit `hovertemplate` with labeled fields (no raw `(x, y)`).

Note: `fig_movement` marker traces get their hovertemplate here in Task 4; Task 5 adds ellipse traces to the same figure (ellipses use `hoverinfo="skip"`). Keep both consistent.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pitching.py`:

```python
def test_pitching_figs_have_labeled_hovers():
    import pandas as pd
    from app.data import pitching as P
    df = pd.DataFrame({
        "pitch_no": [1, 2, 3, 4],
        "rel_speed": [90.0, 89.0, 80.0, 81.0],
        "horz_break": [-10.0, -9.0, 12.0, 11.0],
        "induced_vert_break": [22.0, 21.0, 4.0, 5.0],
        "inning": [1, 1, 2, 2],
        "auto_pitch_type": ["Fastball", "Fastball", "Sweeper", "Sweeper"],
        "tagged_pitch_type": ["Fastball", "Fastball", "Sweeper", "Sweeper"],
    })
    velo = P.fig_velo_by_pitch(df)
    assert any("Pitch No:" in (t.hovertemplate or "") for t in velo.data)
    assert any("Velo:" in (t.hovertemplate or "") for t in velo.data)
    mv = P.fig_movement(df)
    assert any("HB:" in (t.hovertemplate or "") and "IVB:" in (t.hovertemplate or "")
               for t in mv.data)
    inn = P.fig_velo_by_inning(df)
    assert any("Avg Velo:" in (t.hovertemplate or "") for t in inn.data)
```

(If your warehouse schema uses a different pitch-type column than `auto_pitch_type`/`tagged_pitch_type`, `pitch_type(df)` already resolves it — the test only needs the columns `pitch_type` reads. Inspect `P.pitch_type` and include whichever column it uses; the two above cover the common cases.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pitching.py::test_pitching_figs_have_labeled_hovers -v`
Expected: FAIL (no hovertemplates set today).

- [ ] **Step 3: Implement**

In `app/data/pitching.py`:

`fig_velo_by_pitch` — add a hovertemplate to the per-type trace:

```python
    for pt, sub in d.groupby("_pt"):
        fig.add_trace(go.Scatter(x=sub["_seq"], y=sub["rel_speed"],
                                 mode="markers+lines", name=pt,
                                 marker=dict(color=pitch_color(pt)),
                                 line=dict(color=pitch_color(pt)),
                                 hovertemplate=("Pitch No: %{x}<br>"
                                                "Velo: %{y:.1f} mph<br>"
                                                f"{pt}<extra></extra>")))
```

`fig_movement` — add a hovertemplate to the marker trace (ellipses come in Task 5):

```python
    for pt, sub in d.groupby("_pt"):
        fig.add_trace(go.Scatter(x=sub["horz_break"], y=sub["induced_vert_break"],
                                 mode="markers", name=pt,
                                 marker=dict(color=pitch_color(pt), size=9),
                                 hovertemplate=(f"{pt}<br>HB: %{{x:.1f}} in<br>"
                                                "IVB: %{y:.1f} in<extra></extra>")))
```

`fig_velo_by_inning` — add to the Bar:

```python
    fig = go.Figure(go.Bar(x=g["inning"], y=g["rel_speed"].round(1),
                           hovertemplate=("Inning %{x}<br>"
                                          "Avg Velo: %{y:.1f} mph<extra></extra>")))
```

`fig_outings_velo_trend` — add to both lines:

```python
        fig.add_trace(go.Scatter(x=d["game_date"], y=d["appearance_avg_velo"].round(1),
                                 mode="markers+lines", name="Avg Velo",
                                 line=dict(color="#0076A5"),
                                 hovertemplate=("Date: %{x}<br>"
                                                "Avg Velo: %{y:.1f} mph<extra></extra>")))
        fig.add_trace(go.Scatter(x=d["game_date"], y=d["appearance_max_velo"].round(1),
                                 mode="markers+lines", name="Max Velo",
                                 line=dict(color="#9A0021"),
                                 hovertemplate=("Date: %{x}<br>"
                                                "Max Velo: %{y:.1f} mph<extra></extra>")))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_pitching.py::test_pitching_figs_have_labeled_hovers -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/data/pitching.py tests/test_pitching.py
git commit -m "feat(pitching): labeled hover tooltips on velo/movement/inning/outings figs"
```

---

### Task 5: Pitching — 1σ movement ellipses

**Files:**
- Modify: `app/data/pitching.py` (`fig_movement`; add `_rgba` + `_cov_ellipse` helpers)
- Test: `tests/test_pitching.py` (append)

**Interfaces:**
- Consumes: `pitch_color(pt)`.
- Produces: `fig_movement` gains one translucent `fill="toself"` ellipse trace per pitch type with ≥3 non-degenerate points, drawn under the markers, `hoverinfo="skip"`, `showlegend=False`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pitching.py`:

```python
def test_fig_movement_has_one_ellipse_per_pitch_type():
    import pandas as pd
    from app.data import pitching as P
    rows = []
    for pt, hb0, ivb0 in [("Fastball", -10, 22), ("Sweeper", 12, 4)]:
        for k in range(4):
            rows.append({"horz_break": hb0 + k, "induced_vert_break": ivb0 + k,
                         "auto_pitch_type": pt, "tagged_pitch_type": pt})
    df = pd.DataFrame(rows)
    fig = P.fig_movement(df)
    ellipses = [t for t in fig.data if getattr(t, "fill", None) == "toself"]
    assert len(ellipses) == 2  # one per pitch type
    # markers still present (mode='markers')
    assert any(t.mode == "markers" for t in fig.data)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pitching.py::test_fig_movement_has_one_ellipse_per_pitch_type -v`
Expected: FAIL (no ellipse traces today).

- [ ] **Step 3: Implement**

In `app/data/pitching.py`, add helpers near the other figure helpers:

```python
def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _cov_ellipse(x, y, n_std: float = 1.0, n_pts: int = 40):
    """(xs, ys) polygon for the n_std covariance ellipse of points (x, y),
    or None if <3 points or a degenerate covariance."""
    import numpy as np
    x = np.asarray(x, dtype=float); y = np.asarray(y, dtype=float)
    if len(x) < 3:
        return None
    cov = np.cov(x, y)
    if not np.all(np.isfinite(cov)):
        return None
    vals, vecs = np.linalg.eigh(cov)
    if np.any(vals <= 0):
        return None
    t = np.linspace(0, 2 * np.pi, n_pts)
    circle = np.stack([np.cos(t), np.sin(t)])
    ell = (vecs @ (np.sqrt(vals)[:, None] * circle)) * n_std
    return ell[0] + x.mean(), ell[1] + y.mean()
```

Rewrite `fig_movement` to draw ellipses first (under markers), then markers:

```python
def fig_movement(df: pd.DataFrame) -> go.Figure:
    d = df.dropna(subset=["horz_break", "induced_vert_break"]).copy()
    d["_pt"] = pitch_type(d)
    fig = go.Figure()
    # 1-sigma covariance ellipse per pitch type, drawn under the markers
    for pt, sub in d.groupby("_pt"):
        ell = _cov_ellipse(sub["horz_break"], sub["induced_vert_break"])
        if ell is None:
            continue
        xs, ys = ell
        fig.add_trace(go.Scatter(
            x=list(xs) + [xs[0]], y=list(ys) + [ys[0]], mode="lines",
            fill="toself", fillcolor=_rgba(pitch_color(pt), 0.15),
            line=dict(color=pitch_color(pt), width=1),
            name=f"{pt} 1σ", showlegend=False, hoverinfo="skip"))
    for pt, sub in d.groupby("_pt"):
        fig.add_trace(go.Scatter(x=sub["horz_break"], y=sub["induced_vert_break"],
                                 mode="markers", name=pt,
                                 marker=dict(color=pitch_color(pt), size=9),
                                 hovertemplate=(f"{pt}<br>HB: %{{x:.1f}} in<br>"
                                                "IVB: %{y:.1f} in<extra></extra>")))
    fig.update_xaxes(title="Horizontal Break (in)", zeroline=True)
    fig.update_yaxes(title="Induced Vert Break (in)", zeroline=True)
    return _base_layout(fig, "Pitch Movement")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_pitching.py::test_fig_movement_has_one_ellipse_per_pitch_type tests/test_pitching.py::test_pitching_figs_have_labeled_hovers -v`
Expected: PASS (both — the labeled-hover test from Task 4 still holds).

- [ ] **Step 5: Commit**

```bash
git add app/data/pitching.py tests/test_pitching.py
git commit -m "feat(pitching): 1-sigma covariance ellipses on the movement chart"
```

---

### Task 6: Practice — real session dates on the swing-decision trend

**Files:**
- Modify: `app/dashboards/hitting_practice/charts.py::swing_decision_trend_fig` (add `_date_labels` helper)
- Test: `tests/test_hitting_practice_dash.py` (append)

**Interfaces:**
- Produces: `swing_decision_trend_fig` renders human-readable date tick labels regardless of whether `play_date` arrives as `date` objects or as `int64` epoch-ms (the `dcc.Store` JSON round-trip converts dates → epoch-ms; confirmed live).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_hitting_practice_dash.py`:

```python
def test_swing_trend_uses_real_dates_not_epoch():
    import pandas as pd
    from app.dashboards.hitting_practice import charts
    # play_date arriving as int64 epoch-ms (post dcc.Store round-trip)
    df = pd.DataFrame([
        {"play_date": 1774915200000, "in_zone_pct": 80, "chase_pct": 30, "score": 50},
        {"play_date": 1775088000000, "in_zone_pct": 70, "chase_pct": 40, "score": 30},
    ])
    fig = charts.swing_decision_trend_fig(df)
    xs = list(fig.data[0].x)
    # no raw epoch integers on the axis; labels look like dates
    assert all("2026" in str(v) or any(m in str(v) for m in
               ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"])
               for v in xs)
    assert "1774915200000" not in [str(v) for v in xs]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_hitting_practice_dash.py::test_swing_trend_uses_real_dates_not_epoch -v`
Expected: FAIL (`astype(str)` emits `"1774915200000"`).

- [ ] **Step 3: Implement**

In `app/dashboards/hitting_practice/charts.py`, add a helper and use it:

```python
def _date_labels(series: pd.Series) -> pd.Series:
    """Human-readable date labels from either date/datetime values or the
    int64 epoch-ms that a dcc.Store JSON round-trip produces."""
    s = pd.Series(series)
    if pd.api.types.is_numeric_dtype(s):
        dt = pd.to_datetime(s, unit="ms")
    else:
        dt = pd.to_datetime(s, errors="coerce")
    return dt.dt.strftime("%b %d")
```

In `swing_decision_trend_fig`, replace the x assignment and force a category axis:

```python
    if trend_df is not None and not trend_df.empty:
        x = _date_labels(trend_df["play_date"])
        fig.add_trace(go.Scatter(
            x=x, y=trend_df["score"], mode="lines+markers", name="Swing Decision Score",
            line=dict(color=CRIMSON, width=2), marker=dict(color=CRIMSON, size=9)))
        fig.add_hline(y=0, line=dict(color="#bbb", width=1))
    fig.update_layout(
        title="Swing Decision Score by Session (In-Zone % − Chase %)",
        xaxis_title="Session date", yaxis_title="Score",
        xaxis=dict(type="category"),
        height=340, margin=dict(l=40, r=20, t=50, b=40),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"))
    return fig
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_hitting_practice_dash.py::test_swing_trend_uses_real_dates_not_epoch tests/test_hitting_practice_dash.py::test_new_practice_figs_build -v`
Expected: PASS (both).

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/hitting_practice/charts.py tests/test_hitting_practice_dash.py
git commit -m "fix(practice): render real session dates on swing-decision trend"
```

---

### Task 7: Practice — zone chips fixed set, "Zone N" labels, grey empties

**Files:**
- Modify: `app/dashboards/hitting_practice/tabs/swing_frequency.py` (`zone_chip_row`, add `chip_style`)
- Modify: `app/dashboards/hitting_practice/callbacks.py` (`_sfz_toggle`, `_sfz_styles` — add `sfz-present` State)
- Test: `tests/test_hitting_practice_dash.py` (append)

**Interfaces:**
- Produces: `zone_chip_row(df)` renders exactly 13 chips (Zone 1–13), Zone 0 never present, labels `"Zone N"`; empty zones `disabled=True` and excluded from `sfz-active`; a `sfz-present` store lists the enabled zones.
- Produces: `chip_style(active: bool, present: bool) -> dict` shared by the tab and the styles callback.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_hitting_practice_dash.py`:

```python
def test_zone_chip_row_fixed_set_and_labels():
    import pandas as pd
    from dash import html
    from app.dashboards.hitting_practice.tabs import swing_frequency as sf

    def _buttons(node, out):
        if isinstance(node, html.Button):
            out.append(node)
        for k in ([node.children] if not isinstance(getattr(node, "children", None), (list, tuple))
                  else node.children):
            if hasattr(k, "children") or isinstance(k, html.Button):
                _buttons(k, out)
        return out

    # data present only for zones 1,3,5 -> those enabled, the rest greyed
    df = pd.DataFrame([{"zone_section": z} for z in [1, 1, 3, 5]])
    row = sf.zone_chip_row(df)
    btns = _buttons(row, [])
    labels = [b.children for b in btns]
    assert labels == [f"Zone {z}" for z in range(1, 14)]  # 13 chips, Zone N, no Zone 0
    disabled = {b.children: bool(b.disabled) for b in btns}
    assert disabled["Zone 2"] is True and disabled["Zone 1"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_hitting_practice_dash.py::test_zone_chip_row_fixed_set_and_labels -v`
Expected: FAIL (today only present zones render, labeled `Z#`).

- [ ] **Step 3: Implement the tab side**

Replace `zone_chip_row` in `app/dashboards/hitting_practice/tabs/swing_frequency.py` and add `chip_style`:

```python
_ZONES = list(range(1, 14))  # HitTrax standard zones 1-13 (Zone 0 excluded)


def chip_style(active: bool, present: bool) -> dict:
    if not present:                       # zone has no data -> greyed, disabled
        bg, fg, border, cursor, opacity = "#e6e6e6", "#999", "#ccc", "default", "0.6"
    elif active:                          # present + selected
        bg, fg, border, cursor, opacity = "#9A0021", "#fff", "#9A0021", "pointer", "1"
    else:                                 # present + deselected
        bg, fg, border, cursor, opacity = "#fff", "#9A0021", "#9A0021", "pointer", "0.55"
    return {"border": f"2px solid {border}", "background": bg, "color": fg,
            "borderRadius": "12px", "padding": "2px 10px", "margin": "0 4px 4px 0",
            "cursor": cursor, "opacity": opacity,
            "fontFamily": "Teko, sans-serif", "fontSize": "14px"}


def zone_chip_row(df: pd.DataFrame) -> html.Div:
    present = {int(z) for z in df["zone_section"].dropna().unique()} \
        if not df.empty and "zone_section" in df.columns else set(_ZONES)
    chips = [html.Button(
        f"Zone {z}", id={"type": "sfz-chip", "index": z}, n_clicks=0,
        disabled=z not in present, style=chip_style(active=z in present, present=z in present))
        for z in _ZONES]
    active0 = sorted(present)
    return html.Div([dcc.Store(id="sfz-active", data=active0),
                     dcc.Store(id="sfz-present", data=active0),
                     html.Div(chips)], style={"margin": "6px 0"})
```

- [ ] **Step 4: Implement the callback side**

In `app/dashboards/hitting_practice/callbacks.py`, update `_sfz_toggle` to ignore zones that aren't present, and rewrite `_sfz_styles` to read the `sfz-present` store and reuse `chip_style`:

```python
    @dash_app.callback(
        Output("sfz-active", "data"),
        Input({"type": "sfz-chip", "index": ALL}, "n_clicks"),
        State("sfz-active", "data"), State("sfz-present", "data"),
        prevent_initial_call=True,
    )
    def _sfz_toggle(_clicks, active, present):
        tid = ctx.triggered_id
        if not tid:
            return active
        z = tid["index"]
        present = set(present or [])
        if z not in present:                 # disabled/empty zone -> ignore
            return active
        active = list(active or [])
        return [x for x in active if x != z] if z in active else active + [z]

    @dash_app.callback(
        Output({"type": "sfz-chip", "index": ALL}, "style"),
        Input("sfz-active", "data"),
        State("sfz-present", "data"),
        State({"type": "sfz-chip", "index": ALL}, "id"),
    )
    def _sfz_styles(active, present, ids):
        from app.dashboards.hitting_practice.tabs.swing_frequency import chip_style
        active = set(active or [])
        present = set(present or [])
        return [chip_style(active=i["index"] in active, present=i["index"] in present)
                for i in ids]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_hitting_practice_dash.py::test_zone_chip_row_fixed_set_and_labels tests/test_hitting_practice_dash.py::test_swing_frequency_ev_body_zone_filter -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/dashboards/hitting_practice/tabs/swing_frequency.py app/dashboards/hitting_practice/callbacks.py tests/test_hitting_practice_dash.py
git commit -m "feat(practice): fixed zone-chip set (Zone N), grey empty zones"
```

---

### Task 8: Practice — remove Session-type and Exclude-test controls

**Files:**
- Modify: `app/dashboards/hitting_practice/layout.py` (`serve_layout` — drop two filter blocks; drop `sessions` prep)
- Modify: `app/dashboards/hitting_practice/callbacks.py` (`_on_filters` — drop two inputs + session-options output)
- Test: `tests/test_hitting_practice_dash.py` (append)

**Interfaces:**
- Produces: layout no longer contains component ids `prac-session` or `prac-exclude-test`; the `prac-filters` store still seeds `session="All session types"`, `exclude_test=True`; `_on_filters` computes with those fixed values and returns 4 outputs (filters data, player options, daterange start, end).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_hitting_practice_dash.py`:

```python
def test_practice_layout_drops_session_and_exclude_controls():
    import inspect
    from app.dashboards.hitting_practice import layout
    src = inspect.getsource(layout)
    assert 'id="prac-session"' not in src
    assert 'id="prac-exclude-test"' not in src
    # defaults still seeded in the filters store
    assert '"session": "All session types"' in src
    assert '"exclude_test": True' in src


def test_on_filters_signature_dropped_session_exclude():
    import inspect
    from app.dashboards.hitting_practice import callbacks
    src = inspect.getsource(callbacks)
    assert 'Input("prac-session"' not in src
    assert 'Input("prac-exclude-test"' not in src
    assert 'Output("prac-session"' not in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_hitting_practice_dash.py::test_practice_layout_drops_session_and_exclude_controls tests/test_hitting_practice_dash.py::test_on_filters_signature_dropped_session_exclude -v`
Expected: FAIL (both controls/inputs still present).

- [ ] **Step 3: Implement the layout side**

In `app/dashboards/hitting_practice/layout.py::serve_layout`:

Remove the `sessions = [...]` line (no longer needed). Remove the two filter `html.Div` blocks whose children are the `dcc.Dropdown(id="prac-session", ...)` and the `dcc.Checklist(id="prac-exclude-test", ...)`. The `filters` div then contains only Date range, Calendar, and Player. Leave the `prac-filters` store defaults exactly as they are (they already seed `session` and `exclude_test`).

Resulting `filters` block:

```python
    filters = html.Div([
        html.Div([
            html.Label("Date range", style={"color": "white", "fontWeight": "bold"}),
            dcc.Dropdown(
                id="prac-date-preset",
                options=[
                    {"label": "Custom (Swing Decision → today)", "value": "Custom"},
                    {"label": "Past Week", "value": "Past Week"},
                    {"label": "Past Month", "value": "Past Month"},
                    {"label": "Past 3 Months", "value": "Past 3 Months"},
                    {"label": "Past Year", "value": "Past Year"},
                ],
                value="Custom", clearable=False, style={"minWidth": "220px"},
            ),
        ]),
        html.Div([
            html.Label("Calendar", style={"color": "white", "fontWeight": "bold"}),
            dr.date_picker("prac", start.isoformat(), end.isoformat(),
                           min_date=str(min_d), max_date=str(max_d)),
        ]),
        html.Div([
            html.Label("Player", style={"color": "white", "fontWeight": "bold"}),
            dcc.Dropdown(id="prac-player", options=players, value=default_player,
                         clearable=False, disabled=not is_coach and len(players) <= 1,
                         style={"minWidth": "200px"}),
        ]),
    ], style={"display": "flex", "gap": "16px", "alignItems": "flex-end",
              "flexWrap": "wrap", "padding": "12px 16px", "backgroundColor": BANNER})
```

- [ ] **Step 4: Implement the callback side**

Rewrite the `_on_filters` callback in `app/dashboards/hitting_practice/callbacks.py`:

```python
    @dash_app.callback(
        Output("prac-filters", "data"),
        Output("prac-player", "options"),
        Output("prac-daterange", "start_date"),
        Output("prac-daterange", "end_date"),
        Input("prac-date-preset", "value"),
        Input("prac-player", "value"),
        Input("prac-daterange", "start_date"),
        Input("prac-daterange", "end_date"),
    )
    def _on_filters(preset, player, ds, de):
        is_coach = bool(getattr(current_user, "is_coach", False))
        own_name = getattr(current_user, "name", None)
        exclude_test = True
        pitch, _, _, _ = _load_all(exclude_test)
        if ctx.triggered_id == "prac-daterange" and ds and de:
            start = date.fromisoformat(ds[:10])
            end = date.fromisoformat(de[:10])
        else:
            start, end = P.preset_date_range(preset or "Custom")
        windowed = P.apply_filters(pitch, player=None, start=start, end=end, session=None)
        base = windowed if not windowed.empty else pitch
        popts = selectors.player_options(base, is_coach=is_coach, own_name=own_name)
        player = selectors.resolve_player(player, is_coach=is_coach, own_name=own_name)
        if player not in {o["value"] for o in popts} and popts:
            player = popts[0]["value"]
        return (
            {"player": player, "preset": preset or "Custom",
             "session": "All session types", "exclude_test": True,
             "start": start.isoformat(), "end": end.isoformat()},
            popts, start.isoformat(), end.isoformat(),
        )
```

(Downstream callbacks `_load_pitch`, `_render`, `_sidebar` are unchanged — they read `session`/`exclude_test` from the store, which now always hold the fixed values.)

- [ ] **Step 5: Run tests + the practice mount test to confirm the app still builds**

Run: `python -m pytest tests/test_hitting_practice_dash.py -q`
Expected: PASS (all, including `test_build_hitting_practice_dash_mounts`).

- [ ] **Step 6: Commit**

```bash
git add app/dashboards/hitting_practice/layout.py app/dashboards/hitting_practice/callbacks.py tests/test_hitting_practice_dash.py
git commit -m "feat(practice): drop session-type + exclude-test controls (hardcode defaults)"
```

---

### Task 9: Practice — spray data helpers (fan aggregation + scatter fields)

**Files:**
- Modify: `app/data/practice.py` (extend `spray_points`; add `spray_fan` + fan constants; add canonical `HIT_TYPE_COLORS`)
- Test: `tests/test_practice.py` (append)

**Interfaces:**
- Produces: `spray_points(plays) -> DataFrame[x, y, hit_type_label, distance_feet, exit_velocity]` (batted balls 1/2/3).
- Produces: `spray_fan(plays) -> DataFrame[direction, ring, wedge_i, ring_i, a0, a1, r0, r1, count, pct]` — always 15 rows (5 wedges × 3 rings), `pct` = share of batted balls with valid geometry (0 when none). Angles in degrees measured from straightaway center (negative = left field); radii in feet.
- Produces module constants: `FAN_WEDGE_EDGES`, `FAN_DIRECTIONS`, `FAN_RING_EDGES`, `FAN_RINGS`, `FAN_DISPLAY_MAX`, `HIT_TYPE_COLORS`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_practice.py`:

```python
def test_spray_points_carries_distance_and_ev():
    import pandas as pd
    from app.data import practice as P
    plays = pd.DataFrame([
        {"horizontal_angle": -20.0, "distance_feet": 200.0, "exit_velocity": 95.0, "hit_type": 2},
        {"horizontal_angle": 10.0, "distance_feet": 350.0, "exit_velocity": 101.0, "hit_type": 3},
        {"horizontal_angle": 0.0, "distance_feet": 0.0, "exit_velocity": 0.0, "hit_type": 0},
    ])
    pts = P.spray_points(plays)
    assert list(pts.columns) == ["x", "y", "hit_type_label", "distance_feet", "exit_velocity"]
    assert len(pts) == 2  # hit_type 0 excluded
    assert set(pts["exit_velocity"]) == {95.0, 101.0}


def test_spray_fan_15_cells_and_pct_sums_100():
    import pandas as pd
    from app.data import practice as P
    plays = pd.DataFrame([
        {"horizontal_angle": -40.0, "distance_feet": 120.0, "hit_type": 1},   # Left / Infield
        {"horizontal_angle": 0.0, "distance_feet": 200.0, "hit_type": 2},     # Center / Outfield
        {"horizontal_angle": 30.0, "distance_feet": 360.0, "hit_type": 3},    # Right / Deep
        {"horizontal_angle": 5.0, "distance_feet": 50.0, "hit_type": 0},      # excluded (miss)
    ])
    fan = P.spray_fan(plays)
    assert len(fan) == 15
    assert round(fan["pct"].sum(), 1) == 100.0
    assert int(fan["count"].sum()) == 3  # miss excluded
    # empty df -> 15 zero cells, no crash
    fan0 = P.spray_fan(pd.DataFrame(columns=["horizontal_angle", "distance_feet", "hit_type"]))
    assert len(fan0) == 15 and fan0["count"].sum() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_practice.py::test_spray_points_carries_distance_and_ev tests/test_practice.py::test_spray_fan_15_cells_and_pct_sums_100 -v`
Expected: FAIL (`spray_fan` missing; `spray_points` lacks distance/ev columns).

- [ ] **Step 3: Implement**

In `app/data/practice.py`, add canonical colors near `HIT_TYPE_MAP`:

```python
HIT_TYPE_COLORS = {"Ground Ball": "#7a5230", "Line Drive": "#9A0021",
                   "Fly Ball": "#0076A5", "Miss/Foul": "#5a5a5a", "Other": "#5a5a5a"}
```

Add fan constants near the other module constants:

```python
# Batted-ball distribution fan geometry (provisional; coach-confirmable).
FAN_WEDGE_EDGES = [-45.0, -27.0, -9.0, 9.0, 27.0, 45.0]     # 5 wedges (degrees)
FAN_DIRECTIONS = ["Left", "Left-Center", "Center", "Right-Center", "Right"]
FAN_RING_EDGES = [0.0, 150.0, 330.0]                        # inner edges; Deep = >330
FAN_RINGS = ["Infield", "Outfield", "Deep/HR"]
FAN_DISPLAY_MAX = 420.0                                     # outer draw radius for Deep
```

Replace `spray_points`:

```python
def spray_points(plays: pd.DataFrame) -> pd.DataFrame:
    """Batted-ball landing points from horizontal_angle + distance_feet.
    x = dist*sin(angle) (neg=left field), y = dist*cos(angle). Batted balls only
    (hit_type 1/2/3). Carries distance_feet + exit_velocity for hover. PROVISIONAL."""
    cols = ["x", "y", "hit_type_label", "distance_feet", "exit_velocity"]
    if plays.empty or "horizontal_angle" not in plays.columns:
        return pd.DataFrame(columns=cols)
    d = plays[plays["hit_type"].isin([1, 2, 3])].dropna(
        subset=["horizontal_angle", "distance_feet"]).copy()
    if d.empty:
        return pd.DataFrame(columns=cols)
    ang = np.radians(d["horizontal_angle"].astype(float))
    d["x"] = d["distance_feet"].astype(float) * np.sin(ang)
    d["y"] = d["distance_feet"].astype(float) * np.cos(ang)
    d["hit_type_label"] = d["hit_type"].map(HIT_TYPE_MAP)
    if "exit_velocity" not in d.columns:
        d["exit_velocity"] = np.nan
    return d[cols].reset_index(drop=True)
```

Add `spray_fan`:

```python
def spray_fan(plays: pd.DataFrame) -> pd.DataFrame:
    """Aggregate batted balls into a 5-wedge x 3-ring fan (always 15 rows).
    count = balls in each cell; pct = share of all batted balls with valid
    geometry. Geometry bounds (a0/a1 deg, r0/r1 ft) included for drawing.
    PROVISIONAL (wedge/ring cutoffs are coach-confirmable constants)."""
    rows = []
    for wi, direction in enumerate(FAN_DIRECTIONS):
        a0, a1 = FAN_WEDGE_EDGES[wi], FAN_WEDGE_EDGES[wi + 1]
        for ri, ring in enumerate(FAN_RINGS):
            r0 = FAN_RING_EDGES[ri]
            r1 = FAN_RING_EDGES[ri + 1] if ri + 1 < len(FAN_RING_EDGES) else FAN_DISPLAY_MAX
            rows.append({"direction": direction, "ring": ring, "wedge_i": wi,
                         "ring_i": ri, "a0": a0, "a1": a1, "r0": r0, "r1": r1,
                         "count": 0, "pct": 0.0})
    fan = pd.DataFrame(rows)
    if plays.empty or "horizontal_angle" not in plays.columns:
        return fan
    d = plays[plays["hit_type"].isin([1, 2, 3])].dropna(
        subset=["horizontal_angle", "distance_feet"]).copy()
    d = d[d["horizontal_angle"].astype(float).between(-45.0, 45.0)]
    total = len(d)
    if total == 0:
        return fan
    ang = d["horizontal_angle"].astype(float).to_numpy()
    dist = d["distance_feet"].astype(float).to_numpy()
    wedge_i = np.clip(np.digitize(ang, FAN_WEDGE_EDGES[1:-1]), 0, 4)
    ring_i = np.clip(np.digitize(dist, FAN_RING_EDGES[1:]), 0, 2)
    for wi, ri in zip(wedge_i, ring_i):
        m = (fan["wedge_i"] == wi) & (fan["ring_i"] == ri)
        fan.loc[m, "count"] += 1
    fan["pct"] = (100.0 * fan["count"] / total).round(1)
    return fan
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_practice.py::test_spray_points_carries_distance_and_ev tests/test_practice.py::test_spray_fan_15_cells_and_pct_sums_100 -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/data/practice.py tests/test_practice.py
git commit -m "feat(practice): spray_fan aggregation + spray_points distance/EV + hit-type colors"
```

---

### Task 10: Practice — spray charts (fan + upgraded scatter + recolored bar)

**Files:**
- Modify: `app/dashboards/hitting_practice/charts.py` (add `spray_distribution_fan`; upgrade `spray_chart_fig` hover; recolor `contact_type_bar`; point `_HIT_COLORS` at `P.HIT_TYPE_COLORS`)
- Test: `tests/test_hitting_practice_dash.py` (append)

**Interfaces:**
- Consumes: `P.spray_fan`, `P.spray_points`, `P.HIT_TYPE_COLORS`, `P.FAN_*` constants.
- Produces: `spray_distribution_fan(fan_df) -> go.Figure` (one filled polygon per non-empty cell + `%` annotations); `spray_chart_fig(spray_df)` scatter with per-point `Distance` + `Exit Velo` hover; `contact_type_bar(counts_df)` with per-bar hit-type colors.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_hitting_practice_dash.py`:

```python
def test_spray_distribution_fan_builds_cells():
    import pandas as pd
    from app.dashboards.hitting_practice import charts
    from app.data import practice as P
    plays = pd.DataFrame([
        {"horizontal_angle": -30.0, "distance_feet": 120.0, "hit_type": 1},
        {"horizontal_angle": 10.0, "distance_feet": 350.0, "hit_type": 3},
    ])
    fig = charts.spray_distribution_fan(P.spray_fan(plays))
    # at least one filled sector polygon + a % annotation
    assert any(getattr(t, "fill", None) == "toself" for t in fig.data)
    assert fig.layout.annotations and any("%" in a.text for a in fig.layout.annotations)
    # empty fan still renders
    assert charts.spray_distribution_fan(P.spray_fan(pd.DataFrame(
        columns=["horizontal_angle", "distance_feet", "hit_type"]))) is not None


def test_spray_scatter_hover_has_distance_and_ev():
    import pandas as pd
    from app.dashboards.hitting_practice import charts
    spray = pd.DataFrame([{"x": -50.0, "y": 200.0, "hit_type_label": "Line Drive",
                           "distance_feet": 206.2, "exit_velocity": 95.4}])
    fig = charts.spray_chart_fig(spray)
    assert any("Distance:" in (t.hovertemplate or "") and "Exit Velo:" in (t.hovertemplate or "")
               for t in fig.data if t.mode == "markers")


def test_contact_type_bar_uses_hit_type_colors():
    import pandas as pd
    from app.dashboards.hitting_practice import charts
    from app.data import practice as P
    counts = pd.DataFrame([{"Hit Type": "Line Drive", "Count": 10},
                           {"Hit Type": "Fly Ball", "Count": 5}])
    fig = charts.contact_type_bar(counts)
    marker_colors = list(fig.data[0].marker.color)
    assert marker_colors == [P.HIT_TYPE_COLORS["Line Drive"], P.HIT_TYPE_COLORS["Fly Ball"]]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_hitting_practice_dash.py::test_spray_distribution_fan_builds_cells tests/test_hitting_practice_dash.py::test_spray_scatter_hover_has_distance_and_ev tests/test_hitting_practice_dash.py::test_contact_type_bar_uses_hit_type_colors -v`
Expected: FAIL (`spray_distribution_fan` missing; scatter has no distance/ev hover; bar is single crimson).

- [ ] **Step 3: Implement**

In `app/dashboards/hitting_practice/charts.py`:

Point the local color map at the canonical source (replace the `_HIT_COLORS = {...}` line):

```python
from app.data import practice as P  # already imported at top as `P`
_HIT_COLORS = P.HIT_TYPE_COLORS
```

Add the crimson-shade helper and the fan figure:

```python
def _crimson_shade(frac: float) -> str:
    """Light-pink -> brand crimson by fraction 0..1."""
    frac = max(0.0, min(1.0, frac))
    c0, c1 = (253, 234, 238), (154, 0, 33)
    r, g, b = (round(c0[i] + (c1[i] - c0[i]) * frac) for i in range(3))
    return f"rgb({r},{g},{b})"


def _fan_field(fig: go.Figure) -> None:
    L = P.FAN_DISPLAY_MAX
    import numpy as np
    # foul lines from home plate along +/-45 deg
    for sgn in (-1, 1):
        th = np.radians(45.0) * sgn
        fig.add_shape(type="line", x0=0, y0=0, x1=L * np.sin(th), y1=L * np.cos(th),
                      line=dict(color="#888", width=1))
    # outer arc
    ts = np.radians(np.linspace(-45, 45, 40))
    xs, ys = L * np.sin(ts), L * np.cos(ts)
    path = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    fig.add_shape(type="path", path=path, line=dict(color="#888", width=1))


def spray_distribution_fan(fan_df: pd.DataFrame) -> go.Figure:
    """Filled fan: each cell shaded by its share of batted balls + % label."""
    import numpy as np
    fig = go.Figure()
    _fan_field(fig)
    annotations = []
    if fan_df is not None and not fan_df.empty:
        maxpct = max(float(fan_df["pct"].max()), 1e-9)
        for _, row in fan_df.iterrows():
            if row["count"] <= 0:
                continue
            a0, a1 = np.radians(row["a0"]), np.radians(row["a1"])
            r0, r1 = float(row["r0"]), float(row["r1"])
            ts = np.linspace(a0, a1, 12)
            outer = [(r1 * np.sin(t), r1 * np.cos(t)) for t in ts]
            inner = [(r0 * np.sin(t), r0 * np.cos(t)) for t in ts[::-1]]
            poly = outer + inner
            xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
            fig.add_trace(go.Scatter(
                x=xs, y=ys, mode="lines", fill="toself",
                fillcolor=_crimson_shade(float(row["pct"]) / (maxpct)),
                line=dict(color="#bbb", width=0.5), showlegend=False,
                hovertext=f"{row['direction']} · {row['ring']}: "
                          f"{row['pct']:.0f}% ({int(row['count'])})",
                hoverinfo="text"))
            mid_a = (a0 + a1) / 2; mid_r = (r0 + r1) / 2
            annotations.append(dict(x=mid_r * np.sin(mid_a), y=mid_r * np.cos(mid_a),
                                    text=f"{row['pct']:.0f}%", showarrow=False,
                                    font=dict(family="Teko, sans-serif", size=14,
                                              color="#1a1a1a")))
    fig.update_layout(
        title="Batted-Ball Distribution", annotations=annotations,
        xaxis=dict(range=[-P.FAN_DISPLAY_MAX, P.FAN_DISPLAY_MAX], visible=False),
        yaxis=dict(range=[-20, P.FAN_DISPLAY_MAX + 20], visible=False,
                   scaleanchor="x", scaleratio=1),
        height=460, margin=dict(l=10, r=10, t=50, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"))
    return fig
```

Upgrade `spray_chart_fig` — add distance/EV hover via `customdata` (replace the scatter loop and keep the field shapes):

```python
    if spray_df is not None and not spray_df.empty:
        has_hover = {"distance_feet", "exit_velocity"} <= set(spray_df.columns)
        for label, sub in spray_df.groupby("hit_type_label"):
            trace = dict(x=sub["x"], y=sub["y"], mode="markers", name=str(label),
                         marker=dict(color=_HIT_COLORS.get(label, "#5a5a5a"), size=8,
                                     line=dict(width=0.5, color="#666")))
            if has_hover:
                trace["customdata"] = sub[["distance_feet", "exit_velocity"]].to_numpy()
                trace["hovertemplate"] = (f"{label}<br>Distance: %{{customdata[0]:.0f}} ft"
                                          "<br>Exit Velo: %{customdata[1]:.1f} mph<extra></extra>")
            fig.add_trace(go.Scatter(**trace))
```

Recolor `contact_type_bar` — per-bar colors from the hit-type map:

```python
def contact_type_bar(counts_df: pd.DataFrame) -> go.Figure:
    """Vertical bar of hit-type counts, sorted descending, colored per hit type."""
    fig = go.Figure()
    if counts_df is not None and not counts_df.empty:
        d = counts_df.sort_values("Count", ascending=False)
        colors = [_HIT_COLORS.get(ht, "#5a5a5a") for ht in d["Hit Type"]]
        fig.add_trace(go.Bar(x=d["Hit Type"], y=d["Count"], marker_color=colors,
                             text=d["Count"], textposition="outside"))
    fig.update_layout(
        title="Contact Type", yaxis_title="Count",
        height=340, margin=dict(l=40, r=20, t=50, b=40),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"))
    return fig
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_hitting_practice_dash.py::test_spray_distribution_fan_builds_cells tests/test_hitting_practice_dash.py::test_spray_scatter_hover_has_distance_and_ev tests/test_hitting_practice_dash.py::test_contact_type_bar_uses_hit_type_colors tests/test_hitting_practice_dash.py::test_new_practice_figs_build -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/hitting_practice/charts.py tests/test_hitting_practice_dash.py
git commit -m "feat(practice): distribution fan + scatter distance/EV hover + colored contact bar"
```

---

### Task 11: Practice — Batted-Ball tab two-field layout + chip callbacks

**Files:**
- Modify: `app/dashboards/hitting_practice/tabs/batted_ball.py` (chip row + two-field body)
- Modify: `app/dashboards/hitting_practice/callbacks.py` (add `bb` chip toggle/styles/body callbacks)
- Test: `tests/test_hitting_practice_dash.py` (append)

**Interfaces:**
- Consumes: `charts.spray_distribution_fan`, `charts.spray_chart_fig`, `charts.contact_type_bar`, `P.spray_fan`, `P.spray_points`, `P.hit_type_counts`, `P.HIT_TYPE_MAP`, `swing_frequency.chip_style`.
- Produces: `batted_ball.render(plays)` = chip row (`bb-active`/`bb-present` stores, `bb-chip` buttons) + `bb-body` (two graphs side by side + contact bar); `batted_ball.body(plays, active_labels)` filters both fields to `active_labels`; the contact bar stays unfiltered.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_hitting_practice_dash.py`:

```python
def test_batted_ball_two_fields_and_chips():
    import inspect
    import pandas as pd
    from app.dashboards.hitting_practice.tabs import batted_ball
    src = inspect.getsource(batted_ball)
    assert "spray_distribution_fan" in src and "spray_chart_fig" in src
    assert "bb-chip" in src and "bb-active" in src

    plays = pd.DataFrame([
        {"horizontal_angle": -30.0, "distance_feet": 200.0, "exit_velocity": 90.0, "hit_type": 2},
        {"horizontal_angle": 20.0, "distance_feet": 300.0, "exit_velocity": 95.0, "hit_type": 3},
    ])
    # two graphs (fan + scatter) + the contact bar => at least 3 graphs
    def _count_graphs(node, n=0):
        from dash import dcc
        if isinstance(node, dcc.Graph):
            n += 1
        ch = getattr(node, "children", None)
        kids = ch if isinstance(ch, (list, tuple)) else ([ch] if ch is not None else [])
        for k in kids:
            n = _count_graphs(k, n)
        return n
    assert _count_graphs(batted_ball.render(plays)) >= 3
    # filtering to Fly Ball only keeps the FB row feeding the fan/scatter (no crash)
    assert batted_ball.body(plays, ["Fly Ball"]) is not None


def test_batted_ball_chip_callbacks_registered():
    import inspect
    from app.dashboards.hitting_practice import callbacks
    src = inspect.getsource(callbacks)
    assert "bb-active" in src and "bb-body" in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_hitting_practice_dash.py::test_batted_ball_two_fields_and_chips tests/test_hitting_practice_dash.py::test_batted_ball_chip_callbacks_registered -v`
Expected: FAIL (single-graph tab; no `bb` chips/callbacks).

- [ ] **Step 3: Implement the tab**

Replace `app/dashboards/hitting_practice/tabs/batted_ball.py`:

```python
"""Batted Ball tab — hit-type chips -> distribution fan + landing scatter, + contact bar."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import practice as P
from app.dashboards.hitting_practice import charts
from app.dashboards.hitting_practice.tabs.swing_frequency import chip_style
from app.dashboards.shell import section

_HIT_ORDER = ["Ground Ball", "Line Drive", "Fly Ball"]


def chip_row(plays: pd.DataFrame) -> html.Div:
    labels = pd.Series(dtype=object)
    if plays is not None and not plays.empty and "hit_type" in plays.columns:
        labels = plays["hit_type"].map(P.HIT_TYPE_MAP)
    present = [t for t in _HIT_ORDER if t in set(labels.dropna())]
    if not present:
        present = list(_HIT_ORDER)
    chips = [html.Button(t, id={"type": "bb-chip", "index": t}, n_clicks=0,
                         style=chip_style(active=True, present=True)) for t in present]
    return html.Div([dcc.Store(id="bb-active", data=present),
                     dcc.Store(id="bb-present", data=present),
                     html.Div(chips)], style={"margin": "6px 0"})


def body(plays: pd.DataFrame, active_labels) -> html.Div:
    d = plays
    if active_labels is not None and plays is not None and not plays.empty \
            and "hit_type" in plays.columns:
        keep = set(active_labels)
        d = plays[plays["hit_type"].map(P.HIT_TYPE_MAP).isin(keep)]
    fan = P.spray_fan(d)
    spray = P.spray_points(d)
    counts = P.hit_type_counts(plays)  # contact bar stays unfiltered (overview)
    return html.Div([
        html.Div([
            html.Div([section("Batted-Ball Distribution"),
                      dcc.Graph(figure=charts.spray_distribution_fan(fan))],
                     style={"flex": "1"}),
            html.Div([section("Landing Chart"),
                      dcc.Graph(figure=charts.spray_chart_fig(spray))],
                     style={"flex": "1"}),
        ], style={"display": "flex", "gap": "16px"}),
        section("Contact Type"),
        dcc.Graph(figure=charts.contact_type_bar(counts)),
    ])


def render(plays: pd.DataFrame) -> html.Div:
    if plays is None or plays.empty:
        return html.Div("No batted-ball data for these filters.",
                        style={"color": "#555", "padding": "12px"})
    return html.Div([chip_row(plays),
                     html.Div(id="bb-body", children=body(plays, None))])
```

- [ ] **Step 4: Implement the callbacks**

The `bb-body` re-render needs the current plays. The `_render` callback loads `plays` only inside its `batted` branch (not stored), so the chip-body callback must reload plays the same way. Add these callbacks in `register_callbacks` in `app/dashboards/hitting_practice/callbacks.py` (mirror the `sfz` trio):

```python
    @dash_app.callback(
        Output("bb-active", "data"),
        Input({"type": "bb-chip", "index": ALL}, "n_clicks"),
        State("bb-active", "data"), State("bb-present", "data"),
        prevent_initial_call=True,
    )
    def _bb_toggle(_clicks, active, present):
        tid = ctx.triggered_id
        if not tid:
            return active
        label = tid["index"]
        present = set(present or [])
        if label not in present:
            return active
        active = list(active or [])
        return [x for x in active if x != label] if label in active else active + [label]

    @dash_app.callback(
        Output({"type": "bb-chip", "index": ALL}, "style"),
        Input("bb-active", "data"),
        State("bb-present", "data"),
        State({"type": "bb-chip", "index": ALL}, "id"),
    )
    def _bb_styles(active, present, ids):
        from app.dashboards.hitting_practice.tabs.swing_frequency import chip_style
        active = set(active or [])
        present = set(present or [])
        return [chip_style(active=i["index"] in active, present=i["index"] in present)
                for i in ids]

    @dash_app.callback(
        Output("bb-body", "children"),
        Input("bb-active", "data"),
        State("prac-filters", "data"),
    )
    def _bb_body(active, filt):
        from app.dashboards.hitting_practice.tabs import batted_ball
        filt = filt or {}
        _, plays, _, _ = _load_all(bool(filt.get("exclude_test", True)))
        start = date.fromisoformat(filt["start"]) if filt.get("start") else None
        end = date.fromisoformat(filt["end"]) if filt.get("end") else None
        player = filt.get("player") or "All Players"
        if not plays.empty and start and end and "play_date" in plays.columns:
            plays = plays[pd.to_datetime(plays["play_date"]).between(
                pd.Timestamp(start), pd.Timestamp(end))]
        if player != "All Players" and not plays.empty:
            plays = plays[plays["player_name"] == player]
        if plays.empty:
            return html.Div("No batted-ball data for these filters.",
                            style={"color": "#555", "padding": "12px"})
        return batted_ball.body(plays, active)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_hitting_practice_dash.py::test_batted_ball_two_fields_and_chips tests/test_hitting_practice_dash.py::test_batted_ball_chip_callbacks_registered tests/test_hitting_practice_dash.py::test_batted_ball_tab_renders -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/dashboards/hitting_practice/tabs/batted_ball.py app/dashboards/hitting_practice/callbacks.py tests/test_hitting_practice_dash.py
git commit -m "feat(practice): two-field batted-ball tab with hit-type chip filter"
```

---

### Task 12: Full-suite gate + live smoke

**Files:** none (verification only)

- [ ] **Step 1: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS (≥ 271 + the new tests; 0 failures).

- [ ] **Step 2: Restart the dev server by port owner**

```powershell
Get-NetTCPConnection -LocalPort 8050 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

Confirm the port is free, then relaunch a single instance: `PYTHONIOENCODING=utf-8 python run.py`.

- [ ] **Step 3: Live smoke, both roles**

Log in as coach (`coach@lmu.edu` / `paw2026`) and player (`hitter@lmu.edu` / `paw2026`). Verify:
  - Hitting dashboard header shows the "← Hitting" back-link; sidebar footnote is darker.
  - Pitching: pitch names in the Characteristics/All-Pitches tables are colored; hovering the Velocity Across Outing / Movement points shows labeled fields; Movement shows translucent 1σ ellipses.
  - Catching → Static Framing: Zone Location is a 2×2 grid, not 4-across.
  - Practice → Swing Frequency: session-date axis shows real dates; zone chips read "Zone 1…13" with empty zones greyed; no "Session type"/"Exclude test accounts" controls remain.
  - Practice → Batted Ball: distribution fan (crimson) + landing scatter side by side, hit-type chips filter both, scatter hover shows Distance + Exit Velo, contact bar colored by hit type.

- [ ] **Step 4: Commit any smoke-fix follow-ups** (only if the smoke surfaces a defect).

---

## Self-Review

**Spec coverage:**
- A1 footnote color → Task 1. A2 back-link → Task 1.
- B3 session dates → Task 6. B4 zone chips → Task 7. B5 spray (fan/scatter/bar/chips) → Tasks 9 (data) + 10 (charts) + 11 (tab/callbacks). B6 remove filters → Task 8.
- C7 colored pitch column → Task 3. C8 labeled hovers → Task 4. C9 movement ellipses → Task 5.
- D9b static-framing 2-per-row → Task 2.
- Every spec section maps to a task. No gaps.

**Placeholder scan:** No TBD/TODO/"handle edge cases"/"similar to Task N". All code steps carry real code.

**Type consistency:**
- `chip_style(active, present)` defined in Task 7 (swing_frequency), reused in Tasks 7 and 11 callbacks — same signature throughout.
- `spray_fan`/`spray_points` columns defined in Task 9 match consumption in Task 10 (`spray_distribution_fan`, `spray_chart_fig`) and Task 11 (`body`).
- `HIT_TYPE_COLORS` defined in Task 9, consumed in Task 10 (`_HIT_COLORS = P.HIT_TYPE_COLORS`) and asserted in Task 10 tests.
- `_rgba`/`_cov_ellipse` defined in Task 5, used only within `fig_movement`.
- Store/id names (`sfz-active`, `sfz-present`, `bb-active`, `bb-present`, `bb-body`, `bb-chip`, `sfz-chip`) consistent across tab render and callbacks.

**Ordering note:** Task 4 sets `fig_movement`'s marker hovertemplate; Task 5 rewrites `fig_movement` but preserves that same hovertemplate and adds ellipses — the Task 4 hover test still passes after Task 5 (verified in Task 5 Step 4).
