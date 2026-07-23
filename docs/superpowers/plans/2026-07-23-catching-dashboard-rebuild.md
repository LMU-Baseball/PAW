# Catching Dashboard Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the `/dash/catching/` dashboard to match the legacy R catcher app (`src/app.R`, "THE CATCHER'S PAW") — stolen/lost-strike framing model, 4 filters, a Static Framing facet tab, and a data-backed Caught Stealing tab replacing the broken Blocking/Throws tabs.

**Architecture:** Rewrite in place (same package `app/dashboards/catching/`, same `/dash/catching/` route, PAW shell). Warehouse-based (`fact_tm_game_pitch`/`dim_tm_game`/`tm_player`). Tasks 1–7 are **additive** (new data functions, new charts, new tab files) so the suite stays green; Task 8 wires layout/callbacks, deletes the old tabs + superseded transforms, and rewrites tests.

**Tech Stack:** Python, Flask, Dash, Plotly, pandas, SQLAlchemy; pytest.

## Global Constraints

- **Warehouse only** — no legacy `GAMES`. Source tables: `fact_tm_game_pitch`, `dim_tm_game`, `tm_player`, `tm_team`. Canonical id = `catcher_id`. LMU = `pitcher_team = 'LOY_LIO'` (`C.LMU_PITCHER_TEAM`), `team_id 78` (`C.LMU_TEAM_ID`).
- **No DB in tabs/charts/tables** — pure `df → components`. Only `selectors.py`, `callbacks.py`, and `app/data/catching.py` touch the warehouse.
- **Split-id sibling union** — keep `_sibling_catcher_ids`; all season/game loaders filter `catcher_id IN (siblings)`.
- **Role scoping** — coach any LMU catcher; player self-only via `selectors.resolve_catcher` (do not change).
- **Brand** — Teko font; crimson `#9A0021`; blue `#0076A5`; transparent `paper_bgcolor`, near-white `plot_bgcolor` so charts read over the palms background.
- **Plate coords (catcher view)** — `_x = plate_loc_side * -12`, `_y = plate_loc_height * 12 - 30`.
- **Provisional metric defs are docstring'd and coach-confirmable** (see spec §10). Reproduce the legacy "Steal%" formulas verbatim (they compute a loss rate — do NOT silently "fix").
- **Run tests** with `python -m pytest -q`. On Windows prefix headless app launches with `PYTHONIOENCODING=utf-8`.
- Spec: `docs/superpowers/specs/2026-07-23-catching-dashboard-rebuild-design.md`.

---

### Task 1: Framing derived columns + filters (data layer)

**Files:**
- Modify: `app/data/catching.py` (add new code near the TRANSFORMS section; do NOT remove old functions yet)
- Test: `tests/test_catching.py` (append new tests)

**Interfaces:**
- Consumes: `app.data.hitting_wh.attack_zone(side_ft, height_ft) -> str` (already imported at top of `catching.py`).
- Produces:
  - `PITCH_SPEED_MAP: dict[str, str]`
  - `add_framing_cols(df: pd.DataFrame) -> pd.DataFrame` — adds columns `Zone`, `InZone` (bool), `PitchSpeed`, `CallType`, `_x`, `_y`. Empty-in → empty-out (same columns when possible).
  - `apply_framing_filters(df, *, bat_side="All", pitcher_throws="All", pitch_speed="All", zone="All") -> pd.DataFrame`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_catching.py`:

```python
def _framing_rows():
    import pandas as pd
    # side_ft, height_ft chosen so |side*12|,|height*12-30| land in/out of the box.
    return pd.DataFrame([
        # In zone (x=0, y=0), called ball -> Lost Strike
        {"plate_loc_side": 0.0, "plate_loc_height": 2.5, "pitch_call": "BallCalled",
         "batter_side": "Right", "pitcher_throws": "Left", "tagged_pitch_type": "Fastball"},
        # Out of zone (x=24in), called strike -> Stolen Strike
        {"plate_loc_side": 2.0, "plate_loc_height": 2.5, "pitch_call": "StrikeCalled",
         "batter_side": "Left", "pitcher_throws": "Right", "tagged_pitch_type": "Slider"},
        # In zone, called strike -> Correct Call
        {"plate_loc_side": 0.0, "plate_loc_height": 2.5, "pitch_call": "StrikeCalled",
         "batter_side": "Right", "pitcher_throws": "Right", "tagged_pitch_type": "ChangeUp"},
        # Swing (InPlay) -> Correct Call regardless of zone
        {"plate_loc_side": 0.0, "plate_loc_height": 2.5, "pitch_call": "InPlay",
         "batter_side": "Left", "pitcher_throws": "Left", "tagged_pitch_type": "Curveball"},
    ])


def test_add_framing_cols_classifies_call_type():
    from app.data import catching as C
    out = C.add_framing_cols(_framing_rows())
    assert list(out["CallType"]) == [
        "Lost Strike", "Stolen Strike", "Correct Call", "Correct Call"]
    assert list(out["InZone"]) == [True, False, True, True]
    assert out.loc[0, "Zone"] == "Heart"
    # catcher-view coords
    assert out.loc[1, "_x"] == -24.0


def test_add_framing_cols_pitch_speed_recode():
    from app.data import catching as C
    out = C.add_framing_cols(_framing_rows())
    assert list(out["PitchSpeed"]) == [
        "Fastball", "Offspeed", "Offspeed", "Offspeed"]


def test_add_framing_cols_empty():
    import pandas as pd
    from app.data import catching as C
    assert C.add_framing_cols(pd.DataFrame()).empty


