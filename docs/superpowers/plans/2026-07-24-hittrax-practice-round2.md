# HitTrax Practice Round 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add real LMU-park home-run determination, fan/scatter consistency, richer batted-ball hovers, a crimson heatmap colorscale, and labeled hovers to the HitTrax Practice tab.

**Architecture:** A fence-distance model in `app/data/practice.py` (interpolated from the coach's five field dimensions) classifies each batted ball as fair/foul and HR/not; the distribution fan and landing scatter both consume it. Chart tweaks live in `app/dashboards/hitting_practice/charts.py`. Pure data helpers get unit tests; chart builders get render + structural tests.

**Tech Stack:** Python, Dash, Plotly (graph_objects), pandas, numpy, pytest.

## Global Constraints

- Scope: HitTrax practice dashboard only (`app/data/practice.py`, `app/dashboards/hitting_practice/charts.py`). No other dashboard, no DB/schema change, no new dependency.
- Crimson sequential ramp: light pink `rgb(253,234,238)` → crimson `#9A0021` (same ramp the fan already uses via `_crimson_shade`). Never introduce new brand hues.
- Hit-type colors from `P.HIT_TYPE_COLORS` (GB `#7a5230`, LD `#9A0021`, FB `#0076A5`, Miss/Foul `#5a5a5a`).
- LMU fence dimensions (angle°: ft), our convention negative = left, 0 = center, +45 = RF line: `[-45,-22.5,0,22.5,45] → [326,362,406,365,321]`.
- Home run = **fair** (|angle| ≤ 45°) **and** `distance_feet ≥ fence_distance(angle)`.
- Fan stays fair-only; the scatter shows all batted balls but marks foul + HR distinctly.
- Font on all figures stays `"Teko, sans-serif"`.
- Do NOT run `git stash/reset/checkout/clean`. Only `git add <named files>` + commit.
- Run the full suite with `python -m pytest -q` (currently 290 passing; must stay green).
- Restart the dev server by port owner (`Get-NetTCPConnection -LocalPort 8050 -State Listen`), never by process name.

---

### Task 1: Fence model + ball classification (spray_points flags)

**Files:**
- Modify: `app/data/practice.py` (add `FENCE_ANGLES`/`FENCE_DISTS`/`fence_distance`; extend `spray_points`)
- Test: `tests/test_practice.py` (append)

**Interfaces:**
- Produces: `fence_distance(angle) -> float | np.ndarray` (scalar or array; clamped to ±45°).
- Produces: `spray_points(plays)` now returns columns `[x, y, hit_type_label, distance_feet, exit_velocity, is_foul, is_hr]`; still all batted balls (fair + foul).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_practice.py`:

```python
def test_fence_distance_interpolates_lmu_dimensions():
    import numpy as np
    from app.data import practice as P
    assert round(float(P.fence_distance(0.0))) == 406
    assert round(float(P.fence_distance(-45.0))) == 326
    assert round(float(P.fence_distance(45.0))) == 321
    # interpolates between LF line (326) and LF-center (362)
    mid = float(P.fence_distance(-33.75))
    assert 326 < mid < 362
    # clamps beyond the fair range
    assert float(P.fence_distance(-60.0)) == float(P.fence_distance(-45.0))
    # array input
    out = P.fence_distance(np.array([0.0, 45.0]))
    assert list(np.round(out)) == [406, 321]


def test_spray_points_foul_and_hr_flags():
    import pandas as pd
    from app.data import practice as P
    plays = pd.DataFrame([
        {"horizontal_angle": -45.0, "distance_feet": 340.0, "exit_velocity": 100.0, "hit_type": 3},  # fair, over 326 -> HR
        {"horizontal_angle": -22.5, "distance_feet": 340.0, "exit_velocity": 100.0, "hit_type": 3},  # fair, under 362 -> not HR
        {"horizontal_angle": -60.0, "distance_feet": 250.0, "exit_velocity": 80.0, "hit_type": 2},   # foul
        {"horizontal_angle": 0.0, "distance_feet": 100.0, "exit_velocity": 70.0, "hit_type": 1},     # fair infield
    ])
    pts = P.spray_points(plays)
    assert {"is_foul", "is_hr"} <= set(pts.columns)
    assert list(pts["is_hr"]) == [True, False, False, False]
    assert list(pts["is_foul"]) == [False, False, True, False]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_practice.py::test_fence_distance_interpolates_lmu_dimensions tests/test_practice.py::test_spray_points_foul_and_hr_flags -v`
Expected: FAIL (`fence_distance` missing; `spray_points` lacks flag columns).

- [ ] **Step 3: Implement**

In `app/data/practice.py`, add the fence model near the fan constants:

```python
# LMU field dimensions (coach-supplied): fence carry (ft) by spray angle
# (deg; neg=left, 0=center, +45=RF line). PROVISIONAL (linear between points).
FENCE_ANGLES = [-45.0, -22.5, 0.0, 22.5, 45.0]
FENCE_DISTS = [326.0, 362.0, 406.0, 365.0, 321.0]


def fence_distance(angle):
    """Interpolated LMU fence carry (ft) at a spray angle (deg). Scalar or array;
    clamped to the +/-45 fair range."""
    a = np.clip(np.asarray(angle, dtype=float), -45.0, 45.0)
    return np.interp(a, FENCE_ANGLES, FENCE_DISTS)
```

Replace `spray_points` with (adds the two flag columns):

```python
def spray_points(plays: pd.DataFrame) -> pd.DataFrame:
    """Batted-ball landing points from horizontal_angle + distance_feet.
    x = dist*sin(angle) (neg=left field), y = dist*cos(angle). Batted balls only
    (hit_type 1/2/3), fair AND foul. Carries distance_feet + exit_velocity for
    hover, plus is_foul (|angle|>45) and is_hr (fair & carry>=fence). PROVISIONAL."""
    cols = ["x", "y", "hit_type_label", "distance_feet", "exit_velocity",
            "is_foul", "is_hr"]
    if plays.empty or "horizontal_angle" not in plays.columns:
        return pd.DataFrame(columns=cols)
    d = plays[plays["hit_type"].isin([1, 2, 3])].dropna(
        subset=["horizontal_angle", "distance_feet"]).copy()
    if d.empty:
        return pd.DataFrame(columns=cols)
    angf = d["horizontal_angle"].astype(float).to_numpy()
    distf = d["distance_feet"].astype(float).to_numpy()
    rad = np.radians(angf)
    d["x"] = distf * np.sin(rad)
    d["y"] = distf * np.cos(rad)
    d["hit_type_label"] = d["hit_type"].map(HIT_TYPE_MAP)
    if "exit_velocity" not in d.columns:
        d["exit_velocity"] = np.nan
    d["is_foul"] = np.abs(angf) > 45.0
    d["is_hr"] = (~d["is_foul"].to_numpy()) & (distf >= fence_distance(angf))
    return d[cols].reset_index(drop=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_practice.py::test_fence_distance_interpolates_lmu_dimensions tests/test_practice.py::test_spray_points_foul_and_hr_flags -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/data/practice.py tests/test_practice.py
git commit -m "feat(practice): LMU fence model + fair/HR flags on spray_points"
```

---

### Task 2: spray_fan — fence-based HR ring + per-cell avg EV/distance

**Files:**
- Modify: `app/data/practice.py` (fan constants + `spray_fan`)
- Test: `tests/test_practice.py` (append)

**Interfaces:**
- Consumes: `fence_distance` (Task 1).
- Produces: `spray_fan(plays)` — 15 rows, rings `Infield / Outfield / HR` (Outfield↔HR boundary = fence), columns now include `avg_ev`, `avg_dist` (means per cell, `None` when empty). `count`/`pct` invariants unchanged. New constants `FAN_INFIELD_MAX`, `FAN_RINGS=["Infield","Outfield","HR"]`, `FAN_DISPLAY_MAX=440.0`; `FAN_RING_EDGES` removed.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_practice.py`:

```python
def test_spray_fan_hr_ring_and_averages():
    import pandas as pd
    from app.data import practice as P
    plays = pd.DataFrame([
        {"horizontal_angle": -40.0, "distance_feet": 120.0, "exit_velocity": 85.0, "hit_type": 1},   # Left infield
        {"horizontal_angle": 0.0, "distance_feet": 200.0, "exit_velocity": 90.0, "hit_type": 2},     # Center outfield (fence 406)
        {"horizontal_angle": -40.0, "distance_feet": 360.0, "exit_velocity": 102.0, "hit_type": 3},  # Left HR (fence ~334)
    ])
    fan = P.spray_fan(plays)
    assert len(fan) == 15
    assert round(fan["pct"].sum(), 1) == 100.0
    assert "HR" in set(fan["ring"])
    hr = fan[(fan["ring"] == "HR") & (fan["count"] > 0)]
    assert len(hr) == 1 and int(hr.iloc[0]["count"]) == 1
    assert hr.iloc[0]["avg_ev"] == 102.0 and hr.iloc[0]["avg_dist"] == 360.0
    # empty df -> 15 zero cells, averages None
    fan0 = P.spray_fan(pd.DataFrame(columns=["horizontal_angle", "distance_feet", "hit_type"]))
    assert len(fan0) == 15 and fan0["count"].sum() == 0 and fan0["avg_ev"].isna().all()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_practice.py::test_spray_fan_hr_ring_and_averages -v`
Expected: FAIL (no HR ring / no avg columns).

- [ ] **Step 3: Implement**

In `app/data/practice.py`, replace the fan geometry constants:

```python
# Batted-ball distribution fan geometry (provisional; coach-confirmable).
FAN_WEDGE_EDGES = [-45.0, -27.0, -9.0, 9.0, 27.0, 45.0]     # 5 wedges (degrees)
FAN_DIRECTIONS = ["Left", "Left-Center", "Center", "Right-Center", "Right"]
FAN_INFIELD_MAX = 150.0                                     # Infield/Outfield boundary
FAN_RINGS = ["Infield", "Outfield", "HR"]                  # Outfield/HR boundary = fence
FAN_DISPLAY_MAX = 440.0                                     # outer draw radius (> CF fence 406)
```

(Delete the old `FAN_RING_EDGES = ...` line and the old `FAN_DISPLAY_MAX = 420.0` line.)

Replace `spray_fan` with:

```python
def spray_fan(plays: pd.DataFrame) -> pd.DataFrame:
    """Aggregate FAIR batted balls into a 5-wedge x 3-ring fan (always 15 rows).
    Rings: Infield (0-150), Outfield (150-fence), HR (>= fence at the ball's angle).
    Per cell: count, pct (share of fair batted balls), avg_ev, avg_dist. Geometry
    bounds (a0/a1 deg, r0/r1 ft) are nominal (fence at the wedge mid-angle) for
    annotation placement; the chart draws the fence as a curve. PROVISIONAL."""
    rows = []
    for wi, direction in enumerate(FAN_DIRECTIONS):
        a0, a1 = FAN_WEDGE_EDGES[wi], FAN_WEDGE_EDGES[wi + 1]
        fence_mid = float(fence_distance((a0 + a1) / 2.0))
        bounds = [(0.0, FAN_INFIELD_MAX), (FAN_INFIELD_MAX, fence_mid),
                  (fence_mid, FAN_DISPLAY_MAX)]
        for ri, ring in enumerate(FAN_RINGS):
            r0, r1 = bounds[ri]
            rows.append({"direction": direction, "ring": ring, "wedge_i": wi,
                         "ring_i": ri, "a0": a0, "a1": a1, "r0": r0, "r1": r1,
                         "count": 0, "pct": 0.0, "avg_ev": None, "avg_dist": None})
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
    fen = fence_distance(ang)
    d["_wi"] = np.clip(np.digitize(ang, FAN_WEDGE_EDGES[1:-1]), 0, 4)
    d["_ri"] = np.where(dist < FAN_INFIELD_MAX, 0, np.where(dist >= fen, 2, 1))
    for (wi, ri), sub in d.groupby(["_wi", "_ri"]):
        m = (fan["wedge_i"] == wi) & (fan["ring_i"] == ri)
        fan.loc[m, "count"] = len(sub)
        ev = sub["exit_velocity"].dropna() if "exit_velocity" in sub.columns else sub.iloc[0:0]
        di = sub["distance_feet"].dropna()
        fan.loc[m, "avg_ev"] = round(float(ev.mean()), 1) if len(ev) else None
        fan.loc[m, "avg_dist"] = round(float(di.mean()), 0) if len(di) else None
    # full-precision pct (per-cell rounding can drift the total off 100.0)
    fan["pct"] = 100.0 * fan["count"] / total
    return fan
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_practice.py::test_spray_fan_hr_ring_and_averages tests/test_practice.py::test_spray_fan_15_cells_and_pct_sums_100 -v`
Expected: PASS (both — the round-1 invariant test still holds).

- [ ] **Step 5: Commit**

```bash
git add app/data/practice.py tests/test_practice.py
git commit -m "feat(practice): fence-based HR ring + per-cell avg EV/distance in spray_fan"
```

---

### Task 3: Pitch Zones crimson colorscale + labeled practice hovers

**Files:**
- Modify: `app/dashboards/hitting_practice/charts.py` (`_METRIC_CFG`, `pitch_zone_heatmap`, `ev_distance_by_pitch`; add `_CRIMSON_SCALE`)
- Test: `tests/test_hitting_practice_dash.py` (append)

**Interfaces:**
- Produces: `pitch_zone_heatmap` uses the crimson sequential colorscale for all metrics and a metric-named hover; `ev_distance_by_pitch` traces carry labeled `Pitch #` / `Exit Velo` / `Distance` hovers.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_hitting_practice_dash.py`:

```python
def test_heatmap_uses_crimson_scale_all_metrics():
    import pandas as pd
    from app.dashboards.hitting_practice import charts
    df = pd.DataFrame([{"px": 0.0, "py": 2.5, "result": 1,
                        "exit_velocity": 90.0, "distance_feet": 300.0}])
    for metric in ("contact", "ev", "distance"):
        cs = charts.pitch_zone_heatmap(df, metric).data[0].colorscale
        assert cs != "YlOrRd"
        stops = [str(s[1]).lower().replace(" ", "") for s in cs]
        assert any(v in stops for v in ("#9a0021", "rgb(154,0,33)"))


def test_ev_distance_by_pitch_labeled_hovers():
    import pandas as pd
    from app.dashboards.hitting_practice import charts
    df = pd.DataFrame([
        {"is_contact": True, "play_timestamp": "2026-04-01 10:00:05",
         "exit_velocity": 90.0, "distance_feet": 250.0},
        {"is_contact": True, "play_timestamp": "2026-04-01 10:00:10",
         "exit_velocity": 95.0, "distance_feet": 300.0},
    ])
    tmpls = [t.hovertemplate or "" for t in charts.ev_distance_by_pitch(df).data]
    assert any("Pitch #:" in t and "Exit Velo:" in t for t in tmpls)
    assert any("Pitch #:" in t and "Distance:" in t for t in tmpls)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_hitting_practice_dash.py::test_heatmap_uses_crimson_scale_all_metrics tests/test_hitting_practice_dash.py::test_ev_distance_by_pitch_labeled_hovers -v`
Expected: FAIL (still `YlOrRd`; ev/distance hover unlabeled).

- [ ] **Step 3: Implement**

In `app/dashboards/hitting_practice/charts.py`, add the shared scale near the top (after `_BLUE`):

```python
_CRIMSON_SCALE = [[0.0, "rgb(253,234,238)"], [0.5, "rgb(200,90,110)"], [1.0, "#9A0021"]]
```

Change `_METRIC_CFG` to carry the crimson scale (replace the `"YlOrRd"` entries):

```python
_METRIC_CFG = {
    "contact": ("Contact %", _CRIMSON_SCALE, (0, 100), "Contact Rate"),
    "ev": ("Avg EV (mph)", _CRIMSON_SCALE, (None, None), "Avg Exit Velocity"),
    "distance": ("Avg Dist (ft)", _CRIMSON_SCALE, (None, None), "Avg Distance"),
}
```

In `pitch_zone_heatmap`, replace the `hovertemplate` on the Heatmap with a metric-named one (leave the rest of the function unchanged):

```python
        hovertemplate=("Horizontal: %{x:.2f} ft<br>Height: %{y:.2f} ft<br>"
                       f"{label}: %{{z:.1f}}<extra></extra>"),
```

In `ev_distance_by_pitch`, add hovertemplates to the two traces:

```python
    fig.add_trace(go.Scatter(
        x=d["pitch_n"], y=d["exit_velocity"], name="Exit Velo",
        mode="lines+markers", line=dict(color=CRIMSON),
        hovertemplate="Pitch #: %{x}<br>Exit Velo: %{y:.1f} mph<extra></extra>",
    ), secondary_y=False)
    fig.add_trace(go.Scatter(
        x=d["pitch_n"], y=d["distance_feet"], name="Distance",
        mode="lines+markers", line=dict(color=_BLUE),
        hovertemplate="Pitch #: %{x}<br>Distance: %{y:.0f} ft<extra></extra>",
    ), secondary_y=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_hitting_practice_dash.py::test_heatmap_uses_crimson_scale_all_metrics tests/test_hitting_practice_dash.py::test_ev_distance_by_pitch_labeled_hovers tests/test_hitting_practice_dash.py::test_pitch_zone_heatmap_black_box_and_metric -v`
Expected: PASS (all — the existing black-box test still holds).

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/hitting_practice/charts.py tests/test_hitting_practice_dash.py
git commit -m "feat(practice): crimson heatmap colorscale + labeled EV/distance hovers"
```

---

### Task 4: Distribution fan — fence-curve rings + richer hover + real fence

**Files:**
- Modify: `app/dashboards/hitting_practice/charts.py` (add `_fence_path`; rewrite `_fan_field` + `spray_distribution_fan`)
- Test: `tests/test_hitting_practice_dash.py` (append)

**Interfaces:**
- Consumes: `P.fence_distance`, `P.FAN_INFIELD_MAX`, `P.FAN_DISPLAY_MAX`, and the `avg_ev`/`avg_dist`/`ring_i` columns from Task 2.
- Produces: `_fence_path() -> str` (SVG path of the real fence, reused by Task 5); `spray_distribution_fan` draws fence-curve ring boundaries and a per-cell hover with Balls / Share / Avg EV / Avg Dist.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_hitting_practice_dash.py`:

```python
def test_spray_fan_hover_has_balls_ev_dist():
    import pandas as pd
    from app.dashboards.hitting_practice import charts
    from app.data import practice as P
    plays = pd.DataFrame([
        {"horizontal_angle": -30.0, "distance_feet": 120.0, "exit_velocity": 85.0, "hit_type": 1},
        {"horizontal_angle": 10.0, "distance_feet": 360.0, "exit_velocity": 100.0, "hit_type": 3},
    ])
    fig = charts.spray_distribution_fan(P.spray_fan(plays))
    hovers = [t.hovertext for t in fig.data if getattr(t, "fill", None) == "toself"]
    assert any(("Balls:" in (h or "")) and ("Avg EV:" in (h or ""))
               and ("Avg Dist:" in (h or "")) for h in hovers)
    # empty fan still renders
    assert charts.spray_distribution_fan(P.spray_fan(pd.DataFrame(
        columns=["horizontal_angle", "distance_feet", "hit_type"]))) is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_hitting_practice_dash.py::test_spray_fan_hover_has_balls_ev_dist -v`
Expected: FAIL (hover lacks Balls/Avg EV/Avg Dist).

- [ ] **Step 3: Implement**

In `app/dashboards/hitting_practice/charts.py`, add the fence-path helper (after `_crimson_shade`):

```python
def _fence_path() -> str:
    """SVG path of the real LMU outfield fence (carry vs angle)."""
    degs = np.linspace(-45.0, 45.0, 60)
    fr = P.fence_distance(degs)
    ts = np.radians(degs)
    xs, ys = fr * np.sin(ts), fr * np.cos(ts)
    return "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
```

Replace `_fan_field` so the outer boundary is the real fence:

```python
def _fan_field(fig: go.Figure) -> None:
    L = P.FAN_DISPLAY_MAX
    for sgn in (-1, 1):  # foul lines from home to the display edge
        th = np.radians(45.0) * sgn
        fig.add_shape(type="line", x0=0, y0=0, x1=L * np.sin(th), y1=L * np.cos(th),
                      line=dict(color="#888", width=1))
    fig.add_shape(type="path", path=_fence_path(), line=dict(color="#888", width=1.5))
```

Replace `spray_distribution_fan` with (fence-curve ring boundaries + richer hover):

```python
def spray_distribution_fan(fan_df: pd.DataFrame) -> go.Figure:
    """Filled fan: each cell shaded by its share of fair batted balls, % label,
    and a Balls / Share / Avg EV / Avg Dist hover. Ring boundaries follow the real
    fence curve."""
    fig = go.Figure()
    _fan_field(fig)
    annotations = []
    if fan_df is not None and not fan_df.empty:
        maxpct = max(float(fan_df["pct"].max()), 1e-9)
        for _, row in fan_df.iterrows():
            if row["count"] <= 0:
                continue
            ri = int(row["ring_i"])
            degs = np.linspace(float(row["a0"]), float(row["a1"]), 16)
            ts = np.radians(degs)
            if ri == 0:
                r_in = np.zeros_like(ts); r_out = np.full_like(ts, P.FAN_INFIELD_MAX)
            elif ri == 1:
                r_in = np.full_like(ts, P.FAN_INFIELD_MAX); r_out = P.fence_distance(degs)
            else:
                r_in = P.fence_distance(degs); r_out = np.full_like(ts, P.FAN_DISPLAY_MAX)
            outer = list(zip(r_out * np.sin(ts), r_out * np.cos(ts)))
            inner = list(zip(r_in * np.sin(ts), r_in * np.cos(ts)))[::-1]
            poly = outer + inner
            xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
            ev, di = row["avg_ev"], row["avg_dist"]
            ev_txt = "—" if ev is None or pd.isna(ev) else f"{ev:.0f} mph"
            di_txt = "—" if di is None or pd.isna(di) else f"{di:.0f} ft"
            fig.add_trace(go.Scatter(
                x=xs, y=ys, mode="lines", fill="toself",
                fillcolor=_crimson_shade(float(row["pct"]) / maxpct),
                line=dict(color="#bbb", width=0.5), showlegend=False,
                hovertext=(f"{row['direction']} · {row['ring']}<br>"
                           f"Balls: {int(row['count'])}<br>Share: {row['pct']:.0f}%<br>"
                           f"Avg EV: {ev_txt}<br>Avg Dist: {di_txt}"),
                hoverinfo="text"))
            mid_a = np.radians((float(row["a0"]) + float(row["a1"])) / 2.0)
            mid_r = (float(row["r0"]) + float(row["r1"])) / 2.0
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_hitting_practice_dash.py::test_spray_fan_hover_has_balls_ev_dist tests/test_hitting_practice_dash.py::test_spray_distribution_fan_builds_cells -v`
Expected: PASS (both — the round-1 build test still holds).

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/hitting_practice/charts.py tests/test_hitting_practice_dash.py
git commit -m "feat(practice): fence-curve HR ring + Balls/EV/Dist hover on distribution fan"
```

---

### Task 5: Landing scatter — remove legend, draw fence, mark foul + HR

**Files:**
- Modify: `app/dashboards/hitting_practice/charts.py` (`spray_chart_fig`)
- Test: `tests/test_hitting_practice_dash.py` (append)

**Interfaces:**
- Consumes: `_fence_path` (Task 4); `is_foul`/`is_hr` columns from `spray_points` (Task 1).
- Produces: `spray_chart_fig` with `showlegend=False`, a real fence curve, foul balls as open/greyed markers, HRs as star markers; per-point Distance/Exit-Velo hover with a class tag.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_hitting_practice_dash.py`:

```python
def test_spray_chart_marks_foul_and_hr_no_legend():
    import pandas as pd
    from app.dashboards.hitting_practice import charts
    spray = pd.DataFrame([
        {"x": -50.0, "y": 200.0, "hit_type_label": "Line Drive",
         "distance_feet": 206.0, "exit_velocity": 95.0, "is_foul": False, "is_hr": False},
        {"x": 10.0, "y": 400.0, "hit_type_label": "Fly Ball",
         "distance_feet": 405.0, "exit_velocity": 103.0, "is_foul": False, "is_hr": True},
        {"x": -200.0, "y": 20.0, "hit_type_label": "Line Drive",
         "distance_feet": 200.0, "exit_velocity": 70.0, "is_foul": True, "is_hr": False},
    ])
    fig = charts.spray_chart_fig(spray)
    assert fig.layout.showlegend is False
    syms = [t.marker.symbol for t in fig.data if t.mode == "markers"]
    assert "star" in syms          # HR marker
    assert "circle-open" in syms   # foul marker
    assert any(s.type == "path" for s in fig.layout.shapes)  # fence curve drawn
    # still renders without the flag columns (round-1 contract)
    plain = pd.DataFrame([{"x": -50.0, "y": 200.0, "hit_type_label": "Line Drive",
                           "distance_feet": 206.0, "exit_velocity": 95.0}])
    assert charts.spray_chart_fig(plain) is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_hitting_practice_dash.py::test_spray_chart_marks_foul_and_hr_no_legend -v`
Expected: FAIL (legend on; no star/open markers; generic arc not a fence path... note the round-1 chart already draws a `path` arc, so the specific failing asserts are `showlegend is False`, `"star" in syms`, `"circle-open" in syms`).

- [ ] **Step 3: Implement**

Replace `spray_chart_fig` in `app/dashboards/hitting_practice/charts.py`:

```python
def spray_chart_fig(spray_df: pd.DataFrame) -> go.Figure:
    """Field + batted-ball landing points colored by hit type; foul balls marked
    open/greyed, home runs marked as stars. Real LMU fence drawn."""
    fig = go.Figure()
    L = P.FAN_DISPLAY_MAX
    for sgn in (-1, 1):  # foul lines
        th = np.radians(45.0) * sgn
        fig.add_shape(type="line", x0=0, y0=0, x1=L * np.sin(th), y1=L * np.cos(th),
                      line=dict(color="#888", width=1))
    fig.add_shape(type="path", path=_fence_path(), line=dict(color="#888", width=1.5))
    b = 63.6  # infield diamond (~90ft bases)
    fig.add_shape(type="path", path=f"M 0,0 L {b},{b} L 0,{2*b} L {-b},{b} Z",
                  line=dict(color="#bbb", width=1), fillcolor="rgba(0,0,0,0)")
    if spray_df is not None and not spray_df.empty:
        has_hover = {"distance_feet", "exit_velocity"} <= set(spray_df.columns)
        has_flags = {"is_foul", "is_hr"} <= set(spray_df.columns)
        for label, sub in spray_df.groupby("hit_type_label"):
            color = _HIT_COLORS.get(label, "#5a5a5a")
            if has_flags:
                classes = [
                    ("", sub[~sub["is_foul"] & ~sub["is_hr"]],
                     dict(symbol="circle", color=color, size=8, line=dict(width=0.5, color="#666"))),
                    (" (HR)", sub[sub["is_hr"]],
                     dict(symbol="star", color=color, size=13, line=dict(width=1.2, color="#1a1a1a"))),
                    (" (Foul)", sub[sub["is_foul"]],
                     dict(symbol="circle-open", color="#999", size=8, line=dict(width=1.2, color="#999"))),
                ]
            else:
                classes = [("", sub, dict(symbol="circle", color=color, size=8,
                                          line=dict(width=0.5, color="#666")))]
            for tag, part, marker in classes:
                if part is None or part.empty:
                    continue
                trace = dict(x=part["x"], y=part["y"], mode="markers",
                             name=f"{label}{tag}", marker=marker, showlegend=False)
                if has_hover:
                    trace["customdata"] = part[["distance_feet", "exit_velocity"]].to_numpy()
                    trace["hovertemplate"] = (
                        f"{label}{tag}<br>Distance: %{{customdata[0]:.0f}} ft"
                        "<br>Exit Velo: %{customdata[1]:.1f} mph<extra></extra>")
                fig.add_trace(go.Scatter(**trace))
    fig.update_layout(
        title="Spray Chart", showlegend=False,
        xaxis=dict(range=[-340, 340], visible=False),
        yaxis=dict(range=[-20, L + 20], visible=False, scaleanchor="x", scaleratio=1),
        height=460, margin=dict(l=10, r=10, t=50, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"))
    return fig
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_hitting_practice_dash.py::test_spray_chart_marks_foul_and_hr_no_legend tests/test_hitting_practice_dash.py::test_spray_scatter_hover_has_distance_and_ev tests/test_hitting_practice_dash.py::test_batted_ball_tab_renders -v`
Expected: PASS (all — round-1 hover + tab-render contracts still hold).

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/hitting_practice/charts.py tests/test_hitting_practice_dash.py
git commit -m "feat(practice): landing scatter with real fence, foul/HR markers, no legend"
```

---

### Task 6: Full-suite gate + live smoke

**Files:** none (verification only)

- [ ] **Step 1: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS (≥ 290 + the new tests; 0 failures).

- [ ] **Step 2: Restart the dev server by port owner**

```powershell
Get-NetTCPConnection -LocalPort 8050 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```
Confirm the port is free, then relaunch one instance: `PYTHONIOENCODING=utf-8 python run.py`.

- [ ] **Step 3: Live smoke, both roles**

Log in as coach (`coach@lmu.edu` / `paw2026`) and player (`hitter@lmu.edu` / `paw2026`). On the Practice tab verify:
  - Pitch Zones heatmap renders in the crimson (pink→crimson) ramp for all three metrics; hover names the metric.
  - Swing Frequency "Exit Velo & Distance by Pitch" hover shows labeled `Pitch #` / `Exit Velo` / `Distance`.
  - Batted Ball: the fan's outer ring is HR (fence-bounded); hovering a section shows Balls / Share / Avg EV / Avg Dist; the landing scatter has no right-side legend, draws the real fence, marks foul balls as open/grey and HRs as stars, and the two charts now tell a consistent story.

- [ ] **Step 4: Commit any smoke-fix follow-ups** (only if the smoke surfaces a defect).

---

## Self-Review

**Spec coverage:**
- A (crimson heatmaps) → Task 3. B (labeled hovers) → Task 3. C (fence model + classification) → Task 1. D (scatter: legend/fence/foul/HR) → Task 5. E (fan: HR ring + hover) → Tasks 2 (data) + 4 (chart). Every spec section maps to a task.

**Placeholder scan:** No TBD/TODO/"handle edge cases". All code steps carry real code.

**Type consistency:**
- `fence_distance` (Task 1) consumed by `spray_fan` (Task 2), `_fence_path`/`spray_distribution_fan` (Task 4), `spray_chart_fig` (Task 5) — same signature (scalar/array of degrees → ft).
- `spray_points` flag columns `is_foul`/`is_hr` (Task 1) consumed by `spray_chart_fig` (Task 5).
- `spray_fan` columns `avg_ev`/`avg_dist`/`ring_i` (Task 2) consumed by `spray_distribution_fan` (Task 4).
- `_fence_path` (Task 4) consumed by `spray_chart_fig` (Task 5).
- Constants: `FAN_INFIELD_MAX`, `FAN_DISPLAY_MAX=440`, `FAN_RINGS` (Task 2) consumed by Task 4. `FAN_RING_EDGES` removed in Task 2 — only `spray_fan` referenced it (rewritten same task); the chart uses `ring_i` + `fence_distance`, never `FAN_RING_EDGES`.

**Ordering note:** Task 2 removes `FAN_RING_EDGES` and rewrites `spray_fan` in the same task (no window where a consumer is broken). Task 4's chart depends on Task 2's new columns; Task 5 depends on Task 1 flags + Task 4's `_fence_path`. Round-1 tests (`test_spray_fan_15_cells_and_pct_sums_100`, `test_spray_distribution_fan_builds_cells`, `test_spray_scatter_hover_has_distance_and_ev`, `test_batted_ball_tab_renders`) are all re-run in the relevant task's Step 4 and continue to hold.
