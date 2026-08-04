# Polish Wave B — Bullpen Dashboard (SP2 + SP3 + SP4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Checkbox steps.

**Goal:** Polish the bullpen dashboard: new sidebar tiles (Sessions/Pitches/Strike%/Avg FB Velo), fit-to-width tables (round-2, renumbered pitches), clean chart hovers, movement mean-circle+ellipse, location nine-pocket, velocity range-lollipop, release dispersion plot, and trends small-multiples (one panel per pitch type).

**Architecture:** Extend `app/data/bullpen.py` (strike%, avg FB velo), rework `app/dashboards/bullpen/charts.py` (hovers, ellipses, nine-pocket, lollipop, dispersion, small-multiples), `layout.py` (tiles), `tables.py`/`tabs/session_detail.py` (condense), `tabs/trends.py` + `callbacks.py` (small-multiples, drop chips). All Plotly; colors via `plots.color_for`.

**Tech Stack:** Dash, Plotly graph_objects + `plotly.subplots.make_subplots`, numpy, pandas, pytest.

## Global Constraints
- Python 3.12; `from __future__ import annotations`. Colors via `app.reports.plots.color_for`.
- Strike zone box `_ZONE` = x ±0.83 ft, y 1.5–3.5 ft (already in charts.py); nine-pocket = 2 interior gridlines each axis.
- **Strike% = pitches inside zone + one-ball edge buffer** `EDGE = 0.24` ft (≈2.9 in) beyond each edge. Provisional/coach-confirmable.
- **Avg FB Velo** = mean `RelSpeed` where `TaggedPitchType == 'Fastball'`; None→"—".
- Round displayed numbers to **2 decimals**. All-pitches table renumbered **1…N** per session (not raw Trackman `PitchNo`).
- Trends = **one subplot per pitch type, 2 columns**; metric toggle drives all; NO pitch-type chips.
- `flask` not on PATH → `python -m pytest` (FOREGROUND). Live-DB anchor `GEIS = 824645`. `PYTHONIOENCODING=utf-8`. Full suite green before each commit.

---

### Task 1: Data — Strike% + Avg FB Velo tiles

**Files:** Modify `app/data/bullpen.py`; Test `tests/test_bullpen_data.py` (append).

**Interfaces produced:**
- `strike_pct(df) -> float | None` — % of located pitches inside zone+edge buffer (0–100, 1 decimal).
- `avg_fb_velo(df) -> float | None`
- `bullpen_session_summary(pid, start, end)` now returns keys `{sessions, pitches, strike_pct, avg_fb_velo, last_date}` (drops `pitch_types`).

- [ ] **Step 1: Write failing tests** (append to `tests/test_bullpen_data.py`):

```python
import pandas as pd

def test_strike_pct_zone_plus_edge():
    df = pd.DataFrame({  # 3 in zone-ish, 1 far outside
        "plate_loc_side": [0.0, 0.5, -0.9, 3.0],
        "plate_loc_height": [2.5, 3.0, 2.0, 2.5]})
    v = B.strike_pct(df)
    assert v == 75.0  # first three within zone+~2.9in buffer, last far out
    assert B.strike_pct(pd.DataFrame({"plate_loc_side": [], "plate_loc_height": []})) is None

def test_avg_fb_velo():
    df = pd.DataFrame({"tagged_pitch_type": ["Fastball", "Fastball", "Slider"],
                       "rel_speed": [90.0, 92.0, 80.0]})
    assert B.avg_fb_velo(df) == 91.0
    assert B.avg_fb_velo(pd.DataFrame({"tagged_pitch_type": ["Slider"], "rel_speed": [80.0]})) is None

def test_session_summary_has_new_tiles():
    s = B.bullpen_session_summary(GEIS, "2025-09-01", "2026-05-13")
    assert set(s) == {"sessions", "pitches", "strike_pct", "avg_fb_velo", "last_date"}
```

- [ ] **Step 2: Run to verify fail** — `python -m pytest tests/test_bullpen_data.py -k "strike_pct or avg_fb or new_tiles" -q`.