def test_apply_framing_filters():
    from app.data import catching as C
    df = C.add_framing_cols(_framing_rows())
    assert len(C.apply_framing_filters(df)) == 4  # all "All"
    assert len(C.apply_framing_filters(df, bat_side="Left")) == 2
    assert len(C.apply_framing_filters(df, pitch_speed="Fastball")) == 1
    # rows 0,2,3 are side=0 -> x=0 -> Heart; row 1 is side=2.0 -> x=24in -> Waste
    assert len(C.apply_framing_filters(df, zone="Heart")) == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_catching.py -k "framing_cols or framing_filters" -v`
Expected: FAIL (`AttributeError: module 'app.data.catching' has no attribute 'add_framing_cols'`).

- [ ] **Step 3: Implement in `app/data/catching.py`**

Add after the existing `_col` helper (keep everything above it):

```python
# Fastball/Offspeed recode of tagged_pitch_type (matches legacy src/app.R).
PITCH_SPEED_MAP = {
    "Fastball": "Fastball", "Sinker": "Fastball", "Cutter": "Fastball",
    "Splitter": "Fastball", "TwoSeamFastBall": "Fastball",
    "FourSeamFastBall": "Fastball", "OneSeamFastBall": "Fastball",
    "Slider": "Offspeed", "ChangeUp": "Offspeed", "Changeup": "Offspeed",
    "Curveball": "Offspeed", "Knuckleball": "Offspeed", "Undefined": "Offspeed",
}


def _in_zone(side_ft, height_ft) -> bool:
    """Rulebook strike-zone box in catcher-view inches (PROVISIONAL, coach-
    confirmable). The legacy app used a Trackman InZone DB flag the warehouse
    lacks (zi is NULL). Box matches the solid rectangle drawn in src/app.R."""
    if side_ft is None or height_ft is None or pd.isna(side_ft) or pd.isna(height_ft):
        return False
    return abs(float(side_ft) * 12) <= 10 and abs(float(height_ft) * 12 - 30) <= 13


