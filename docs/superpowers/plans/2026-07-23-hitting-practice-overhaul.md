# Hitting-Practice Dashboard Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Overhaul the HitTrax practice dashboard — add a player photo/name sidebar with the swing tiles, a black + metric-toggleable Pitch Zones heatmap, a swing-decision trend + zone-chip EV/distance chart on Swing Frequency, and a Batted Ball tab (spray chart + contact-type bar) replacing Contact Overview.

**Architecture:** In-place within `app/dashboards/hitting_practice/` + `app/data/{practice.py,roster_media.py}`. New pure data transforms + Plotly figures; a reactive `prac-sidebar`; tab reworks reuse the pitching chip pattern for the zone selector.

**Tech Stack:** Python, Flask, Dash, Plotly, pandas, numpy; pytest.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-07-23-hitting-practice-overhaul-design.md`. Base branch `feat/hitting-practice-overhaul` (off `feat/catching-enhancements`).
- **No DB in tabs/charts** — pure `df → components`/`figure`. DB only in `app/data/*` + callbacks.
- **Spray chart** = Plotly-drawn field (foul lines + arc + diamond), batted balls only (`hit_type ∈ {1,2,3}`), colored by hit type; NO sector shading.
- **Sidebar** always present; "All Players" → lion placeholder (`PHOTO_PLACEHOLDER` from shell) + "All Players" + team-aggregate tiles.
- **Metric toggle** values: `contact` / `ev` / `distance`.
- **Brand:** Teko; crimson `#9A0021`; blue `#0076A5`; transparent `paper_bgcolor`, near-white `plot_bgcolor`.
- `HIT_TYPE_MAP = {0:"Miss/Foul",1:"Ground Ball",2:"Line Drive",3:"Fly Ball"}` (exists in `practice.py`).
- Practice data: `practice_plays` has `horizontal_angle`, `distance_feet`, `exit_velocity`, `hit_type`, `result`, `zone_section`. Pitch-coord df (`load_pitch_coords`) has `px,py,result,exit_velocity,distance_feet,zone_section,play_date,is_contact`.
- **Tests:** `python -m pytest -q`; Windows headless prefix `PYTHONIOENCODING=utf-8`. Live-DB tests follow the existing unguarded convention.

---

### Task 1: Data layer — media-by-name, load_plays angle, trend, metric heatmap, spray

**Files:**
- Modify: `app/data/roster_media.py` (add `player_media_by_name`)
- Modify: `app/data/practice.py` (`load_plays` +`horizontal_angle`; add `swing_decision_trend`, `heatmap_metric`, `spray_points`; keep `heatmap_contact_rate` as a wrapper)
- Test: `tests/test_roster_media.py`, `tests/test_practice.py` (append)

**Interfaces (produced):**
- `roster_media.player_media_by_name(name: str) -> {'jersey','photo_url'}`
- `practice.swing_decision_trend(df) -> DataFrame[play_date, in_zone_pct, chase_pct, score]`
- `practice.heatmap_metric(df, metric="contact", bins=20) -> (z, xedges, yedges)`
- `practice.spray_points(plays_df) -> DataFrame[x, y, hit_type_label]`
- `practice.load_plays` rows include `horizontal_angle`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_roster_media.py`:

```python
def test_player_media_by_name(monkeypatch):
    from app.data import roster_media
    monkeypatch.setattr(roster_media, "load_roster_media", lambda: {
        "813709": {"jersey": "27", "photo_url": "u.jpg", "name": "Tanner Warady"},
    })
    got = roster_media.player_media_by_name("Tanner Warady")
    assert got["jersey"] == "27" and got["photo_url"] == "u.jpg"
    # unmatched -> blanks
    assert roster_media.player_media_by_name("Nobody Here") == {"jersey": "", "photo_url": ""}
    assert roster_media.player_media_by_name("") == {"jersey": "", "photo_url": ""}
```

Append to `tests/test_practice.py`:

```python
def test_swing_decision_trend():
    import pandas as pd
    from app.data import practice as P
    df = pd.DataFrame([
        # 2026-04-01: 1 in-zone contact, 1 chase miss -> iz 100, chase 0, score 100
        {"play_date": "2026-04-01", "zone_section": 5, "result": 1},
        {"play_date": "2026-04-01", "zone_section": 11, "result": -4},
        # 2026-04-08: 1 in-zone miss -> iz 0, chase None -> score None (excluded)
        {"play_date": "2026-04-08", "zone_section": 3, "result": -4},
    ])
    df["is_contact"] = df["result"] != -4
    t = P.swing_decision_trend(df)
    assert list(t["play_date"]) == ["2026-04-01"]
    assert t.iloc[0]["score"] == 100.0


def test_heatmap_metric_ev_and_distance():
    import numpy as np, pandas as pd
    from app.data import practice as P
    df = pd.DataFrame([
        {"px": 0.0, "py": 2.5, "result": 1, "exit_velocity": 90.0, "distance_feet": 300.0},
        {"px": 0.0, "py": 2.5, "result": 1, "exit_velocity": 80.0, "distance_feet": 100.0},
    ])
    z_ev, xe, ye = P.heatmap_metric(df, "ev")
    z_dist, _, _ = P.heatmap_metric(df, "distance")
    # the one populated bin averages the two rows
    assert np.nanmax(z_ev) == 85.0
    assert np.nanmax(z_dist) == 200.0


def test_spray_points_sign_and_filter():
    import pandas as pd
    from app.data import practice as P
    plays = pd.DataFrame([
        {"horizontal_angle": -45.0, "distance_feet": 100.0, "hit_type": 2},  # left, LD
        {"horizontal_angle": 45.0, "distance_feet": 100.0, "hit_type": 3},   # right, FB
        {"horizontal_angle": 0.0, "distance_feet": 0.0, "hit_type": 0},      # miss -> dropped
    ])
    s = P.spray_points(plays)
    assert len(s) == 2  # miss excluded
    assert s.iloc[0]["x"] < 0 and s.iloc[1]["x"] > 0  # neg angle = left
    assert set(s["hit_type_label"]) == {"Line Drive", "Fly Ball"}
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_roster_media.py tests/test_practice.py -k "by_name or swing_decision_trend or heatmap_metric or spray_points" -v`
Expected: FAIL (functions missing).

- [ ] **Step 3: Implement**

In `app/data/roster_media.py` add:

```python
def player_media_by_name(name) -> dict:
    """{'jersey','photo_url'} matched to a roster entry by name (norm + last/first
    fallback); blanks if unmatched. For HitTrax names (no trackman id)."""
    blank = {"jersey": "", "photo_url": ""}
    if not name:
        return blank
    data = load_roster_media()
    key = _norm_name(name)
    for entry in data.values():
        if _norm_name(entry.get("name", "")) == key:
            return {"jersey": entry.get("jersey", ""), "photo_url": entry.get("photo_url", "")}
    f, l = _name_parts(name)
    if l:
        for entry in data.values():
            ef, el = _name_parts(entry.get("name", ""))
            if el == l and ef[:1] == f[:1]:
                return {"jersey": entry.get("jersey", ""),
                        "photo_url": entry.get("photo_url", "")}
    return blank
```

In `app/data/practice.py`:
- Add `horizontal_angle` to the `load_plays` SELECT column list (after `distance_feet`).
- Replace `heatmap_contact_rate` with a general `heatmap_metric` + keep the old name as a wrapper:

```python
def heatmap_metric(df: pd.DataFrame, metric: str = "contact", bins: int = 20):
    """(z, x_edges, y_edges) grid for a Plotly heatmap. metric: contact|ev|distance.
    z[y][x]; NaN where no pitches in a bin."""
    xedges = np.linspace(-2, 2, bins + 1)
    yedges = np.linspace(0.5, 5.0, bins + 1)
    if df.empty:
        return np.full((bins, bins), np.nan), xedges, yedges
    d = df.dropna(subset=["px", "py"]).copy()
    if metric == "contact":
        d["_c"] = d["result"] != -4
        counts, _, _ = np.histogram2d(d["px"], d["py"], bins=[xedges, yedges])
        made, _, _ = np.histogram2d(d.loc[d["_c"], "px"], d.loc[d["_c"], "py"],
                                    bins=[xedges, yedges])
        with np.errstate(divide="ignore", invalid="ignore"):
            z = np.where(counts > 0, 100.0 * made / counts, np.nan)
    else:
        col = "exit_velocity" if metric == "ev" else "distance_feet"
        sub = d[d[col].notna()]
        counts, _, _ = np.histogram2d(sub["px"], sub["py"], bins=[xedges, yedges])
        sums, _, _ = np.histogram2d(sub["px"], sub["py"], bins=[xedges, yedges],
                                    weights=sub[col])
        with np.errstate(divide="ignore", invalid="ignore"):
            z = np.where(counts > 0, sums / counts, np.nan)
    return z.T, xedges, yedges


def heatmap_contact_rate(df: pd.DataFrame, bins: int = 20):
    """Back-compat wrapper: contact-rate grid."""
    return heatmap_metric(df, "contact", bins)


def swing_decision_trend(df: pd.DataFrame) -> pd.DataFrame:
    """Per-date swing-decision score (in-zone 1-9 contact% - chase 10-13 contact%).
    Only dates where the score is computable. PROVISIONAL."""
    cols = ["play_date", "in_zone_pct", "chase_pct", "score"]
    if df.empty or "play_date" not in df.columns:
        return pd.DataFrame(columns=cols)
    rows = []
    for d, sub in df.groupby("play_date"):
        s = swing_decision_score(sub)
        if s["score"] is not None:
            rows.append({"play_date": d, "in_zone_pct": s["in_zone_pct"],
                         "chase_pct": s["chase_pct"], "score": s["score"]})
    return pd.DataFrame(rows, columns=cols).sort_values("play_date").reset_index(drop=True)


def spray_points(plays: pd.DataFrame) -> pd.DataFrame:
    """Batted-ball landing points from horizontal_angle + distance_feet.
    x = dist*sin(angle) (neg=left field), y = dist*cos(angle). Batted balls only
    (hit_type 1/2/3). PROVISIONAL."""
    cols = ["x", "y", "hit_type_label"]
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
    return d[cols].reset_index(drop=True)
```

`swing_decision_score` already exists in `practice.py`; `swing_decision_trend` calls it per date. `np` is already imported.

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_roster_media.py tests/test_practice.py -k "by_name or swing_decision_trend or heatmap_metric or spray_points" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/data/roster_media.py app/data/practice.py tests/test_roster_media.py tests/test_practice.py
git commit -m "feat(practice-data): media-by-name, load_plays angle, swing-decision trend, metric heatmap, spray points"
```

---

### Task 2: Charts — black/metric heatmap, trend, spray, contact-type bar

**Files:**
- Modify: `app/dashboards/hitting_practice/charts.py`
- Test: `tests/test_hitting_practice_dash.py` (append)

**Interfaces (produced):**
- `pitch_zone_heatmap(df, metric="contact")` — black zone box; metric-aware colorbar/scale/title.
- `swing_decision_trend_fig(trend_df) -> go.Figure`
- `spray_chart_fig(spray_df) -> go.Figure`
- `contact_type_bar(counts_df) -> go.Figure`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_hitting_practice_dash.py`:

```python
def test_pitch_zone_heatmap_black_box_and_metric():
    import pandas as pd
    from app.dashboards.hitting_practice import charts
    df = pd.DataFrame([{"px": 0.0, "py": 2.5, "result": 1,
                        "exit_velocity": 90.0, "distance_feet": 300.0}])
    fig = charts.pitch_zone_heatmap(df, metric="ev")
    # the strike-zone rectangle shape is drawn black
    rects = [s for s in fig.layout.shapes if s.type == "rect"]
    assert rects and any(s.line.color == "black" for s in rects)


def test_new_practice_figs_build():
    import pandas as pd
    from app.dashboards.hitting_practice import charts
    assert charts.swing_decision_trend_fig(pd.DataFrame(
        columns=["play_date", "in_zone_pct", "chase_pct", "score"])) is not None
    assert charts.swing_decision_trend_fig(pd.DataFrame([
        {"play_date": "2026-04-01", "in_zone_pct": 80, "chase_pct": 30, "score": 50}])) is not None
    assert charts.spray_chart_fig(pd.DataFrame(columns=["x", "y", "hit_type_label"])) is not None
    assert charts.spray_chart_fig(pd.DataFrame([
        {"x": -50.0, "y": 200.0, "hit_type_label": "Line Drive"}])) is not None
    assert charts.contact_type_bar(pd.DataFrame([
        {"Hit Type": "Line Drive", "Count": 10}, {"Hit Type": "Fly Ball", "Count": 5}])) is not None
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_hitting_practice_dash.py -k "black_box or new_practice_figs" -v`
Expected: FAIL.

- [ ] **Step 3: Implement in `app/dashboards/hitting_practice/charts.py`**

Replace `pitch_zone_heatmap` with a metric-aware version (black box):

```python
_METRIC_CFG = {
    "contact": ("Contact %", "YlOrRd", (0, 100), "Contact Rate"),
    "ev": ("Avg EV (mph)", "YlOrRd", (None, None), "Avg Exit Velocity"),
    "distance": ("Avg Dist (ft)", "YlOrRd", (None, None), "Avg Distance"),
}


def pitch_zone_heatmap(df: pd.DataFrame, metric: str = "contact") -> go.Figure:
    label, scale, (zmin, zmax), title = _METRIC_CFG.get(metric, _METRIC_CFG["contact"])
    z, xedges, yedges = P.heatmap_metric(df, metric)
    x_centers = (xedges[:-1] + xedges[1:]) / 2
    y_centers = (yedges[:-1] + yedges[1:]) / 2
    fig = go.Figure(data=go.Heatmap(
        z=z, x=x_centers, y=y_centers, colorscale=scale,
        zmin=zmin, zmax=zmax, colorbar=dict(title=label),
        hovertemplate="x=%{x:.2f}ft<br>y=%{y:.2f}ft<br>%{z:.1f}<extra></extra>",
    ))
    fig.add_shape(type="rect", x0=P.SZ_X0, y0=P.SZ_Y0, x1=P.SZ_X1, y1=P.SZ_Y1,
                  line=dict(color="black", width=2), fillcolor="rgba(0,0,0,0)")
    fig.update_layout(
        title=f"Pitch Zones — {title} (Catcher's View)",
        xaxis_title="Horizontal (ft)", yaxis_title="Height (ft)",
        yaxis=dict(scaleanchor="x", scaleratio=1),
        height=480, margin=dict(l=40, r=20, t=50, b=40),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"),
    )
    return fig
```

Add the three new figures (keep `_BLUE`, `CRIMSON` already imported):

```python
_HIT_COLORS = {"Ground Ball": "#7a5230", "Line Drive": "#9A0021", "Fly Ball": "#0076A5"}


def swing_decision_trend_fig(trend_df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if trend_df is not None and not trend_df.empty:
        x = trend_df["play_date"].astype(str)
        fig.add_trace(go.Scatter(
            x=x, y=trend_df["score"], mode="lines+markers", name="Swing Decision Score",
            line=dict(color=CRIMSON, width=2), marker=dict(color=CRIMSON, size=9)))
        fig.add_hline(y=0, line=dict(color="#bbb", width=1))
    fig.update_layout(
        title="Swing Decision Score by Session (In-Zone % − Chase %)",
        xaxis_title="Session date", yaxis_title="Score",
        height=340, margin=dict(l=40, r=20, t=50, b=40),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"))
    return fig


def spray_chart_fig(spray_df: pd.DataFrame) -> go.Figure:
    """Plotly-drawn field + batted-ball landing points colored by hit type."""
    fig = go.Figure()
    # Field: foul lines from home (0,0), outfield arc (~330ft), infield diamond.
    L = 330.0
    fig.add_shape(type="line", x0=0, y0=0, x1=-L * 0.707, y1=L * 0.707,
                  line=dict(color="#888", width=1))
    fig.add_shape(type="line", x0=0, y0=0, x1=L * 0.707, y1=L * 0.707,
                  line=dict(color="#888", width=1))
    fig.add_shape(type="path",
                  path=f"M {-L*0.707},{L*0.707} Q 0,{L*1.15} {L*0.707},{L*0.707}",
                  line=dict(color="#888", width=1))
    # infield diamond (~90ft bases, rotated): home->1st->2nd->3rd
    b = 63.6  # 90/sqrt(2)
    fig.add_shape(type="path",
                  path=f"M 0,0 L {b},{b} L 0,{2*b} L {-b},{b} Z",
                  line=dict(color="#bbb", width=1), fillcolor="rgba(0,0,0,0)")
    if spray_df is not None and not spray_df.empty:
        for label, sub in spray_df.groupby("hit_type_label"):
            fig.add_trace(go.Scatter(
                x=sub["x"], y=sub["y"], mode="markers", name=str(label),
                marker=dict(color=_HIT_COLORS.get(label, "#5a5a5a"), size=8,
                            line=dict(width=0.5, color="#666"))))
    fig.update_layout(
        title="Spray Chart", showlegend=True,
        xaxis=dict(range=[-260, 260], visible=False),
        yaxis=dict(range=[-20, 400], visible=False, scaleanchor="x", scaleratio=1),
        height=460, margin=dict(l=10, r=10, t=50, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"))
    return fig


def contact_type_bar(counts_df: pd.DataFrame) -> go.Figure:
    """Vertical bar of hit-type counts, sorted descending."""
    fig = go.Figure()
    if counts_df is not None and not counts_df.empty:
        d = counts_df.sort_values("Count", ascending=False)
        fig.add_trace(go.Bar(x=d["Hit Type"], y=d["Count"], marker_color=CRIMSON,
                             text=d["Count"], textposition="outside"))
    fig.update_layout(
        title="Contact Type", yaxis_title="Count",
        height=340, margin=dict(l=40, r=20, t=50, b=40),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"))
    return fig
```

Leave `hit_type_donut` / `top_players_bar` in the file for now (unused after Task 6; final review may prune).

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_hitting_practice_dash.py -k "black_box or new_practice_figs" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/hitting_practice/charts.py tests/test_hitting_practice_dash.py
git commit -m "feat(practice): metric heatmap (black box) + swing-decision trend + spray + contact-type bar figs"
```

---

### Task 3: Player sidebar (layout + callback)

**Files:**
- Modify: `app/dashboards/hitting_practice/layout.py` (wrap in flex, add `prac-sidebar`)
- Modify: `app/dashboards/hitting_practice/callbacks.py` (sidebar callback)
- Test: `tests/test_hitting_practice_dash.py` (append)

**Interfaces:**
- Consumes: `roster_media.player_media_by_name`, `P.contact_summary`, `P.swing_decision_score`, `P.apply_filters`, `shell.PHOTO_PLACEHOLDER`.
- Produces: `layout.sidebar(pitch_df, player) -> html.Div` (photo/name + Swing Freq tiles + Swing Decision tiles); reactive `prac-sidebar`.

- [ ] **Step 1: Write the failing test**

```python
def test_practice_sidebar_renders_player_and_all():
    import pandas as pd
    from app.dashboards.hitting_practice import layout
    df = pd.DataFrame([{"px": 0.0, "py": 2.5, "result": 1, "zone_section": 5,
                        "exit_velocity": 90.0, "is_contact": True,
                        "player_name": "Andrew Mhoon", "play_date": "2026-04-01"}])
    assert layout.sidebar(df, "Andrew Mhoon") is not None
    assert layout.sidebar(df, "All Players") is not None
    assert layout.sidebar(pd.DataFrame(), "All Players") is not None
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_hitting_practice_dash.py -k practice_sidebar -v`
Expected: FAIL (`layout.sidebar` missing).

- [ ] **Step 3: Edit `layout.py`**

Add imports: `from app.data import roster_media` and `from app.dashboards.shell import PHOTO_PLACEHOLDER` (shell already imported for header/BANNER — extend the import). Add the sidebar builder and a `_tile` helper:

```python
def _tile(label, value):
    from app.dashboards.shell import CRIMSON
    return html.Div([
        html.Div(str(value), style={"fontSize": "24px", "fontWeight": "bold", "color": CRIMSON}),
        html.Div(label, style={"fontSize": "13px", "color": "#555"}),
    ], style={"textAlign": "center", "padding": "6px 8px",
              "backgroundColor": "rgba(255,255,255,0.85)", "borderRadius": "8px"})


def sidebar(pitch_df, player) -> html.Div:
    import pandas as pd
    from app.data import practice as P
    is_all = (not player) or player == "All Players"
    if is_all:
        photo, name = PHOTO_PLACEHOLDER, "All Players"
    else:
        media = roster_media.player_media_by_name(player)
        photo = media.get("photo_url") or PHOTO_PLACEHOLDER
        name = player
    d = pitch_df if (pitch_df is not None and not pitch_df.empty) else pd.DataFrame()
    if not d.empty:
        d = P.trim_to_first_contact(d)
    summ = P.contact_summary(d)
    sds = P.swing_decision_score(d)

    def f(v, s=""):
        return "—" if v is None else f"{v}{s}"

    return html.Div([
        html.Img(src=photo, style={"width": "100%", "borderRadius": "8px",
                                   "border": "4px solid white", "background": "rgba(255,255,255,0.6)"}),
        html.Div(name, style={"fontSize": "22px", "fontWeight": "bold", "marginTop": "8px"}),
        html.Div("Swing Frequency", style={"fontSize": "14px", "color": "#9A0021",
                                            "fontWeight": "bold", "marginTop": "10px"}),
        html.Div([_tile("Pitches", summ["pitches"]), _tile("Contacts", summ["contacts"]),
                  _tile("Contact%", f(summ["contact_pct"], "%"))],
                 style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "6px"}),
        html.Div("Swing Decision", style={"fontSize": "14px", "color": "#9A0021",
                                          "fontWeight": "bold", "marginTop": "10px"}),
        html.Div([_tile("In-Zone%", f(sds["in_zone_pct"], "%")),
                  _tile("Chase%", f(sds["chase_pct"], "%")),
                  _tile("SD Score", f(sds["score"]))],
                 style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "6px"}),
    ], style={"padding": "8px"})
```

In `serve_layout`, wrap the content below the header in a flex row with the sidebar. Replace the final `return html.Div([...])` structure so it is:

```python
    return html.Div([
        dcc.Store(id="prac-filters", data={...}),   # keep existing store(s)
        dcc.Store(id="prac-pitch-data"),
        header(back_href="/hitting", back_label="← Hitting"),
        html.Div([
            html.Div(id="prac-sidebar", children=sidebar(pitch_all, default_player),
                     style={"width": "240px", "flexShrink": "0"}),
            html.Div([
                html.H2("HitTrax Practice Analytics", style={"color": "#9A0021", "margin": "0 0 4px"}),
                html.Div("Ported from the Streamlit batting-practice dashboard.",
                         style={"color": "#555", "marginBottom": "8px"}),
                filters, tabs,
                html.Div(id="prac-tab-content", style={"padding": "8px 16px"}),
            ], style={"flexGrow": "1"}),
        ], style={"display": "flex", "gap": "16px", "padding": "16px", "alignItems": "flex-start"}),
    ])
```

(Preserve the existing stores/filters/tabs objects exactly — only restructure the outer wrapper to add the sidebar column. `pitch_all` and `default_player` are already computed in `serve_layout`.)

- [ ] **Step 4: Edit `callbacks.py` — reactive sidebar**

Add a callback that refreshes the sidebar from the filters:

```python
    @dash_app.callback(
        Output("prac-sidebar", "children"),
        Input("prac-filters", "data"),
    )
    def _sidebar(filt):
        filt = filt or {}
        exclude_test = bool(filt.get("exclude_test", True))
        pitch, _, _, _ = _load_all(exclude_test)
        from datetime import date
        start = date.fromisoformat(filt["start"]) if filt.get("start") else None
        end = date.fromisoformat(filt["end"]) if filt.get("end") else None
        player = filt.get("player") or "All Players"
        d = P.apply_filters(pitch, player=player, start=start, end=end,
                            session=filt.get("session"))
        return layout.sidebar(d, player)
```

(`_load_all`, `layout`, `P` are already imported in `callbacks.py`.)

- [ ] **Step 5: Run tests + full suite**

Run: `python -m pytest tests/test_hitting_practice_dash.py -q` then `python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/dashboards/hitting_practice/layout.py app/dashboards/hitting_practice/callbacks.py tests/test_hitting_practice_dash.py
git commit -m "feat(practice): player photo/name sidebar with swing tiles (team view for All Players)"
```

---

### Task 4: Pitch Zones — black box + metric toggle

**Files:**
- Modify: `app/dashboards/hitting_practice/tabs/pitch_zones.py`
- Modify: `app/dashboards/hitting_practice/callbacks.py` (metric callback; `_render` passes metric)
- Test: `tests/test_hitting_practice_dash.py` (append)

**Interfaces:**
- `pitch_zones.render(df, metric="contact")` — adds a `dcc.RadioItems(id="pz-metric")` + a `pz-heatmap` container.

- [ ] **Step 1: Write the failing test**

```python
def test_pitch_zones_has_metric_toggle():
    import inspect
    from app.dashboards.hitting_practice.tabs import pitch_zones as pz
    # the metric toggle id is present, and render accepts a metric arg
    assert "pz-metric" in inspect.getsource(pz)
    assert "metric" in inspect.signature(pz.render).parameters


def test_pitch_zones_render_ev():
    import pandas as pd
    from app.dashboards.hitting_practice.tabs import pitch_zones
    df = pd.DataFrame([{"px": 0.0, "py": 2.5, "result": 1, "zone_section": 5,
                        "exit_velocity": 90.0, "distance_feet": 300.0, "is_contact": True}])
    assert pitch_zones.render(df, metric="ev") is not None
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_hitting_practice_dash.py -k pitch_zones_has_metric -v`
Expected: FAIL (`pz-metric` not in source).

- [ ] **Step 3: Edit `pitch_zones.py`**

Add a metric toggle + heatmap container; `render` takes a `metric` arg and the callback re-renders the heatmap. Replace the heatmap `dcc.Graph` line and keep tiles/zone-table:

```python
def render(df: pd.DataFrame, metric: str = "contact") -> html.Div:
    if df.empty:
        return html.Div("No pitch-location data for these filters. "
                        "Try a wider date range or another player.",
                        style={"color": "#555", "padding": "12px"})
    d = P.trim_to_first_contact(df)
    summ = P.contact_summary(d)
    zone = P.zone_contact_table(d)
    tiles = html.Div([
        _tile("Pitches", summ["pitches"]),
        _tile("Contact%", _fmt(summ["contact_pct"])),
        _tile("In-Zone", summ["in_zone"]),
        _tile("In-Zone Contact%", _fmt(summ["in_zone_contact_pct"])),
    ], style={"display": "flex", "gap": "10px", "flexWrap": "wrap", "marginBottom": "12px"})
    return html.Div([
        section("Pitch Zones"),
        tiles,
        dcc.RadioItems(id="pz-metric",
                       options=[{"label": " Contact %", "value": "contact"},
                                {"label": " Avg EV", "value": "ev"},
                                {"label": " Avg Distance", "value": "distance"}],
                       value=metric, inline=True,
                       style={"margin": "4px 0"},
                       inputStyle={"marginRight": "4px", "marginLeft": "12px"}),
        html.Div(id="pz-heatmap", children=dcc.Graph(figure=charts.pitch_zone_heatmap(d, metric))),
        section("Zone Summary"),
        tables.df_table(zone, id_="pz-zone-table"),
        html.Div(
            "HitTrax does not separate swing-miss from takes; non-contact "
            "(result = -4) includes both. Warm-up pitches before first contact "
            "are trimmed per session.",
            style={"fontSize": "12px", "color": "#888", "marginTop": "8px"}),
    ])
```

- [ ] **Step 4: Edit `callbacks.py` — metric re-render**

Add:

```python
    @dash_app.callback(
        Output("pz-heatmap", "children"),
        Input("pz-metric", "value"), State("prac-pitch-data", "data"),
    )
    def _pz_metric(metric, pitch_json):
        from app.dashboards.hitting_practice import charts
        df = _read_json(pitch_json)
        if df.empty:
            return dcc.Graph(figure=charts.pitch_zone_heatmap(df, metric or "contact"))
        d = P.trim_to_first_contact(df)
        return dcc.Graph(figure=charts.pitch_zone_heatmap(d, metric or "contact"))
```

Ensure `dcc` is imported in `callbacks.py` (add to the dash import if missing). The `_render` "zones" branch still calls `pitch_zones.render(pitch)` (default metric) — unchanged.

- [ ] **Step 5: Run tests + full suite**

Run: `python -m pytest tests/test_hitting_practice_dash.py -q` then `python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/dashboards/hitting_practice/ tests/test_hitting_practice_dash.py
git commit -m "feat(practice): Pitch Zones black box + Contact/EV/Distance metric toggle"
```

---

### Task 5: Swing Frequency tab — trend + zone chips (tiles removed)

**Files:**
- Modify: `app/dashboards/hitting_practice/tabs/swing_frequency.py`
- Modify: `app/dashboards/hitting_practice/callbacks.py` (zone chip toggle/style + ev-body)
- Test: `tests/test_hitting_practice_dash.py` (append)

**Interfaces:**
- `swing_frequency.render(df)` — swing-decision trend graph, then a zone chip row (prefix `sfz`) + `sf-ev-body` container; **no** Swing Freq / Swing Decision tiles (now in the sidebar).
- `swing_frequency.ev_body(df, active_zones)` — the EV/Distance graph filtered to `active_zones`.

- [ ] **Step 1: Write the failing test**

```python
def test_swing_frequency_has_trend_and_zone_chips():
    import inspect
    from app.dashboards.hitting_practice.tabs import swing_frequency as sf
    src = inspect.getsource(sf)
    assert "swing_decision_trend_fig" in src and "sfz" in src
    # tiles removed: no In-Zone Contact% tile label in the tab anymore
    assert "Swing Decision Score" not in src or "trend" in src.lower()


def test_swing_frequency_ev_body_zone_filter():
    import pandas as pd
    from app.dashboards.hitting_practice.tabs import swing_frequency as sf
    df = pd.DataFrame([
        {"zone_section": 5, "exit_velocity": 90.0, "distance_feet": 300.0,
         "result": 1, "is_contact": True, "play_date": "2026-04-01", "px": 0.0, "py": 2.5},
        {"zone_section": 11, "exit_velocity": 70.0, "distance_feet": 100.0,
         "result": 1, "is_contact": True, "play_date": "2026-04-01", "px": 1.0, "py": 2.0},
    ])
    # filtering to zone 5 keeps only that row's data feeding the chart (no crash)
    assert sf.ev_body(df, [5]) is not None
    assert sf.ev_body(df, None) is not None
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_hitting_practice_dash.py -k "swing_frequency_has or ev_body" -v`
Expected: FAIL.

- [ ] **Step 3: Rewrite `swing_frequency.py`**

```python
"""Swing Frequency tab — swing-decision trend + zone-filterable EV/distance."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import practice as P
from app.dashboards.hitting_practice import charts
from app.dashboards.shell import section

_ZONES = list(range(1, 14))  # 1-13


def zone_chip_row(df: pd.DataFrame) -> html.Div:
    present = sorted(int(z) for z in df["zone_section"].dropna().unique()) \
        if not df.empty and "zone_section" in df.columns else _ZONES
    chips = [html.Button(
        f"Z{z}", id={"type": "sfz-chip", "index": z}, n_clicks=0,
        style={"border": "2px solid #9A0021", "background": "#9A0021", "color": "#fff",
               "borderRadius": "12px", "padding": "2px 10px", "margin": "0 4px 4px 0",
               "cursor": "pointer", "fontFamily": "Teko, sans-serif", "fontSize": "14px"})
        for z in present]
    return html.Div([dcc.Store(id="sfz-active", data=present), html.Div(chips)],
                    style={"margin": "6px 0"})


def ev_body(df: pd.DataFrame, active_zones) -> html.Div:
    d = df
    if active_zones is not None and not df.empty and "zone_section" in df.columns:
        d = df[df["zone_section"].isin(active_zones)]
    return html.Div(dcc.Graph(figure=charts.ev_distance_by_pitch(d)))


def render(df: pd.DataFrame) -> html.Div:
    if df.empty:
        return html.Div("No pitch data for these filters.",
                        style={"color": "#555", "padding": "12px"})
    d = P.trim_to_first_contact(df)
    trend = P.swing_decision_trend(d)
    return html.Div([
        section("Swing Decision Score Trend"),
        dcc.Graph(figure=charts.swing_decision_trend_fig(trend)),
        section("Exit Velo & Distance by Pitch"),
        zone_chip_row(d),
        html.Div(id="sf-ev-body", children=ev_body(d, None)),
    ])
```

- [ ] **Step 4: Edit `callbacks.py` — zone chip callbacks**

Ensure `ALL`, `ctx` imported from dash. Add:

```python
    @dash_app.callback(
        Output("sfz-active", "data"),
        Input({"type": "sfz-chip", "index": ALL}, "n_clicks"),
        State("sfz-active", "data"), prevent_initial_call=True,
    )
    def _sfz_toggle(_clicks, active):
        tid = ctx.triggered_id
        if not tid:
            return active
        z = tid["index"]
        active = list(active or [])
        return [x for x in active if x != z] if z in active else active + [z]

    @dash_app.callback(
        Output("sf-ev-body", "children"),
        Input("sfz-active", "data"), State("prac-pitch-data", "data"),
    )
    def _sfz_body(active, pitch_json):
        from app.dashboards.hitting_practice.tabs import swing_frequency as sf
        df = _read_json(pitch_json)
        if df.empty:
            return sf.ev_body(df, active)
        return sf.ev_body(P.trim_to_first_contact(df), active)

    @dash_app.callback(
        Output({"type": "sfz-chip", "index": ALL}, "style"),
        Input("sfz-active", "data"),
        State({"type": "sfz-chip", "index": ALL}, "id"),
    )
    def _sfz_styles(active, ids):
        active = set(active or [])
        out = []
        for i in ids:
            on = i["index"] in active
            out.append({"border": "2px solid #9A0021",
                        "background": "#9A0021" if on else "#fff",
                        "color": "#fff" if on else "#9A0021",
                        "borderRadius": "12px", "padding": "2px 10px",
                        "margin": "0 4px 4px 0", "cursor": "pointer",
                        "opacity": "1" if on else ".55",
                        "fontFamily": "Teko, sans-serif", "fontSize": "14px"})
        return out
```

- [ ] **Step 5: Run tests + full suite**

Run: `python -m pytest tests/test_hitting_practice_dash.py -q` then `python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/dashboards/hitting_practice/ tests/test_hitting_practice_dash.py
git commit -m "feat(practice): Swing Frequency = swing-decision trend + zone-chip EV/distance (tiles to sidebar)"
```

---

### Task 6: Batted Ball tab (replaces Contact Overview)

**Files:**
- Rename/replace: `app/dashboards/hitting_practice/tabs/contact_overview.py` → new `tabs/batted_ball.py` (delete the old file)
- Modify: `app/dashboards/hitting_practice/layout.py` (tab label/value), `callbacks.py` (`_render` routing + import)
- Test: `tests/test_hitting_practice_dash.py` (append; remove Contact-Overview-specific tests)

**Interfaces:**
- `batted_ball.render(plays: pd.DataFrame) -> html.Div` — spray chart + contact-type bar.

- [ ] **Step 1: Write the failing test**

```python
def _has_graph(component):
    """True if a dcc.Graph appears anywhere in the tree (add once if not present)."""
    from dash import dcc
    if isinstance(component, dcc.Graph):
        return True
    ch = getattr(component, "children", None)
    if ch is None or isinstance(ch, str):
        return False
    kids = ch if isinstance(ch, (list, tuple)) else [ch]
    return any(_has_graph(k) for k in kids)


def test_batted_ball_tab_renders():
    import pandas as pd
    from app.dashboards.hitting_practice.tabs import batted_ball
    plays = pd.DataFrame([
        {"horizontal_angle": -30.0, "distance_feet": 200.0, "hit_type": 2},
        {"horizontal_angle": 20.0, "distance_feet": 300.0, "hit_type": 3},
        {"horizontal_angle": 0.0, "distance_feet": 0.0, "hit_type": 0},
    ])
    assert _has_graph(batted_ball.render(plays))
```

(If `_has_graph` is already defined in `tests/test_hitting_practice_dash.py`, don't redefine it — reuse the existing one.)

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_hitting_practice_dash.py -k batted_ball_tab -v`
Expected: FAIL (`batted_ball` module missing).

- [ ] **Step 3: Create `app/dashboards/hitting_practice/tabs/batted_ball.py`**

```python
"""Batted Ball tab — spray chart + contact-type distribution."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import practice as P
from app.dashboards.hitting_practice import charts
from app.dashboards.shell import section


def render(plays: pd.DataFrame) -> html.Div:
    if plays is None or plays.empty:
        return html.Div("No batted-ball data for these filters.",
                        style={"color": "#555", "padding": "12px"})
    spray = P.spray_points(plays)
    counts = P.hit_type_counts(plays)
    return html.Div([
        section("Spray Chart"),
        dcc.Graph(figure=charts.spray_chart_fig(spray)),
        section("Contact Type"),
        dcc.Graph(figure=charts.contact_type_bar(counts)),
    ])
```

Then `git rm app/dashboards/hitting_practice/tabs/contact_overview.py`.

- [ ] **Step 4: Edit `layout.py` tab + `callbacks.py` routing**

In `layout.py`, change the tab from Contact Overview to Batted Ball:

```python
        dcc.Tab(label="Batted Ball", value="batted"),
```

(Replace the existing `dcc.Tab(label="Contact Overview", value="contact")` line; keep the other tabs.)

In `callbacks.py`: update the import `from app.dashboards.hitting_practice.tabs import (... )` to swap `contact_overview` for `batted_ball`. In `_render`, replace the `contact` branch:

```python
        if tab == "batted":
            _, plays, _, _ = _load_all(exclude_test)
            if not plays.empty and start and end and "play_date" in plays.columns:
                plays = plays[pd.to_datetime(plays["play_date"]).between(
                    pd.Timestamp(start), pd.Timestamp(end))]
            if player != "All Players" and not plays.empty:
                plays = plays[plays["player_name"] == player]
            return batted_ball.render(plays)
```

(Delete the old `contact` branch that built KPIs/donut/leaders. `session_tables` branch unchanged.)

- [ ] **Step 5: Run tests + full suite**

Run: `python -m pytest tests/test_hitting_practice_dash.py -q` then `python -m pytest -q`
Expected: PASS. If any test still imports `contact_overview`, delete/update it (it referenced removed behavior).

Grep check: `grep -rn "contact_overview\|hit_type_donut\|top_players_bar\|Contact Overview" app tests` — only intentional leftovers (unused `charts.hit_type_donut`/`top_players_bar` may remain; note them for the final review; no imports of `contact_overview` should remain).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(practice): Batted Ball tab (spray + contact-type bar) replaces Contact Overview"
```

---

### Task 7: Live smoke + review prep

**Files:** none (verification only; scratchpad allowed).

- [ ] **Step 1: Live smoke**

Scratchpad script (not committed): in `create_app().app_context()`:
- `roster_media.player_media_by_name("Andrew Mhoon")` prints a match or blanks.
- Load practice pitch + plays (`P.load_pitch_coords`, `P.load_plays`), confirm `horizontal_angle` present on plays.
- `charts.pitch_zone_heatmap(d, "ev")`, `swing_decision_trend_fig(P.swing_decision_trend(d))`, `spray_chart_fig(P.spray_points(plays))`, `contact_type_bar(P.hit_type_counts(plays))` all build.
- `layout.sidebar(d, "Andrew Mhoon")` and `layout.sidebar(d, "All Players")` render.
- `swing_frequency.render(d)`, `pitch_zones.render(d,"distance")`, `batted_ball.render(plays)` render.

Run: `PYTHONIOENCODING=utf-8 python <scratchpad>/smoke_practice.py`
Expected: all succeed.

- [ ] **Step 2: Update memory + request final review**

Append the outcome to `memory/MEMORY.md` §3h (C done, suite count, any Minors). Then request a whole-branch code review (superpowers:requesting-code-review) for C. After C, the full stack (rebuild → B → A → C) is ready to merge in order.

---

## Notes for the implementer

- The zone chip callbacks mirror the pitching chip pattern (`_lm_toggle`/`_lm_chip_styles`); the sidebar and metric-toggle callbacks mirror the game dashboards' reactive-sidebar pattern.
- `_read_json`, `_load_all`, `layout`, `P` are already defined/imported in `callbacks.py`; add `dcc`, `ALL`, `ctx` to imports where the new callbacks need them.
- `_has_graph` and (optionally) `_collect_ids` helpers already exist in `tests/test_hitting_practice_dash.py` / the catching test file — if `_has_graph` isn't in the practice test file yet, copy the small recursive helper in.
- Keep `hit_type_donut`/`top_players_bar` unused rather than deleting mid-task; the final review can prune them.
- Do not change the date-range filter (from B) or Session Tables.