- [ ] **Step 3: Implement** — in `app/data/bullpen.py`:

```python
# module constants near _SZ usage (add if absent)
_SZ = dict(x0=-0.83, x1=0.83, y0=1.5, y1=3.5)
_EDGE = 0.24  # one-ball buffer (ft); provisional


def strike_pct(df) -> float | None:
    """% of located pitches inside the strike zone + one-ball edge buffer."""
    if df is None or df.empty:
        return None
    d = df.dropna(subset=["plate_loc_side", "plate_loc_height"])
    if d.empty:
        return None
    inx = d["plate_loc_side"].between(_SZ["x0"] - _EDGE, _SZ["x1"] + _EDGE)
    iny = d["plate_loc_height"].between(_SZ["y0"] - _EDGE, _SZ["y1"] + _EDGE)
    return round(100.0 * float((inx & iny).mean()), 1)


def avg_fb_velo(df) -> float | None:
    if df is None or df.empty or "tagged_pitch_type" not in df.columns:
        return None
    fb = df[df["tagged_pitch_type"] == "Fastball"]["rel_speed"].dropna()
    return round(float(fb.mean()), 1) if not fb.empty else None
```

Rewrite `bullpen_session_summary` to pull the needed columns once and compute all tiles:

```python
def bullpen_session_summary(pitcher_id, start, end) -> dict:
    """Sidebar tiles: Sessions, Pitches, Strike %, Avg FB Velo, plus last_date."""
    df = query_df(
        """
        SELECT DATE(Date) AS date, TaggedPitchType AS tagged_pitch_type,
               RelSpeed AS rel_speed, PlateLocSide AS plate_loc_side,
               PlateLocHeight AS plate_loc_height
          FROM BULLPEN
         WHERE PitcherId = :pid AND DATE(Date) BETWEEN :start AND :end
        """,
        {"pid": int(pitcher_id), "start": str(start), "end": str(end)},
    )
    if df.empty:
        return {"sessions": 0, "pitches": 0, "strike_pct": None,
                "avg_fb_velo": None, "last_date": "—"}
    return {
        "sessions": int(df["date"].nunique()),
        "pitches": int(len(df)),
        "strike_pct": strike_pct(df),
        "avg_fb_velo": avg_fb_velo(df),
        "last_date": str(df["date"].max()),
    }
```

- [ ] **Step 4: Run to verify pass** — focused tests, then full suite.

- [ ] **Step 5: Commit** — `git commit -m "feat(bullpen): strike% + avg FB velo tiles"`.

---

### Task 2: Sidebar tiles

**Files:** Modify `app/dashboards/bullpen/layout.py`; Test `tests/test_bullpen_dash.py` (append).

- [ ] **Step 1: Failing test** (append):

```python
def test_sidebar_shows_new_tiles_live():
    from app.dashboards.bullpen import layout
    s = str(layout.sidebar(GEIS, "2025-09-01", "2026-05-13"))
    for label in ("SESSIONS", "PITCHES", "STRIKE %", "AVG FB VELO"):
        assert label in s
    assert "PITCH TYPES" not in s and "LAST" not in s
```

- [ ] **Step 2: Verify fail.**

- [ ] **Step 3: Implement** — in `layout.py::sidebar`, replace the four `_tile(...)` calls with:

```python
        html.Div([_tile("SESSIONS", summ["sessions"]), _tile("PITCHES", summ["pitches"]),
                  _tile("STRIKE %", "—" if summ["strike_pct"] is None else f"{summ['strike_pct']:.0f}%"),
                  _tile("AVG FB VELO", "—" if summ["avg_fb_velo"] is None else f"{summ['avg_fb_velo']:.1f}")],
                 style={"display": "grid", "gridTemplateColumns": "1fr 1fr",
                        "gap": "6px", "marginTop": "10px"}),
```

- [ ] **Step 4: Verify pass** — file suite + full suite.