def add_framing_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Derive Zone / InZone / PitchSpeed / CallType / _x / _y for framing views.

    CallType (PROVISIONAL v1, matches legacy stolen/lost model):
      Stolen Strike = out-of-zone pitch called StrikeCalled
      Lost Strike   = in-zone pitch called BallCalled
      Correct Call  = everything else (incl. swings / in-play — no framing signal)
    """
    if df.empty:
        return df.copy()
    out = df.copy()
    out["Zone"] = [attack_zone(s, h)
                   for s, h in zip(out["plate_loc_side"], out["plate_loc_height"])]
    out["InZone"] = [_in_zone(s, h)
                     for s, h in zip(out["plate_loc_side"], out["plate_loc_height"])]
    out["PitchSpeed"] = (out["tagged_pitch_type"].map(PITCH_SPEED_MAP)
                         .fillna("Offspeed"))
    call = out["pitch_call"].astype(str)
    out["CallType"] = "Correct Call"
    out.loc[(~out["InZone"]) & (call == "StrikeCalled"), "CallType"] = "Stolen Strike"
    out.loc[(out["InZone"]) & (call == "BallCalled"), "CallType"] = "Lost Strike"
    out["_x"] = out["plate_loc_side"] * -12
    out["_y"] = out["plate_loc_height"] * 12 - 30
    return out


def apply_framing_filters(df: pd.DataFrame, *, bat_side="All",
                          pitcher_throws="All", pitch_speed="All",
                          zone="All") -> pd.DataFrame:
    """Apply the 4 legacy framing filters. 'All' = no filter on that dimension.
    Expects columns from add_framing_cols."""
    if df.empty:
        return df.copy()
    out = df
    if bat_side != "All":
        out = out[out["batter_side"] == bat_side]
    if pitcher_throws != "All":
        out = out[out["pitcher_throws"] == pitcher_throws]
    if pitch_speed != "All":
        out = out[out["PitchSpeed"] == pitch_speed]
    if zone != "All":
        out = out[out["Zone"] == zone]
    return out.copy()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_catching.py -k "framing_cols or framing_filters" -v`
Expected: PASS. If the `zone="Heart"` count differs, correct the **test expectation** to the real geometry (row 1 at x=24in is Waste, so expect 3), not the code.

- [ ] **Step 5: Commit**

```bash
git add app/data/catching.py tests/test_catching.py
git commit -m "feat(catching): framing derived columns (stolen/lost) + filters"
```

---

### Task 2: Framing summary table + season tiles (data layer)

**Files:**
- Modify: `app/data/catching.py`
- Test: `tests/test_catching.py` (append)

**Interfaces:**
- Consumes: `add_framing_cols` (Task 1); `_sibling_catcher_ids`, `_in_clause`, `query_df` (existing).
- Produces:
  - `framing_table(df: pd.DataFrame) -> dict` with keys `net_strikes, steal_pct, shadow_net, shadow_steal_pct, heart_net, heart_loss_pct, waste_net, waste_steal_pct` (percent values rounded to 1 dp or `None`).
  - `framing_season_tiles(catcher_id: int) -> dict` with keys `games, pitches, net_strikes, steal_pct` (string values; `"—"` when empty/zero-denominator).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_catching.py`:

```python
def _framing_table_rows():
    import pandas as pd
    # Build explicit CallType/Zone mixes. height=2.5 -> y=0 (in vert range);
    # x sets the zone: 0in Heart, 24in Waste, 11in Shadow.
    def row(side, call):
        return {"plate_loc_side": side, "plate_loc_height": 2.5,
                "pitch_call": call, "batter_side": "Right",
                "pitcher_throws": "Right", "tagged_pitch_type": "Fastball"}
    return pd.DataFrame([
        row(0.0, "StrikeCalled"),   # Heart, in-zone strike -> Correct
        row(0.0, "BallCalled"),     # Heart, in-zone ball  -> Lost (heart)
        row(2.0, "StrikeCalled"),   # Waste(24in), out strike -> Stolen (waste)
        row(0.9167, "StrikeCalled"),  # ~11in Shadow, out-of-box strike -> Stolen (shadow)
    ])


def test_framing_table_math():
    from app.data import catching as C
    df = C.add_framing_cols(_framing_table_rows())
    t = C.framing_table(df)
    # stolen = 2 (waste + shadow), lost = 1 (heart) -> net = 1
    assert t["net_strikes"] == 1
    # Steal% (legacy quirk) = lost / total_takes * 100 = 1/4*100 = 25.0
    assert t["steal_pct"] == 25.0
    assert t["shadow_net"] == 1
    assert t["heart_net"] == -1
    assert t["heart_loss_pct"] == 100.0  # 1 lost / 1 heart take


def test_framing_table_empty():
    import pandas as pd
    from app.data import catching as C
    t = C.framing_table(pd.DataFrame())
    assert t["net_strikes"] == 0 and t["steal_pct"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_catching.py -k framing_table -v`
Expected: FAIL (`has no attribute 'framing_table'`).

- [ ] **Step 3: Implement in `app/data/catching.py`**

```python
def _pct(num, den):
    return None if not den else round(100.0 * num / den, 1)


def framing_table(df: pd.DataFrame) -> dict:
    """Legacy stolen/lost framing summary (PROVISIONAL; formulas verbatim from
    src/app.R, incl. the 'Steal%' = lost/total quirk — coach-confirmable)."""
    empty = {"net_strikes": 0, "steal_pct": None, "shadow_net": 0,
             "shadow_steal_pct": None, "heart_net": 0, "heart_loss_pct": None,
             "waste_net": 0, "waste_steal_pct": None}
    if df.empty:
        return empty
    f = add_framing_cols(df) if "CallType" not in df.columns else df
    ct, zone = f["CallType"], f["Zone"]
    stolen = ct == "Stolen Strike"
    lost = ct == "Lost Strike"
    total = len(f)
    shadow = zone == "Shadow"
    heart = zone == "Heart"
    waste = zone.isin(["Waste", "Chase"])
    return {
        "net_strikes": int(stolen.sum() - lost.sum()),
        "steal_pct": _pct(lost.sum(), total),
        "shadow_net": int((stolen & shadow).sum() - (lost & shadow).sum()),
        "shadow_steal_pct": _pct((stolen & shadow).sum(), shadow.sum()),
        "heart_net": int((stolen & heart).sum() - (lost & heart).sum()),
        "heart_loss_pct": _pct((lost & heart).sum(), heart.sum()),
        "waste_net": int((stolen & waste).sum() - (lost & waste).sum()),
        "waste_steal_pct": _pct((lost & waste).sum(), waste.sum()),
    }


def framing_season_tiles(catcher_id: int) -> dict:
    """Season sidebar tiles: games, pitches, net strikes, steal% (SQL aggregate,
    sibling-id union). InZone box mirrors _in_zone in SQL."""
    ids = _sibling_catcher_ids(catcher_id)
    marks, params = _in_clause(ids)
    df = query_df(
        f"""
        SELECT COUNT(DISTINCT game_id) AS games,
               COUNT(*) AS pitches,
               SUM(pitch_call='StrikeCalled'
                   AND NOT (ABS(plate_loc_side*12) <= 10
                            AND ABS(plate_loc_height*12 - 30) <= 13)) AS stolen,
               SUM(pitch_call='BallCalled'
                   AND (ABS(plate_loc_side*12) <= 10
                        AND ABS(plate_loc_height*12 - 30) <= 13)) AS lost,
               SUM(pitch_call IN ('StrikeCalled','BallCalled','BallinDirt',
                                  'BallIntentional','AutomaticBall')) AS takes
          FROM fact_tm_game_pitch
         WHERE catcher_id IN ({marks})
        """,
        params,
    )
    if df.empty:
        return {"games": "—", "pitches": "—", "net_strikes": "—", "steal_pct": "—"}
    r = df.iloc[0]
    stolen = int(r["stolen"] or 0)
    lost = int(r["lost"] or 0)
    takes = int(r["takes"] or 0)
    steal = _pct(lost, takes)
    return {
        "games": str(int(r["games"] or 0)),
        "pitches": str(int(r["pitches"] or 0)),
        "net_strikes": str(stolen - lost),
        "steal_pct": "—" if steal is None else f"{steal}%",
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_catching.py -k framing_table -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/data/catching.py tests/test_catching.py
git commit -m "feat(catching): legacy framing summary table + season tiles"
```

---

### Task 3: Caught Stealing transforms (data layer)

**Files:**
- Modify: `app/data/catching.py`
- Test: `tests/test_catching.py` (append)

**Interfaces:**
- Consumes: `_col` (existing).
- Produces:
  - `CS_RESULTS: set[str]`
  - `caught_stealing_events(df: pd.DataFrame) -> pd.DataFrame` (adds `Caught` bool + `pop_time`/`exchange_time`/`throw_speed`)
  - `caught_stealing_summary(df: pd.DataFrame) -> dict` keys `attempts, caught, cs_pct, avg_pop`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_catching.py`:

```python
def test_caught_stealing_summary():
    import pandas as pd
    from app.data import catching as C
    df = pd.DataFrame([
        {"play_result": "StolenBase", "pop_time": 2.0, "exchange_time": 0.7,
         "throw_speed": 78.0, "inning": 1, "pitcher_name": "A, B"},
        {"play_result": "CaughtStealing", "pop_time": 1.9, "exchange_time": 0.66,
         "throw_speed": 80.0, "inning": 3, "pitcher_name": "A, B"},
        {"play_result": "Single", "pop_time": None, "exchange_time": None,
         "throw_speed": None, "inning": 4, "pitcher_name": "A, B"},
    ])
    ev = C.caught_stealing_events(df)
    assert len(ev) == 2
    assert list(ev["Caught"]) == [False, True]
    s = C.caught_stealing_summary(df)
    assert s["attempts"] == 2 and s["caught"] == 1
    assert s["cs_pct"] == 50.0
    assert s["avg_pop"] == 1.95


def test_caught_stealing_empty():
    import pandas as pd
    from app.data import catching as C
    s = C.caught_stealing_summary(pd.DataFrame())
    assert s["attempts"] == 0 and s["cs_pct"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_catching.py -k caught_stealing -v`
Expected: FAIL (`has no attribute 'caught_stealing_events'`).

- [ ] **Step 3: Implement in `app/data/catching.py`**

```python
CS_RESULTS = {"StolenBase", "CaughtStealing"}


def caught_stealing_events(df: pd.DataFrame) -> pd.DataFrame:
    """Stolen-base attempts charged on this catcher's pitches. PROVISIONAL v1."""
    if df.empty or "play_result" not in df.columns:
        return df.iloc[0:0].copy() if not df.empty else df.copy()
    out = df[df["play_result"].isin(CS_RESULTS)].copy()
    if out.empty:
        return out
    out["Caught"] = out["play_result"] == "CaughtStealing"
    pop = _col(out, "pop_time", "PopTime")
    exch = _col(out, "exchange_time", "ExchangeTime")
    thr = _col(out, "throw_speed", "ThrowSpeed")
    import numpy as np
    out["pop_time"] = out[pop] if pop else np.nan
    out["exchange_time"] = out[exch] if exch else np.nan
    out["throw_speed"] = out[thr] if thr else np.nan
    return out