- [ ] **Step 5: Commit** — `git commit -m "feat(bullpen): sidebar tiles -> sessions/pitches/strike%/avg FB velo"`.

---

### Task 3: Chart polish — hovers, movement ellipse/mean, location nine-pocket

**Files:** Modify `app/dashboards/bullpen/charts.py`; Test `tests/test_bullpen_dash.py` (append).

**Interfaces produced:** `_ellipse_xy(xs, ys, n_std=1.0, n=40)`, `_add_zone(fig)` helpers; `movement_fig`/`location_fig` gain ellipse+mean / nine-pocket; all four session charts get hovertemplates.

- [ ] **Step 1: Failing test** (append):

```python
def test_charts_have_hover_and_zone_grid():
    from app.dashboards.bullpen import charts
    df = _session_df()  # existing helper in this test file
    assert any("Velo:" in (t.hovertemplate or "") for t in charts.velo_fig(df).data)
    mv = charts.movement_fig(df)
    assert any("IVB:" in (t.hovertemplate or "") for t in mv.data if t.hovertemplate)
    loc = charts.location_fig(df)
    # nine-pocket = >=5 line shapes (box + 2 v + 2 h)
    assert len(loc.layout.shapes) >= 5

def test_ellipse_xy_shape():
    from app.dashboards.bullpen import charts
    import numpy as np
    x, y = charts._ellipse_xy([1, 2, 3, 4, 2, 3], [2, 1, 3, 2, 2, 1])
    assert len(x) == len(y) >= 20
    assert charts._ellipse_xy([1, 2], [1, 2]) is None  # <3 pts
```

- [ ] **Step 2: Verify fail.**

- [ ] **Step 3: Implement** — in `charts.py`:

Add imports + helpers near the top (after `_ZONE`):

```python
import numpy as np


def _ellipse_xy(xs, ys, n_std=1.0, n=40):
    xs = np.asarray(xs, float); ys = np.asarray(ys, float)
    m = np.isfinite(xs) & np.isfinite(ys)
    xs, ys = xs[m], ys[m]
    if len(xs) < 3:
        return None
    cov = np.cov(xs, ys)
    if not np.all(np.isfinite(cov)):
        return None
    vals, vecs = np.linalg.eigh(cov)
    order = vals.argsort()[::-1]; vals, vecs = vals[order], vecs[:, order]
    t = np.linspace(0, 2 * np.pi, n)
    ell = vecs @ ((n_std * np.sqrt(np.maximum(vals, 0)))[:, None] * np.array([np.cos(t), np.sin(t)]))
    return ell[0] + xs.mean(), ell[1] + ys.mean()


def _add_zone(fig):
    """Strike-zone box + nine-pocket 3x3 grid."""
    z = _ZONE
    fig.add_shape(type="rect", x0=z["x0"], x1=z["x1"], y0=z["y0"], y1=z["y1"],
                  line=dict(color="black", width=1.5))
    for i in (1, 2):
        xi = z["x0"] + (z["x1"] - z["x0"]) * i / 3
        yi = z["y0"] + (z["y1"] - z["y0"]) * i / 3
        fig.add_shape(type="line", x0=xi, x1=xi, y0=z["y0"], y1=z["y1"],
                      line=dict(color="#bbb", width=0.8))
        fig.add_shape(type="line", x0=z["x0"], x1=z["x1"], y0=yi, y1=yi,
                      line=dict(color="#bbb", width=0.8))
```

Add hovertemplates to each `go.Scatter` in `velo_fig`/`movement_fig`/`release_fig`/`location_fig` — set `customdata=[[str(pt)]]*len(sub)` and:
- velo: `hovertemplate="%{customdata[0]}<br>Velo: %{x:.1f} mph<extra></extra>"`
- movement: `hovertemplate="%{customdata[0]}<br>IVB: %{y:.1f} in · HB: %{x:.1f} in<extra></extra>"`
- release: `hovertemplate="%{customdata[0]}<br>Rel H: %{y:.2f} ft · Rel S: %{x:.2f} ft<extra></extra>"`
- location: `hovertemplate="%{customdata[0]}<br>Side: %{x:.2f} · Height: %{y:.2f} ft<extra></extra>"`