def caught_stealing_summary(df: pd.DataFrame) -> dict:
    ev = caught_stealing_events(df)
    n = len(ev)
    if n == 0:
        return {"attempts": 0, "caught": 0, "cs_pct": None, "avg_pop": None}
    caught = int(ev["Caught"].sum())
    pops = ev["pop_time"].dropna()
    return {
        "attempts": n,
        "caught": caught,
        "cs_pct": round(100.0 * caught / n, 1),
        "avg_pop": None if pops.empty else round(float(pops.mean()), 2),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_catching.py -k caught_stealing -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/data/catching.py tests/test_catching.py
git commit -m "feat(catching): caught-stealing transforms"
```

---

### Task 4: Charts rewrite (zone frame + stolen/lost scatter + facets)

**Files:**
- Modify: `app/dashboards/catching/charts.py` (replace file contents)
- Test: `tests/test_catching_dash.py` (append chart tests)

**Interfaces:**
- Consumes: `C.add_framing_cols`, `C.apply_framing_filters` (Tasks 1); `shell.CRIMSON`.
- Produces:
  - `CALLTYPE_COLORS: dict`
  - `framing_scatter(df: pd.DataFrame) -> go.Figure`
  - `framing_facets(df: pd.DataFrame, by: str, title: str) -> go.Figure`
  - (keep `_zone_frame(fig)` private helper)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_catching_dash.py`:

```python
def test_framing_scatter_has_calltype_traces():
    from app.dashboards.catching import charts
    fig = charts.framing_scatter(_sample_df())
    names = {t.name for t in fig.data}
    # at least one CallType series present; figure builds without error
    assert names & {"Stolen Strike", "Lost Strike", "Correct Call"}


def test_framing_facets_builds():
    from app.dashboards.catching import charts
    fig = charts.framing_facets(_sample_df(), by="batter_side", title="Batter Side")
    assert fig is not None
```

Also update `_sample_df()` at the top of `tests/test_catching_dash.py` to include the columns framing needs (`batter_side`, `pitcher_throws`, `tagged_pitch_type`):

```python
def _sample_df():
    return pd.DataFrame([
        {"pitch_call": "StrikeCalled", "play_result": "Undefined",
         "plate_loc_side": 1.5, "plate_loc_height": 2.5, "batter_side": "Right",
         "pitcher_throws": "Left", "tagged_pitch_type": "Fastball",
         "inning": 1, "pitcher_name": "A, B", "pop_time": None},
        {"pitch_call": "BallCalled", "play_result": "Undefined",
         "plate_loc_side": 0.0, "plate_loc_height": 2.5, "batter_side": "Left",
         "pitcher_throws": "Right", "tagged_pitch_type": "Slider",
         "inning": 3, "pitcher_name": "A, B", "pop_time": None},
        {"pitch_call": "InPlay", "play_result": "CaughtStealing",
         "plate_loc_side": -0.2, "plate_loc_height": 2.1, "batter_side": "Right",
         "pitcher_throws": "Right", "tagged_pitch_type": "ChangeUp",
         "inning": 6, "pitcher_name": "A, B", "pop_time": 1.9},
    ])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_catching_dash.py -k "framing_scatter or framing_facets" -v`
Expected: FAIL (`module 'app.dashboards.catching.charts' has no attribute 'framing_scatter'` / old `framing_scatter` signature differs).

- [ ] **Step 3: Replace `app/dashboards/catching/charts.py`**

```python
"""Plotly figures for the catching dashboard (pure functions of pitch DataFrames).

Framing scatter/facets use the legacy stolen/lost color scheme over a catcher-view
strike-zone frame (home-plate pentagon + nested rulebook/Heart/Shadow rectangles).
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from app.data import catching as C

CALLTYPE_COLORS = {
    "Stolen Strike": "#000000",
    "Lost Strike": "#9A0021",
    "Correct Call": "#cccccc",
}
_ORDER = ["Correct Call", "Stolen Strike", "Lost Strike"]  # draw grey first


def _zone_frame(fig, row=None, col=None):
    """Catcher-view zone frame in inches (matches src/app.R)."""
    def seg(x0, y0, x1, y1):
        fig.add_shape(type="line", x0=x0, y0=y0, x1=x1, y1=y1,
                      line=dict(color="black", width=1), row=row, col=col)
    def rect(x0, y0, x1, y1, dash=None, width=1.5):
        fig.add_shape(type="rect", x0=x0, y0=y0, x1=x1, y1=y1,
                      line=dict(color="black", width=width,
                                dash=dash) if dash else dict(color="black", width=width),
                      fillcolor="rgba(0,0,0,0)", row=row, col=col)
    # home-plate pentagon
    seg(-9, -21.5, 9, -21.5); seg(-9, -21.5, -9, -23.5); seg(9, -21.5, 9, -23.5)
    seg(-9, -23.5, 0, -25); seg(9, -23.5, 0, -25)
    # rulebook box (solid) + Heart + wide (dashed)
    rect(-10, -13, 10, 13, width=1.5)
    rect(-7.25, -8.75, 7.25, 8.75, dash="dash", width=1)
    rect(-13.5, -16, 13.5, 16, dash="dash", width=1)


def _base_axes(fig, row=None, col=None):
    fig.update_xaxes(range=[-40, 40], visible=False, row=row, col=col)
    fig.update_yaxes(range=[-25, 25], visible=False, row=row, col=col)


def _scatter_traces(fig, d, row=None, col=None, showlegend=True):
    for ct in _ORDER:
        sub = d[d["CallType"] == ct]
        if sub.empty:
            continue
        fig.add_trace(go.Scatter(
            x=sub["_x"], y=sub["_y"], mode="markers", name=ct,
            legendgroup=ct, showlegend=showlegend,
            marker=dict(color=CALLTYPE_COLORS[ct], size=9,
                        line=dict(width=0.5, color="#666")),
            hovertext=sub["pitch_call"].astype(str), hoverinfo="text",
        ), row=row, col=col)


def framing_scatter(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    _zone_frame(fig)
    if not df.empty:
        d = C.add_framing_cols(df) if "CallType" not in df.columns else df
        d = d[d["plate_loc_side"].notna() & d["plate_loc_height"].notna()]
        _scatter_traces(fig, d)
    _base_axes(fig)
    fig.update_layout(
        title="Zone Location — Catcher View", showlegend=True,
        margin=dict(l=20, r=20, t=40, b=20), height=460,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"),
    )
    return fig


def framing_facets(df: pd.DataFrame, by: str, title: str) -> go.Figure:
    d = C.add_framing_cols(df) if not df.empty else df
    vals = sorted(d[by].dropna().unique()) if not d.empty and by in d.columns else []
    n = max(1, len(vals))
    fig = make_subplots(rows=1, cols=n, subplot_titles=[str(v) for v in vals] or [title])
    for i, v in enumerate(vals, start=1):
        _zone_frame(fig, row=1, col=i)
        _scatter_traces(fig, d[d[by] == v], row=1, col=i, showlegend=(i == 1))
        _base_axes(fig, row=1, col=i)
    if not vals:
        _zone_frame(fig, row=1, col=1); _base_axes(fig, row=1, col=1)
    fig.update_layout(
        title=title, height=380, margin=dict(l=10, r=10, t=60, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"),
    )
    return fig
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_catching_dash.py -k "framing_scatter or framing_facets" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/catching/charts.py tests/test_catching_dash.py
git commit -m "feat(catching): stolen/lost framing scatter + facet charts"
```

---

### Task 5: Overall Framing tab (rewrite `tabs/framing.py`)

**Files:**
- Modify: `app/dashboards/catching/tabs/framing.py` (replace contents)
- Test: `tests/test_catching_dash.py` (append)

**Interfaces:**
- Consumes: `C.apply_framing_filters`, `C.framing_table`, `charts.framing_scatter`, `tables.df_table`, `shell.section`.
- Produces:
  - `FILTER_DEFS` (list of dropdown specs) — used by tests + wiring.
  - `body(df, *, bat_side, pitcher_throws, pitch_speed, zone) -> html.Div` (scatter + summary table; the filtered content)
  - `render(df) -> html.Div` (filter row with dropdown ids `fr-bat`/`fr-throws`/`fr-speed`/`fr-zone` + `fr-body` container)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_catching_dash.py`:

```python
def test_framing_tab_has_filter_ids():
    from app.dashboards.catching.tabs import framing
    comp = framing.render(_sample_df())
    ids = _collect_ids(comp)
    assert {"fr-bat", "fr-throws", "fr-speed", "fr-zone", "fr-body"} <= ids


def test_framing_body_builds():
    from app.dashboards.catching.tabs import framing
    comp = framing.body(_sample_df(), bat_side="All", pitcher_throws="All",
                        pitch_speed="All", zone="All")
    assert comp is not None
```

Add this helper near the top of `tests/test_catching_dash.py` if not already present:

```python
def _collect_ids(component):
    """Recursively gather all component ids in a Dash layout tree."""
    ids = set()

    def walk(c):
        if c is None or isinstance(c, str):
            return
        if isinstance(c, (list, tuple)):
            for x in c:
                walk(x)
            return
        cid = getattr(c, "id", None)
        if isinstance(cid, str):
            ids.add(cid)
        walk(getattr(c, "children", None))

    walk(component)
    return ids
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_catching_dash.py -k "framing_tab or framing_body" -v`
Expected: FAIL.

- [ ] **Step 3: Replace `app/dashboards/catching/tabs/framing.py`**

```python
"""Overall Framing tab: 4 legacy filters + stolen/lost scatter + summary table."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import catching as C
from app.dashboards.catching import charts, tables
from app.dashboards.shell import section

FILTER_DEFS = [
    ("fr-bat", "Batter Hand", ["All", "Left", "Right"]),
    ("fr-throws", "Pitcher Hand", ["All", "Left", "Right"]),
    ("fr-speed", "Pitch Speed", ["All", "Fastball", "Offspeed"]),
    ("fr-zone", "Zone Location", ["All", "Heart", "Shadow", "Chase", "Waste"]),
]

_TABLE_LABELS = {
    "net_strikes": "Net Strikes", "steal_pct": "Steal%",
    "shadow_net": "Shadow Net", "shadow_steal_pct": "Shadow Steal%",
    "heart_net": "Heart Net", "heart_loss_pct": "Heart LOSS%",
    "waste_net": "Waste Net", "waste_steal_pct": "Waste Steal%",
}


def _fmt(key, val):
    if val is None:
        return "—"
    return f"{val}%" if key.endswith("_pct") else str(val)


def body(df: pd.DataFrame, *, bat_side="All", pitcher_throws="All",
         pitch_speed="All", zone="All") -> html.Div:
    if df.empty:
        return html.Div("No pitch data.")
    f = C.add_framing_cols(df)
    f = C.apply_framing_filters(f, bat_side=bat_side, pitcher_throws=pitcher_throws,
                                pitch_speed=pitch_speed, zone=zone)
    summ = C.framing_table(f)
    table_df = pd.DataFrame([{_TABLE_LABELS[k]: _fmt(k, summ[k]) for k in _TABLE_LABELS}])
    return html.Div([
        dcc.Graph(figure=charts.framing_scatter(f)),
        section("Framing Summary"),
        tables.df_table(table_df, id_="fr-summary"),
    ])


def render(df: pd.DataFrame) -> html.Div:
    filters = []
    for fid, label, opts in FILTER_DEFS:
        filters.append(html.Div([
            html.Label(label, style={"fontWeight": "bold", "fontSize": "14px"}),
            dcc.Dropdown(id=fid, options=[{"label": o, "value": o} for o in opts],
                         value="All", clearable=False, style={"width": "150px"}),
        ]))
    return html.Div([
        section("Overall Framing"),
        html.Div(filters, style={"display": "flex", "gap": "12px",
                                 "flexWrap": "wrap", "marginBottom": "10px"}),
        html.Div(id="fr-body", children=body(df)),
        html.Div("Provisional stolen/lost model (in-zone from plate geometry; "
                 "legacy 'Steal%' = lost/total). Coach-confirmable.",
                 style={"fontSize": "12px", "color": "#888", "marginTop": "8px"}),
    ])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_catching_dash.py -k "framing_tab or framing_body" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/catching/tabs/framing.py tests/test_catching_dash.py
git commit -m "feat(catching): Overall Framing tab (filters + stolen/lost scatter + table)"
```

---

### Task 6: Static Framing tab (new `tabs/static_framing.py`)

**Files:**
- Create: `app/dashboards/catching/tabs/static_framing.py`
- Test: `tests/test_catching_dash.py` (append)

**Interfaces:**
- Consumes: `charts.framing_facets`, `shell.section`.
- Produces: `render(df: pd.DataFrame) -> html.Div`

- [ ] **Step 1: Write the failing test**

```python
def test_static_framing_render():
    from app.dashboards.catching.tabs import static_framing
    comp = static_framing.render(_sample_df())
    assert comp is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_catching_dash.py -k static_framing -v`
Expected: FAIL (`No module named ...static_framing`).

- [ ] **Step 3: Create `app/dashboards/catching/tabs/static_framing.py`**

```python
"""Static Framing tab: 4 faceted stolen/lost scatters (whole-game, unfiltered)."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.dashboards.catching import charts
from app.dashboards.shell import section

_FACETS = [
    ("batter_side", "Batter Side"),
    ("pitcher_throws", "Pitcher Side"),
    ("PitchSpeed", "Pitch Speed"),
    ("Zone", "Zone Location"),
]


def render(df: pd.DataFrame) -> html.Div:
    if df.empty:
        return html.Div("No pitch data.")
    graphs = []
    for by, title in _FACETS:
        graphs.append(section(title))
        graphs.append(dcc.Graph(figure=charts.framing_facets(df, by=by, title=title)))
    return html.Div(graphs)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_catching_dash.py -k static_framing -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/catching/tabs/static_framing.py tests/test_catching_dash.py
git commit -m "feat(catching): Static Framing facet tab"
```

---

### Task 7: Caught Stealing tab (new `tabs/caught_stealing.py`)

**Files:**
- Create: `app/dashboards/catching/tabs/caught_stealing.py`
- Test: `tests/test_catching_dash.py` (append)

**Interfaces:**
- Consumes: `C.caught_stealing_events`, `C.caught_stealing_summary`, `tables.df_table`, `shell.CRIMSON`, `shell.section`.
- Produces: `render(df: pd.DataFrame) -> html.Div`

- [ ] **Step 1: Write the failing test**

```python
def test_caught_stealing_render_with_attempt():
    from app.dashboards.catching.tabs import caught_stealing
    comp = caught_stealing.render(_sample_df())  # sample has 1 CaughtStealing
    assert comp is not None


def test_caught_stealing_render_empty():
    import pandas as pd
    from app.dashboards.catching.tabs import caught_stealing
    comp = caught_stealing.render(pd.DataFrame([
        {"play_result": "Single", "pitch_call": "InPlay",
         "plate_loc_side": 0.0, "plate_loc_height": 2.5}]))
    assert comp is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_catching_dash.py -k caught_stealing_render -v`
Expected: FAIL (`No module named ...caught_stealing`).

- [ ] **Step 3: Create `app/dashboards/catching/tabs/caught_stealing.py`**

```python
"""Caught Stealing tab: attempt tiles + per-attempt table (real SB/CS outcomes)."""
from __future__ import annotations

import pandas as pd
from dash import html

from app.data import catching as C
from app.dashboards.catching import tables
from app.dashboards.shell import CRIMSON, section


def _tile(label, value):
    return html.Div([
        html.Div(str(value), style={"fontSize": "28px", "fontWeight": "bold",
                                    "color": CRIMSON}),
        html.Div(label, style={"fontSize": "14px", "color": "#555"}),
    ], style={"textAlign": "center", "padding": "10px 14px",
              "backgroundColor": "rgba(255,255,255,0.85)", "borderRadius": "8px",
              "minWidth": "110px"})


def _fmt(v, suffix=""):
    return "—" if v is None else f"{v}{suffix}"


def render(df: pd.DataFrame) -> html.Div:
    summ = C.caught_stealing_summary(df)
    tiles = html.Div([
        _tile("Attempts", summ["attempts"]),
        _tile("Caught", summ["caught"]),
        _tile("CS%", _fmt(summ["cs_pct"], "%")),
        _tile("Avg Pop (s)", _fmt(summ["avg_pop"])),
    ], style={"display": "flex", "gap": "10px", "flexWrap": "wrap",
              "marginBottom": "12px"})

    ev = C.caught_stealing_events(df)
    if ev.empty:
        table = html.Div("No stolen-base attempts recorded for this game.",
                         style={"color": "#555", "padding": "8px"})
    else:
        show = pd.DataFrame({
            "Inn": ev.get("inning"),
            "Pitcher": ev.get("pitcher_name"),
            "Result": ev["Caught"].map({True: "Caught", False: "Stolen"}),
            "Pop (s)": ev["pop_time"].round(2),
            "Exch (s)": ev["exchange_time"].round(2),
            "Throw (mph)": ev["throw_speed"].round(1),
        })
        table = tables.df_table(show, id_="cs-table")

    return html.Div([section("Caught Stealing"), tiles, table])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_catching_dash.py -k caught_stealing_render -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/catching/tabs/caught_stealing.py tests/test_catching_dash.py
git commit -m "feat(catching): Caught Stealing tab"
```

---

### Task 8: Wire layout + callbacks, remove Blocking/Throws + dead transforms, green suite

**Files:**
- Modify: `app/dashboards/catching/layout.py` (sidebar tiles + tab set)
- Modify: `app/dashboards/catching/callbacks.py` (tab routing + framing filter callback)
- Delete: `app/dashboards/catching/tabs/blocking.py`, `app/dashboards/catching/tabs/throws.py`
- Modify: `app/data/catching.py` (remove superseded transforms + constants)
- Modify: `tests/test_catching.py` (remove tests of deleted functions)
- Modify: `tests/test_catching_dash.py` (update mount/tab tests; drop blocking/throws tab tests)

**Interfaces:**
- Consumes: `framing`, `static_framing`, `caught_stealing` tab modules; `C.framing_season_tiles`.
- Produces: fully wired dashboard; component ids `catcher-dd`/`game-dd`/`scoreboard`/`sidebar`/`tabs`/`selection`/`game-data`/`tab-content` unchanged; tab values `framing`/`static`/`caught`.

- [ ] **Step 1: Update `layout.py` sidebar tiles**

In `layout.py`, replace the `summ = C.season_summary(...)` block and the tiles grid inside `sidebar()`:

```python
    prof = C.catcher_profile(int(catcher_id))
    summ = C.framing_season_tiles(int(catcher_id))
    photo = prof["photo"] or PHOTO_PLACEHOLDER
    jersey = f"#{prof['jersey']} · " if prof["jersey"] else ""
    meta = " · ".join([x for x in (prof["class_year"], prof["position"]) if x])
    return html.Div([
        html.Img(src=photo, style={"width": "100%", "borderRadius": "8px",
                                   "border": "4px solid white",
                                   "background": "rgba(255,255,255,0.6)"}),
        html.Div(f"{jersey}{prof['name'] or '—'}",
                 style={"fontSize": "26px", "fontWeight": "bold", "marginTop": "8px"}),
        html.Div(meta, style={"fontSize": "16px", "color": "#555"}),
        html.Div([_tile("GAMES", summ["games"]), _tile("PITCHES", summ["pitches"]),
                  _tile("NET STRIKES", summ["net_strikes"]),
                  _tile("STEAL%", summ["steal_pct"])],
                 style={"display": "grid", "gridTemplateColumns": "1fr 1fr",
                        "gap": "6px", "marginTop": "10px"}),
        html.Div("Season framing tiles (provisional stolen/lost model).",
                 style={"fontSize": "12px", "color": "#888", "marginTop": "4px"}),
    ], style={"padding": "8px"})
```

Replace the `tabs = dcc.Tabs(...)` block in `serve_layout()`:

```python
    tabs = dcc.Tabs(id="tabs", value="framing", children=[
        dcc.Tab(label="Overall Framing", value="framing"),
        dcc.Tab(label="Static Framing", value="static"),
        dcc.Tab(label="Caught Stealing", value="caught"),
    ])
```

- [ ] **Step 2: Update `callbacks.py`**

Replace the tab imports and `_render_tab`, and add the framing-filter callback:

```python
from app.dashboards.catching.tabs import framing, static_framing, caught_stealing
```

```python
    @dash_app.callback(
        Output("tab-content", "children"),
        Input("tabs", "value"), Input("game-data", "data"),
    )
    def _render_tab(tab, data_json):
        df = _read_game_df(data_json)
        if df.empty:
            return html.Div("No pitch data for this selection.",
                            style={"padding": "12px", "color": "#555"})
        if tab == "framing":
            return framing.render(df)
        if tab == "static":
            return static_framing.render(df)
        if tab == "caught":
            return caught_stealing.render(df)
        return html.Div()

    @dash_app.callback(
        Output("fr-body", "children"),
        Input("fr-bat", "value"), Input("fr-throws", "value"),
        Input("fr-speed", "value"), Input("fr-zone", "value"),
        State("game-data", "data"),
    )
    def _framing_body(bat, throws, speed, zone, data_json):
        df = _read_game_df(data_json)
        if df.empty:
            return html.Div("No pitch data.")
        return framing.body(df, bat_side=bat or "All", pitcher_throws=throws or "All",
                            pitch_speed=speed or "All", zone=zone or "All")
```

Update the import line to include `State`:

```python
from dash import Input, Output, State, html
```

- [ ] **Step 3: Delete old tab files**

```bash
git rm app/dashboards/catching/tabs/blocking.py app/dashboards/catching/tabs/throws.py
```

- [ ] **Step 4: Remove superseded transforms from `app/data/catching.py`**

Delete these now-unused symbols: `season_summary`, `takes`, `framing_by_zone`, `framing_overall`, `framing_shadow`, `framing_by_batter_side`, `_is_dirt_row`, `dirt_events`, `blocking_summary`, `throw_attempts`, `throws_summary`, and the module constants `_TAKE_CALLS`, `_STRIKE_CALLS`, `_DIRT_CALLS`, `_PASSED_WILD`, `_LOW_BALL_CALLS`. Keep `_col` (used by caught-stealing). Keep everything listed under "Kept" in spec §5.

- [ ] **Step 5: Update tests for removed functions**

In `tests/test_catching.py`, delete any tests exercising the removed functions (old `takes`/`framing_by_zone`/`framing_overall`/`blocking_summary`/`throws_summary`/`season_summary`). In `tests/test_catching_dash.py`, delete tests importing `tabs.blocking` or `tabs.throws`; keep the selector role-scoping tests and update the mount test:

```python
def test_build_catching_dash_mounts(server):
    rules = {r.rule for r in server.url_map.iter_rules()}
    assert "/dash/catching/" in rules


def test_all_tabs_render(server):
    from app.dashboards.catching.tabs import framing, static_framing, caught_stealing
    df = _sample_df()
    assert framing.render(df) is not None
    assert static_framing.render(df) is not None
    assert caught_stealing.render(df) is not None
```

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS (no failures; no ImportError from stale references). If anything imports a removed symbol, fix the reference. Confirm no other module imports `season_summary`/`blocking`/`throws` (grep: `python -m pytest` will surface ImportErrors; also `grep -rn "season_summary\|tabs.blocking\|tabs.throws\|throws_summary\|blocking_summary" app tests`).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(catching): wire framing/static/caught tabs; remove blocking/throws + dead transforms"
```

---

### Task 9: Live both-role smoke + final review prep

**Files:** none (verification only; scratchpad script allowed).

- [ ] **Step 1: Live render smoke against the warehouse**

Write a scratchpad script (not committed) that, inside `create_app().app_context()`, picks the first LMU catcher + newest game via `C.wh_lmu_catchers()`/`C.games_for_catcher()`/`C.game_pitches_for()` and calls `framing.render(df)`, `framing.body(df, ...)` with a couple filter combos, `static_framing.render(df)`, `caught_stealing.render(df)` — asserting no exceptions. Also call `C.framing_season_tiles(cid)` and print it.

Run: `PYTHONIOENCODING=utf-8 python <scratchpad>/smoke_catching.py`
Expected: all render calls succeed; tiles print real values.

- [ ] **Step 2: Verify no stale server confusion**

Do NOT assume a running :8050 reflects new Python (see MEMORY §3b GOTCHA). In-process smoke (Step 1) is authoritative. If a live browser check is wanted, restart by port owner first.

- [ ] **Step 3: Update memory + hand off to review**

Append the outcome to `memory/MEMORY.md` §3g (suite count, tabs shipped, any provisional-def confirmations still pending). Then request a whole-branch code review (superpowers:requesting-code-review) before merge.

---

## Notes for the implementer

- Tasks 1–7 are additive: the old `framing.py` keeps importing old data functions until Task 8, so the suite stays green throughout. Do not delete old data functions before Task 8.
- The `_sample_df()` change in Task 4 is shared by later dash tests — make it once.
- Keep provisional metric definitions in docstrings so a coach review can retune them with one-line edits.