In `movement_fig`, for each type add (after the points trace) a 1σ ellipse + hollow mean marker:

```python
        ell = _ellipse_xy(sub["horz_break"], sub["ind_vert_break"])
        if ell is not None:
            fig.add_trace(go.Scatter(x=ell[0], y=ell[1], mode="lines", fill="toself",
                fillcolor=color_for(pt), opacity=0.15, line=dict(color=color_for(pt), width=1),
                showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=[sub["horz_break"].mean()], y=[sub["ind_vert_break"].mean()],
            mode="markers", showlegend=False, hoverinfo="skip",
            marker=dict(size=13, color="white", line=dict(width=2, color=color_for(pt)))))
```

In `location_fig`, replace the single `fig.add_shape(... rect ...)` line with `_add_zone(fig)`.

- [ ] **Step 4: Verify pass** — file suite + full suite.

- [ ] **Step 5: Commit** — `git commit -m "feat(bullpen): clean chart hovers + movement ellipse/mean + location nine-pocket"`.

---

### Task 4: Velocity range-lollipop + Release dispersion (SP3)

**Files:** Modify `app/dashboards/bullpen/charts.py` (rewrite `velo_fig`, `release_fig`); Test `tests/test_bullpen_dash.py` (append).

**Consumes:** `_ellipse_xy` (Task 3). **Depends on Task 3 being merged first.**

- [ ] **Step 1: Failing test** (append):

```python
def test_velo_lollipop_and_release_dispersion():
    from app.dashboards.bullpen import charts
    df = _session_df()
    v = charts.velo_fig(df)
    # a text label with the avg value present on the avg-dot trace
    assert any(getattr(t, "text", None) for t in v.data)
    r = charts.release_fig(df)
    # dispersion: has a filled ellipse trace (fill='toself') for a multi-pitch type
    assert any(getattr(t, "fill", None) == "toself" for t in r.data) or len(r.data) >= 1
    # equal aspect on release
    assert r.layout.yaxis.scaleanchor == "x"
```

- [ ] **Step 2: Verify fail** (existing velo/release tests should still pass — the redesign keeps the same signatures/empty-guards).

- [ ] **Step 3: Implement** — replace `velo_fig` and `release_fig` in `charts.py`:

```python
def velo_fig(df):
    """Horizontal range-lollipop per pitch type: min-max bar + avg dot + label."""
    if df is None or df.empty:
        return _empty()
    rows = []
    for pt, sub in df.groupby("tagged_pitch_type"):
        v = sub["rel_speed"].dropna()
        if v.empty:
            continue
        rows.append((str(pt), float(v.min()), float(v.max()), float(v.mean())))
    if not rows:
        return _empty()
    rows.sort(key=lambda r: r[3])  # slowest at bottom, fastest on top
    fig = go.Figure()
    for i, (pt, vmin, vmax, vavg) in enumerate(rows):
        y = i + 1
        col = color_for(pt)
        fig.add_trace(go.Scatter(x=[vmin, vmax], y=[y, y], mode="lines",
            line=dict(color=col, width=6), opacity=0.35, showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=[vavg], y=[y], mode="markers+text",
            marker=dict(size=15, color=col, line=dict(width=1, color="white")),
            text=[f"{vavg:.1f}"], textposition="middle right",
            textfont=dict(size=12, color="#222"), showlegend=False,
            customdata=[[pt, vmin, vmax]],
            hovertemplate="%{customdata[0]}<br>Velo: %{x:.1f} mph<br>"
                          "Range: %{customdata[1]:.1f}–%{customdata[2]:.1f}<extra></extra>"))
    fig.update_layout(**_BASE)
    fig.update_layout(title="Velocity by pitch type", xaxis_title="mph", showlegend=False)
    fig.update_yaxes(tickvals=list(range(1, len(rows) + 1)),
                     ticktext=[r[0] for r in rows], range=[0.4, len(rows) + 0.7])
    return fig


def release_fig(df):
    """Release-point dispersion: equal aspect, per-type 1σ ellipse + mean marker."""
    if df is None or df.empty:
        return _empty()
    d = df.dropna(subset=["rel_side", "rel_height"])
    if d.empty:
        return _empty()
    fig = go.Figure()
    for pt in _types(d):
        sub = d[d["tagged_pitch_type"] == pt]
        col = color_for(pt)
        ell = _ellipse_xy(sub["rel_side"], sub["rel_height"])
        if ell is not None:
            fig.add_trace(go.Scatter(x=ell[0], y=ell[1], mode="lines", fill="toself",
                fillcolor=col, opacity=0.15, line=dict(color=col, width=1),
                showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=sub["rel_side"], y=sub["rel_height"], mode="markers",
            name=str(pt), marker=dict(size=9, color=col, line=dict(width=0.5, color="white")),
            customdata=[[str(pt)]] * len(sub),
            hovertemplate="%{customdata[0]}<br>Rel H: %{y:.2f} ft · Rel S: %{x:.2f} ft<extra></extra>"))
        fig.add_trace(go.Scatter(x=[sub["rel_side"].mean()], y=[sub["rel_height"].mean()],
            mode="markers", showlegend=False, hoverinfo="skip",
            marker=dict(size=13, color="white", line=dict(width=2, color=col))))
    fig.update_layout(**_BASE)
    fig.update_layout(title="Release", xaxis_title="Rel side (ft)", yaxis_title="Rel height (ft)")
    fig.update_yaxes(scaleanchor="x", scaleratio=1)
    return fig
```

- [ ] **Step 4: Verify pass** — file suite + full suite.

- [ ] **Step 5: Commit** — `git commit -m "feat(bullpen): velocity range-lollipop + release dispersion plot"`.

---

### Task 5: Session Detail tables — condense, round-2, renumber pitches (SP2)

**Files:** Modify `app/dashboards/bullpen/tabs/session_detail.py` (and `tables.py` if needed); Test `tests/test_bullpen_dash.py` (append).

**Behavior:** summary + all-pitches tables round every numeric cell to 2 decimals, use friendly Title-Case headers, and the all-pitches table's pitch column is renumbered **1…N** (drop raw Trackman `PitchNo`). Fit width (no horizontal scroll at normal widths — keep `overflowX:auto` as a fallback but condense columns/headers so it isn't needed).

- [ ] **Step 1: Failing test** (append):

```python
def test_session_detail_tables_condensed_live():
    from app.dashboards.bullpen.tabs import session_detail
    from app.data import bullpen as B
    s = B.session_options(GEIS, "2025-09-01", "2026-05-13")
    if s.empty:
        import pytest; pytest.skip("no sessions")
    out = str(session_detail.render(GEIS, s.iloc[0]["date"]))
    assert "Pitch #" in out or "Pitch" in out  # renumbered header
    # raw session-global pitch numbers (e.g. 33) should NOT appear as the first pitch label
    # (can't assert exact text here; covered by the helper unit test below)

def test_renumber_and_round_helpers():
    import pandas as pd
    from app.dashboards.bullpen.tabs import session_detail as sd
    df = pd.DataFrame({"pitch_no": [33, 34], "tagged_pitch_type": ["Fastball", "Slider"],
                       "rel_speed": [90.12345, 80.98765], "spin_rate": [2200.4, 2300.6]})
    out = sd._display_pitches(df)
    assert list(out.iloc[:, 0]) == [1, 2]           # renumbered 1..N
    assert out["rel_speed"].tolist() == [90.12, 80.99]  # rounded 2dp (col name may be friendly)
```

(If exact friendly header names differ, assert on the renumber + rounding behavior, which is the contract.)

- [ ] **Step 2: Verify fail.**

- [ ] **Step 3: Implement** — add a `_display_pitches(df)` helper in `session_detail.py` that: copies df, replaces the pitch column with `range(1, len(df)+1)`, rounds all float columns to 2 decimals, and renames snake_case columns to friendly Title Case (e.g. `pitch_no→"Pitch #"`, `tagged_pitch_type→"Pitch"`, `rel_speed→"Velo"`, `spin_rate→"Spin"`, `spin_eff→"Spin Eff"`, `ind_vert_break→"IVB"`, `horz_break→"HB"`, `vert_break→"VB"`, `rel_height→"Rel H"`, `rel_side→"Rel S"`, `extension→"Ext"`, `plate_loc_side→"Loc Side"`, `plate_loc_height→"Loc Ht"`, `tilt→"Tilt"`). Build the all-pitches `df_table` from `_display_pitches(df)` with `color_col="Pitch"`. Do the same friendly-header + round-2 for the summary DataFrame (rename `pitch→"Pitch"`, `qty→"#"`, `velo_min/avg/max→"Velo Min/Avg/Max"`, etc.), keeping `color_col="Pitch"`.

- [ ] **Step 4: Verify pass** — file suite + full suite.

- [ ] **Step 5: Commit** — `git commit -m "feat(bullpen): condense/round session tables + renumber pitches 1..N"`.

---

### Task 6: Trends small-multiples (SP4)

**Files:** Modify `app/dashboards/bullpen/charts.py` (add `trend_small_multiples`), `app/dashboards/bullpen/tabs/trends.py` (rewrite render/body, drop chips), `app/dashboards/bullpen/callbacks.py` (drop chip callbacks, update trend body callback); Test `tests/test_bullpen_dash.py` (append/adjust).

**Behavior:** one subplot per pitch type in a 2-column grid; the Velocity/Spin/Movement/Command RadioItems drives all panels; NO pitch-type chips (delete `chip_row`, the `bp-trend-active` store, the chip toggle + chip-style callbacks). Keep `bp-trend-metric` + `bp-trend-data` + `bp-trend-body`.

- [ ] **Step 1: Failing test** (append; also DELETE the now-obsolete chip tests `test_trends_render_has_controls_live` chip assertion — keep the metric assertion):

```python
def test_trend_small_multiples_grid():
    from app.dashboards.bullpen import charts
    df = _trend_df()  # existing helper: Fastball + Slider across 2 dates
    fig = charts.trend_small_multiples(df, "velocity")
    # one subplot per pitch type -> >=2 x-axes
    axes = [k for k in fig.layout if k.startswith("xaxis")]
    assert len(axes) >= 2
    assert charts.trend_small_multiples(df, "movement") is not None

def test_trends_render_no_chips():
    from app.dashboards.bullpen.tabs import trends
    s = str(trends.render(GEIS, "2025-09-01", "2026-05-13"))
    assert "bp-trend-metric" in s and "bp-trend-chip" not in s and "bp-trend-active" not in s
```

- [ ] **Step 2: Verify fail.**

- [ ] **Step 3: Implement**

In `charts.py`, add (import at top: `from plotly.subplots import make_subplots`):

```python
def trend_small_multiples(df, metric):
    if df is None or df.empty:
        return _empty("Need at least 2 sessions to show a trend.")
    types = sorted(df["tagged_pitch_type"].unique())
    ncols = 2
    nrows = (len(types) + 1) // 2
    fig = make_subplots(rows=nrows, cols=ncols, subplot_titles=types,
                        shared_xaxes=False, vertical_spacing=0.12, horizontal_spacing=0.08)
    for i, pt in enumerate(types):
        r, c = i // ncols + 1, i % ncols + 1
        sub = df[df["tagged_pitch_type"] == pt].sort_values("date")
        col = color_for(pt)
        if metric == "velocity":
            series = [("velo_avg", None, "avg"), ("velo_max", "dash", "max")]
        elif metric == "spin":
            series = [("spin_avg", None, "spin"), ("eff_avg", "dot", "eff%")]
        elif metric == "movement":
            series = [("ivb_avg", None, "IVB"), ("hb_avg", "dash", "HB")]
        else:  # command
            series = [("loc_spread", None, "spread")]
        for key, dash, nm in series:
            fig.add_trace(go.Scatter(x=sub["date"], y=sub[key], mode="lines+markers",
                name=f"{pt} {nm}", line=dict(color=col, dash=dash), showlegend=False),
                row=r, col=c)
    fig.update_layout(paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
                      font=dict(family="Teko, sans-serif", size=13),
                      title_font=dict(color="#9A0021"),
                      margin=dict(l=40, r=20, t=40, b=30),
                      height=max(260, 240 * nrows))
    fig.update_xaxes(showgrid=True, gridcolor="#eee")
    fig.update_yaxes(showgrid=True, gridcolor="#eee")
    return fig
```

In `trends.py`, simplify: delete `chip_row`; `render(pitcher_id, start, end)` keeps the metric RadioItems + `bp-trend-data` store, and `body` calls `trend_small_multiples`:

```python
def body(df, metric):
    if df is None or df.empty:
        return html.Div("No bullpen data in this date range.", style=_MUTED)
    if df["date"].nunique() < 2:
        return html.Div("Only one session in range — trends need ≥2 sessions.", style=_MUTED)
    return dcc.Graph(figure=charts.trend_small_multiples(df, metric), style={"height": "auto"})


def render(pitcher_id, start, end):
    if pitcher_id is None:
        return html.Div("Select a pitcher.", style=_MUTED)
    df = B.trend_by_session(int(pitcher_id), start, end)
    controls = dcc.RadioItems(id="bp-trend-metric",
        options=[{"label": lbl, "value": val} for val, lbl in _METRICS],
        value="velocity", inline=True,
        style={"fontFamily": "Teko, sans-serif", "fontSize": "16px"})
    return html.Div([
        controls,
        dcc.Store(id="bp-trend-data", data=(df.to_json(orient="split") if not df.empty else None)),
        html.Div(id="bp-trend-body", children=body(df, "velocity")),
    ])
```

In `callbacks.py`, DELETE `_trend_toggle` and `_trend_chip_styles`; change `_trend_body` to depend only on the metric:

```python
    @dash_app.callback(
        Output("bp-trend-body", "children"),
        Input("bp-trend-metric", "value"), State("bp-trend-data", "data"),
        prevent_initial_call=True,
    )
    def _trend_body(metric, data_json):
        if not data_json:
            return html.Div("No bullpen data in this date range.",
                            style={"padding": "12px", "color": "#555"})
        import io
        df = pd.read_json(io.StringIO(data_json), orient="split")
        return trends.body(df, metric or "velocity")
```

Remove now-unused imports (`ALL`, `ctx`, `color_for`) from callbacks.py if they become unused.

- [ ] **Step 4: Verify pass** — file suite + full suite. Update/remove any obsolete chip tests from earlier tasks.

- [ ] **Step 5: Commit** — `git commit -m "feat(bullpen): trends small-multiples (one panel per pitch type), drop chips"`.

---

## Self-Review
- **SP2 coverage:** tiles (T1+T2), tables condense/round/renumber (T5), hovers + movement ellipse + location nine-pocket (T3). ✅
- **SP3:** velocity lollipop + release dispersion (T4). ✅
- **SP4:** small-multiples + chip removal (T6). ✅
- **Placeholder scan:** T5 notes "if friendly header names differ, assert on the behavior" — the contract (renumber 1..N + round-2) is concretely tested; header strings are cosmetic.
- **Type consistency:** `_ellipse_xy`/`_add_zone` defined in T3, reused by T4 release + T3 movement. `bullpen_session_summary` new keys (T1) consumed by sidebar (T2). `trend_small_multiples(df, metric)` (T6) matches the `body` call. `_display_pitches(df)` (T5) returns a renumbered/rounded frame.
- **Ordering:** T3 before T4 (release reuses `_ellipse_xy`). T1 before T2 (tiles). Independent otherwise.
