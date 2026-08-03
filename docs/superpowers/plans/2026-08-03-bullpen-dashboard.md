# Bullpen Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone interactive Bullpen Dashboard at `/dash/bullpen/` (card in the Pitching hub) with two tabs — Session Detail and Development Trends — reading the freshly-backfilled `BULLPEN` table.

**Architecture:** New `app/dashboards/bullpen/` Dash package mirroring `app/dashboards/pitching/` (index/selectors/layout/callbacks/tables/charts/tabs). Reuses the shared shell, date-range picker, roster-media sidebar, and `plots.color_for` pitch colors. Extends `app/data/bullpen.py` with range-scoped query helpers. Coach picks any LMU pitcher; players are locked to self.

**Tech Stack:** Flask + Dash, Plotly `graph_objects`, pandas, SQLAlchemy (`app.db.query_df`), pytest (live-DB + pure-function conventions).

## Global Constraints

- Python 3.12; match existing code style (`from __future__ import annotations`, snake_case internals).
- Pitch-type colors ALWAYS via `app.reports.plots.color_for(pt)` (cross-app consistency).
- LMU scope = `PitcherTeam IN ('LOY_MAR','LOY_LIO')` (already encoded as `B.LMU_BULLPEN_TEAMS`).
- `BULLPEN.PitcherId` is the raw Trackman id; a player's own id == `user.trackman_id`.
- Date window is capped: `min_date_allowed = "2025-09-01"`, `max = date.today()`. Every bullpen query the dashboard issues is bounded to `[start, end]` within that window.
- One session = one calendar date per pitcher.
- Command trend metric is a location-spread **proxy** (label it as such), not true command.
- Dash pages use the shared shell — do NOT re-copy brand chrome. Import `header`, `index_string`, `BANNER`, `CRIMSON`, `PHOTO_PLACEHOLDER` from `app.dashboards.shell`.
- Tests that hit the live analytics DB are unguarded (matches `test_pitching_dash.py` / `test_bullpen_data.py`). Known live-data anchor: `GEIS = 824645` (Jake Geis, a real LMU bullpen `PitcherId`).
- Run the suite with `python -m pytest -q`. `flask` is not on PATH in this env — use `python -m flask --app run ...` and prefix `PYTHONIOENCODING=utf-8` for any command that prints non-ASCII.

---

### Task 1: Data-layer helpers + fix stale test

**Files:**
- Modify: `app/data/bullpen.py` (append helpers)
- Test: `tests/test_bullpen_data.py` (add cases; fix the now-broken stale-date test)

**Interfaces:**
- Consumes: existing `query_df`, `_r1`, `LMU_BULLPEN_TEAMS`, `lmu_bullpen_pitchers`.
- Produces:
  - `pitcher_name(pitcher_id) -> str | None`
  - `session_options(pitcher_id, start, end) -> DataFrame[date(str), pitches(int)]` (newest first)
  - `bullpen_session_summary(pitcher_id, start, end) -> dict{sessions,pitches,pitch_types,last_date}`
  - `trend_by_session(pitcher_id, start, end) -> DataFrame[date, tagged_pitch_type, pitches, velo_avg, velo_max, spin_avg, eff_avg, ivb_avg, hb_avg, loc_spread]`

> **Note — the backfill broke `test_max_date_is_stale_2025`.** `bullpen_data_max_date()` now returns `2026-05-13` (BULLPEN was repopulated 2026-08-03). That test asserted the old stale state and must be updated.

- [ ] **Step 1: Write failing tests**

Add to `tests/test_bullpen_data.py`:

```python
import pandas as pd

WINDOW = ("2025-09-01", "2026-05-13")  # bounded window covering the loaded data


def test_pitcher_name_for_geis():
    assert B.pitcher_name(GEIS)  # non-empty "Last, First"
    assert B.pitcher_name(-1) is None


def test_session_options_within_window_newest_first():
    df = B.session_options(GEIS, *WINDOW)
    assert not df.empty and {"date", "pitches"} <= set(df.columns)
    dates = list(df["date"])
    assert dates == sorted(dates, reverse=True)          # newest first
    assert all("2025-09-01" <= d <= "2026-05-13" for d in dates)


def test_bullpen_session_summary_shape():
    s = B.bullpen_session_summary(GEIS, *WINDOW)
    assert set(s) == {"sessions", "pitches", "pitch_types", "last_date"}
    assert s["sessions"] >= 1 and s["pitches"] >= 1 and s["pitch_types"] >= 1


def test_bullpen_session_summary_empty_pitcher():
    s = B.bullpen_session_summary(-1, *WINDOW)
    assert s == {"sessions": 0, "pitches": 0, "pitch_types": 0, "last_date": "—"}


def test_trend_by_session_columns_and_sorting():
    df = B.trend_by_session(GEIS, *WINDOW)
    assert not df.empty
    assert {"date", "tagged_pitch_type", "pitches", "velo_avg", "velo_max",
            "spin_avg", "eff_avg", "ivb_avg", "hb_avg", "loc_spread"} <= set(df.columns)
    # grouped/sorted by (type, date)
    assert list(df[["tagged_pitch_type", "date"]].itertuples(index=False, name=None)) == \
        sorted(df[["tagged_pitch_type", "date"]].itertuples(index=False, name=None))
```

And REPLACE `test_max_date_is_stale_2025` with:

```python
def test_max_date_reflects_backfill():
    # BULLPEN repopulated 2026-08-03; data now runs through 2026.
    assert str(B.bullpen_data_max_date()) >= "2026-01-01"
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_bullpen_data.py -q`
Expected: FAIL (new functions undefined; `test_max_date_reflects_backfill` may already pass — that's fine).

- [ ] **Step 3: Implement**

Append to `app/data/bullpen.py`:

```python
def pitcher_name(pitcher_id) -> str | None:
    """Display name ('Last, First') for a BULLPEN PitcherId, or None."""
    df = query_df("SELECT MAX(Pitcher) AS n FROM BULLPEN WHERE PitcherId = :pid",
                  {"pid": int(pitcher_id)})
    v = df.iloc[0]["n"] if not df.empty else None
    return None if v is None or pd.isna(v) else str(v)


def session_options(pitcher_id, start, end) -> pd.DataFrame:
    """Session dates (newest first) with pitch counts, within [start, end]."""
    df = query_df(
        """
        SELECT DATE(Date) AS date, COUNT(*) AS pitches
          FROM BULLPEN
         WHERE PitcherId = :pid AND DATE(Date) BETWEEN :start AND :end
         GROUP BY DATE(Date)
         ORDER BY date DESC
        """,
        {"pid": int(pitcher_id), "start": str(start), "end": str(end)},
    )
    if not df.empty:
        df["date"] = df["date"].astype(str)
    return df


def bullpen_session_summary(pitcher_id, start, end) -> dict:
    """Sidebar tiles for a pitcher within [start, end]."""
    df = query_df(
        """
        SELECT COUNT(DISTINCT DATE(Date)) AS sessions, COUNT(*) AS pitches,
               COUNT(DISTINCT TaggedPitchType) AS pitch_types, MAX(DATE(Date)) AS last_date
          FROM BULLPEN
         WHERE PitcherId = :pid AND DATE(Date) BETWEEN :start AND :end
        """,
        {"pid": int(pitcher_id), "start": str(start), "end": str(end)},
    )
    if df.empty:
        return {"sessions": 0, "pitches": 0, "pitch_types": 0, "last_date": "—"}
    r = df.iloc[0]
    last = r["last_date"]
    return {
        "sessions": int(r["sessions"] or 0),
        "pitches": int(r["pitches"] or 0),
        "pitch_types": int(r["pitch_types"] or 0),
        "last_date": "—" if last is None or pd.isna(last) else str(last),
    }


def trend_by_session(pitcher_id, start, end) -> pd.DataFrame:
    """Per (date, pitch_type) trend aggregates within [start, end].

    `loc_spread` = RMS distance of (PlateLocSide, PlateLocHeight) from the
    group's mean location — a command-CONSISTENCY proxy (lower = tighter),
    NOT true command (bullpens have no intended-target column). None when a
    group has <2 located pitches.
    """
    cols = ["date", "tagged_pitch_type", "pitches", "velo_avg", "velo_max",
            "spin_avg", "eff_avg", "ivb_avg", "hb_avg", "loc_spread"]
    df = query_df(
        """
        SELECT DATE(Date) AS date, TaggedPitchType AS tagged_pitch_type,
               RelSpeed AS rel_speed, SpinRate AS spin_rate,
               SpinAxis3dSpinEfficiency AS spin_eff,
               InducedVertBreak AS ind_vert_break, HorzBreak AS horz_break,
               PlateLocSide AS plate_loc_side, PlateLocHeight AS plate_loc_height
          FROM BULLPEN
         WHERE PitcherId = :pid AND DATE(Date) BETWEEN :start AND :end
           AND TaggedPitchType IS NOT NULL
        """,
        {"pid": int(pitcher_id), "start": str(start), "end": str(end)},
    )
    if df.empty:
        return pd.DataFrame(columns=cols)
    df["date"] = df["date"].astype(str)
    rows = []
    for (d, pt), sub in df.groupby(["date", "tagged_pitch_type"]):
        loc = sub[["plate_loc_side", "plate_loc_height"]].dropna()
        if len(loc) >= 2:
            cx, cy = loc["plate_loc_side"].mean(), loc["plate_loc_height"].mean()
            spread = round(float((((loc["plate_loc_side"] - cx) ** 2 +
                                   (loc["plate_loc_height"] - cy) ** 2).mean()) ** 0.5), 2)
        else:
            spread = None
        rows.append({
            "date": d, "tagged_pitch_type": pt, "pitches": int(len(sub)),
            "velo_avg": _r1(sub["rel_speed"].mean()), "velo_max": _r1(sub["rel_speed"].max()),
            "spin_avg": _r1(sub["spin_rate"].mean()), "eff_avg": _r1(sub["spin_eff"].mean()),
            "ivb_avg": _r1(sub["ind_vert_break"].mean()), "hb_avg": _r1(sub["horz_break"].mean()),
            "loc_spread": spread,
        })
    return (pd.DataFrame(rows, columns=cols)
            .sort_values(["tagged_pitch_type", "date"]).reset_index(drop=True))
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_bullpen_data.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/data/bullpen.py tests/test_bullpen_data.py
git commit -m "feat(bullpen-dash): range-scoped data helpers + fix stale max-date test"
```

---

### Task 2: Role-aware selectors (pure)

**Files:**
- Create: `app/dashboards/bullpen/__init__.py` (empty)
- Create: `app/dashboards/bullpen/selectors.py`
- Test: `tests/test_bullpen_dash.py` (new)

**Interfaces:**
- Consumes: `app.data.bullpen.lmu_bullpen_pitchers`.
- Produces:
  - `resolve_pitcher(requested_id, *, is_coach, own_trackman_id) -> int | None`
  - `pitcher_options(*, is_coach, own_trackman_id) -> list[dict{label,value}]`
  - `session_dropdown_options(sessions_df) -> list[dict{label,value}]`

- [ ] **Step 1: Write failing tests** — create `tests/test_bullpen_dash.py`:

```python
"""Tests for the Dash bullpen dashboard (selectors, layout, tabs, build)."""
import pandas as pd
import pytest

from app import create_app
from config import Config

GEIS = 824645


@pytest.fixture
def server(tmp_path):
    class T(Config):
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 't.db'}"
    return create_app(T)


def test_resolve_pitcher_player_is_self_only():
    from app.dashboards.bullpen import selectors
    assert selectors.resolve_pitcher(999, is_coach=False, own_trackman_id=None) is None
    assert selectors.resolve_pitcher(999, is_coach=False, own_trackman_id=555) == 555
    assert selectors.resolve_pitcher(999, is_coach=True, own_trackman_id=None) == 999


def test_pitcher_options_coach_nonempty():
    from app.dashboards.bullpen import selectors
    opts = selectors.pitcher_options(is_coach=True, own_trackman_id=None)
    assert opts and {"label", "value"} <= set(opts[0])


def test_session_dropdown_options_labels():
    from app.dashboards.bullpen import selectors
    df = pd.DataFrame({"date": ["2026-05-13", "2026-05-06"], "pitches": [18, 17]})
    opts = selectors.session_dropdown_options(df)
    assert opts[0] == {"label": "2026-05-13 (18)", "value": "2026-05-13"}
    assert selectors.session_dropdown_options(pd.DataFrame(columns=["date", "pitches"])) == []
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_bullpen_dash.py -q`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement** — create `app/dashboards/bullpen/__init__.py` (empty) and `app/dashboards/bullpen/selectors.py`:

```python
"""Role-aware selection helpers for the bullpen dashboard (pure functions).

A player is locked to their own data server-side. BULLPEN.PitcherId IS the
raw Trackman id, so a player's own id == their user.trackman_id (no mapping).
"""
from __future__ import annotations

from app.data import bullpen as B


def resolve_pitcher(requested_id, *, is_coach: bool, own_trackman_id):
    """The PitcherId a request may view. Players are self-only."""
    if not is_coach:
        return int(own_trackman_id) if own_trackman_id is not None else None
    return int(requested_id) if requested_id not in (None, "") else None


def pitcher_options(*, is_coach: bool, own_trackman_id) -> list[dict]:
    df = B.lmu_bullpen_pitchers()
    if is_coach:
        return [{"label": str(r.pitcher), "value": int(r.pitcher_id)}
                for r in df.itertuples()]
    pid = resolve_pitcher(None, is_coach=False, own_trackman_id=own_trackman_id)
    if pid is None:
        return []
    row = df[df["pitcher_id"] == pid]
    label = str(row.iloc[0]["pitcher"]) if not row.empty else str(pid)
    return [{"label": label, "value": pid}] if not row.empty else []


def session_dropdown_options(sessions_df) -> list[dict]:
    """Session-date dropdown options (newest first) from B.session_options()."""
    if sessions_df is None or sessions_df.empty:
        return []
    return [{"label": f"{r.date} ({int(r.pitches)})", "value": str(r.date)}
            for r in sessions_df.itertuples()]
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_bullpen_dash.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/bullpen/__init__.py app/dashboards/bullpen/selectors.py tests/test_bullpen_dash.py
git commit -m "feat(bullpen-dash): role-aware pure selectors"
```

---

### Task 3: Plotly charts

**Files:**
- Create: `app/dashboards/bullpen/charts.py`
- Test: `tests/test_bullpen_dash.py` (append)

**Interfaces:**
- Consumes: `app.reports.plots.color_for`; session df (snake_case cols from `B.session_pitches`); trend df from `B.trend_by_session`.
- Produces: `velo_fig(df)`, `movement_fig(df)`, `release_fig(df)`, `location_fig(df)`, `trend_fig(df, metric, active_types=None)` — all return `plotly.graph_objects.Figure`.

- [ ] **Step 1: Write failing tests** — append to `tests/test_bullpen_dash.py`:

```python
def _session_df():
    return pd.DataFrame({
        "tagged_pitch_type": ["Fastball", "Fastball", "Slider"],
        "rel_speed": [90.1, 91.0, 82.4], "ind_vert_break": [15.0, 16.1, 2.0],
        "horz_break": [8.0, 9.2, -5.0], "rel_side": [1.9, 2.0, 1.8],
        "rel_height": [6.0, 6.1, 5.9], "plate_loc_side": [0.1, -0.2, 0.3],
        "plate_loc_height": [2.5, 3.0, 1.8]})


def _trend_df():
    return pd.DataFrame({
        "date": ["2026-05-06", "2026-05-13", "2026-05-06", "2026-05-13"],
        "tagged_pitch_type": ["Fastball", "Fastball", "Slider", "Slider"],
        "pitches": [10, 12, 6, 7], "velo_avg": [90.0, 91.0, 82.0, 83.0],
        "velo_max": [92.0, 93.0, 84.0, 85.0], "spin_avg": [2200.0, 2250.0, 2400.0, 2450.0],
        "eff_avg": [95.0, 96.0, 40.0, 42.0], "ivb_avg": [15.0, 16.0, 2.0, 1.0],
        "hb_avg": [8.0, 9.0, -5.0, -6.0], "loc_spread": [0.9, 0.7, 1.2, 1.0]})


def test_session_charts_render():
    from app.dashboards.bullpen import charts
    df = _session_df()
    for fn in (charts.velo_fig, charts.movement_fig, charts.release_fig, charts.location_fig):
        assert fn(df) is not None
        assert fn(pd.DataFrame(columns=df.columns)) is not None  # empty -> empty fig, no raise


def test_trend_fig_all_metrics_render():
    from app.dashboards.bullpen import charts
    df = _trend_df()
    for metric in ("velocity", "spin", "movement", "command"):
        fig = charts.trend_fig(df, metric, active_types=["Fastball", "Slider"])
        assert fig is not None and len(fig.data) >= 1
    # empty / one-type filter still returns a figure
    assert charts.trend_fig(df, "velocity", active_types=[]) is not None
    assert charts.trend_fig(pd.DataFrame(columns=df.columns), "velocity") is not None
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_bullpen_dash.py -k "charts or trend_fig" -q`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement** — create `app/dashboards/bullpen/charts.py`:

```python
"""Plotly figure builders for the bullpen dashboard (snake_case bullpen cols).

Interactive counterparts to app/reports/bullpen_plots.py (matplotlib, PDF).
Pitch-type color always via plots.color_for for cross-app consistency.
"""
from __future__ import annotations

import plotly.graph_objects as go

from app.reports.plots import color_for

_BASE = dict(paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
             margin=dict(l=45, r=20, t=42, b=42), showlegend=True,
             font=dict(family="Teko, sans-serif", size=14),
             title_font=dict(color="#9A0021", size=16))
_ZONE = dict(x0=-0.83, x1=0.83, y0=1.5, y1=3.5)  # standard strike-zone box (ft)


def _empty(msg="No data"):
    fig = go.Figure()
    fig.add_annotation(text=msg, showarrow=False, font=dict(size=16, color="#888"))
    fig.update_layout(**_BASE)
    fig.update_xaxes(visible=False); fig.update_yaxes(visible=False)
    return fig


def _types(df):
    return list(df.groupby("tagged_pitch_type").groups)


def velo_fig(df):
    if df is None or df.empty:
        return _empty()
    fig = go.Figure()
    types = _types(df)
    for i, pt in enumerate(types):
        sub = df[df["tagged_pitch_type"] == pt]
        y = len(types) - i
        fig.add_trace(go.Scatter(
            x=sub["rel_speed"], y=[y] * len(sub), mode="markers", name=str(pt),
            marker=dict(size=11, color=color_for(pt), line=dict(width=0.5, color="white"))))
    fig.update_layout(title="Velocity by pitch type", xaxis_title="mph", **_BASE)
    fig.update_yaxes(tickvals=list(range(1, len(types) + 1)), ticktext=list(reversed(types)))
    return fig


def movement_fig(df):
    if df is None or df.empty:
        return _empty()
    fig = go.Figure()
    for pt in _types(df):
        sub = df[df["tagged_pitch_type"] == pt]
        fig.add_trace(go.Scatter(
            x=sub["horz_break"], y=sub["ind_vert_break"], mode="markers", name=str(pt),
            marker=dict(size=10, color=color_for(pt), line=dict(width=0.5, color="white"))))
    fig.add_hline(y=0, line_color="#ccc"); fig.add_vline(x=0, line_color="#ccc")
    fig.update_layout(title="Movement", xaxis_title="HB (in)", yaxis_title="IVB (in)", **_BASE)
    fig.update_yaxes(scaleanchor="x", scaleratio=1)
    return fig


def release_fig(df):
    if df is None or df.empty:
        return _empty()
    fig = go.Figure()
    for pt in _types(df):
        sub = df[df["tagged_pitch_type"] == pt]
        fig.add_trace(go.Scatter(
            x=sub["rel_side"], y=sub["rel_height"], mode="markers", name=str(pt),
            marker=dict(size=10, color=color_for(pt), line=dict(width=0.5, color="white"))))
    fig.update_layout(title="Release", xaxis_title="Rel side (ft)",
                      yaxis_title="Rel height (ft)", **_BASE)
    return fig


def location_fig(df):
    if df is None or df.empty:
        return _empty()
    fig = go.Figure()
    fig.add_shape(type="rect", x0=_ZONE["x0"], x1=_ZONE["x1"], y0=_ZONE["y0"], y1=_ZONE["y1"],
                  line=dict(color="black", width=1.5))
    for pt in _types(df):
        sub = df[df["tagged_pitch_type"] == pt]
        fig.add_trace(go.Scatter(
            x=sub["plate_loc_side"], y=sub["plate_loc_height"], mode="markers", name=str(pt),
            marker=dict(size=9, color=color_for(pt), line=dict(width=0.5, color="white"))))
    fig.update_layout(title="Location", **_BASE)
    fig.update_xaxes(range=[-2.5, 2.5], visible=False)
    fig.update_yaxes(range=[0, 5], visible=False, scaleanchor="x", scaleratio=1)
    return fig


_TREND_TITLES = {
    "velocity": "Velocity trend — avg (solid) / max (dashed)",
    "spin": "Spin trend — rate (solid) / efficiency % (dotted, right axis)",
    "movement": "Movement trend — IVB (solid) / HB (dashed)",
    "command": "Location spread — lower = tighter (consistency proxy)",
}


def trend_fig(df, metric, active_types=None):
    if df is None or df.empty:
        return _empty("Need at least 2 sessions to show a trend.")
    types = active_types if active_types else sorted(df["tagged_pitch_type"].unique())
    fig = go.Figure()
    for pt in types:
        sub = df[df["tagged_pitch_type"] == pt].sort_values("date")
        if sub.empty:
            continue
        col = color_for(pt)
        if metric == "velocity":
            fig.add_trace(go.Scatter(x=sub["date"], y=sub["velo_avg"], mode="lines+markers",
                                     name=f"{pt} avg", line=dict(color=col)))
            fig.add_trace(go.Scatter(x=sub["date"], y=sub["velo_max"], mode="lines+markers",
                                     name=f"{pt} max", line=dict(color=col, dash="dash")))
        elif metric == "spin":
            fig.add_trace(go.Scatter(x=sub["date"], y=sub["spin_avg"], mode="lines+markers",
                                     name=f"{pt} spin", line=dict(color=col)))
            fig.add_trace(go.Scatter(x=sub["date"], y=sub["eff_avg"], mode="lines+markers",
                                     name=f"{pt} eff%", line=dict(color=col, dash="dot"),
                                     yaxis="y2"))
        elif metric == "movement":
            fig.add_trace(go.Scatter(x=sub["date"], y=sub["ivb_avg"], mode="lines+markers",
                                     name=f"{pt} IVB", line=dict(color=col)))
            fig.add_trace(go.Scatter(x=sub["date"], y=sub["hb_avg"], mode="lines+markers",
                                     name=f"{pt} HB", line=dict(color=col, dash="dash")))
        else:  # command
            fig.add_trace(go.Scatter(x=sub["date"], y=sub["loc_spread"], mode="lines+markers",
                                     name=str(pt), line=dict(color=col)))
    fig.update_layout(title=_TREND_TITLES.get(metric, ""), xaxis_title="Session date", **_BASE)
    if metric == "spin":
        fig.update_layout(yaxis2=dict(overlaying="y", side="right", title="eff %"))
    return fig
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_bullpen_dash.py -k "charts or trend_fig" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/bullpen/charts.py tests/test_bullpen_dash.py
git commit -m "feat(bullpen-dash): Plotly session + trend charts"
```

---

### Task 4: Tables helper + Session Detail tab

**Files:**
- Create: `app/dashboards/bullpen/tables.py`
- Create: `app/dashboards/bullpen/tabs/__init__.py` (empty)
- Create: `app/dashboards/bullpen/tabs/session_detail.py`
- Test: `tests/test_bullpen_dash.py` (append)

**Interfaces:**
- Consumes: `B.session_pitches`, `B.summary_by_pitch_type`, `charts.*`, `plots.color_for`.
- Produces: `tables.df_table(df, id_=None, color_col="pitch") -> DataTable`; `session_detail.render(pitcher_id, date) -> html.Div`.

- [ ] **Step 1: Write failing tests** — append to `tests/test_bullpen_dash.py`:

```python
def test_df_table_colors_named_column():
    from app.dashboards.bullpen import tables
    from app.reports.plots import color_for
    df = pd.DataFrame({"pitch": ["Fastball", "Slider"], "qty": [10, 5]})
    tbl = tables.df_table(df, id_="t", color_col="pitch")
    colored = {c.get("color") for c in (tbl.style_data_conditional or [])
               if c.get("if", {}).get("column_id") == "pitch"}
    assert color_for("Fastball") in colored and color_for("Slider") in colored


def test_session_detail_render_live():
    from app.dashboards.bullpen.tabs import session_detail
    from app.data import bullpen as B
    s = B.session_options(GEIS, "2025-09-01", "2026-05-13")
    # GEIS has bullpen data in-window; render must not raise and must include charts.
    if s.empty:
        pytest.skip("no in-window sessions for anchor pitcher")
    out = session_detail.render(GEIS, s.iloc[0]["date"])
    assert out is not None


def test_session_detail_empty_states():
    from app.dashboards.bullpen.tabs import session_detail
    assert "Select a pitcher" in str(session_detail.render(None, None))
    assert "session" in str(session_detail.render(GEIS, None)).lower()
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_bullpen_dash.py -k "df_table or session_detail" -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Create `app/dashboards/bullpen/tables.py`:

```python
"""Dash DataTable builder for the bullpen dashboard (pitch colors via plots)."""
from __future__ import annotations

import pandas as pd
from dash import dash_table

from app.reports.plots import color_for


def df_table(df: pd.DataFrame, id_: str | None = None, color_col: str = "pitch"):
    conditional = []
    if color_col in df.columns:
        for pt in df[color_col].dropna().unique():
            conditional.append({
                "if": {"filter_query": f'{{{color_col}}} = "{pt}"', "column_id": color_col},
                "color": color_for(str(pt)), "fontWeight": "bold"})
    return dash_table.DataTable(
        id=id_ or "bullpen-table",
        columns=[{"name": str(c), "id": str(c)} for c in df.columns],
        data=df.to_dict("records"),
        style_table={"overflowX": "auto"},
        style_cell={"fontFamily": "Teko, sans-serif", "fontSize": "15px",
                    "padding": "4px 8px", "textAlign": "center"},
        style_header={"backgroundColor": "#9A0021", "color": "white", "fontWeight": "bold"},
        style_data_conditional=conditional,
    )
```

Create `app/dashboards/bullpen/tabs/__init__.py` (empty) and `app/dashboards/bullpen/tabs/session_detail.py`:

```python
"""Session Detail tab — one bullpen session in detail (interactive report)."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import bullpen as B
from app.dashboards.bullpen import charts, tables

_MUTED = {"padding": "12px", "color": "#555"}


def render(pitcher_id, date) -> html.Div:
    if pitcher_id is None:
        return html.Div("Select a pitcher.", style=_MUTED)
    if not date:
        return html.Div("No bullpen session in this date range.", style=_MUTED)
    df = B.session_pitches(int(pitcher_id), date)
    if df.empty:
        return html.Div("No pitches for this session.", style=_MUTED)

    summ_df = pd.DataFrame(B.summary_by_pitch_type(df))
    graph = lambda fig: dcc.Graph(figure=fig, style={"height": "340px"})
    charts_grid = html.Div(
        [graph(charts.velo_fig(df)), graph(charts.movement_fig(df)),
         graph(charts.release_fig(df)), graph(charts.location_fig(df))],
        style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "12px"})
    return html.Div([
        tables.df_table(summ_df, id_="bp-summary", color_col="pitch"),
        html.Div(style={"height": "12px"}),
        charts_grid,
        html.H4("All pitches", style={"color": "#9A0021", "marginTop": "14px"}),
        tables.df_table(df, id_="bp-pitches", color_col="tagged_pitch_type"),
    ])
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_bullpen_dash.py -k "df_table or session_detail" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/bullpen/tables.py app/dashboards/bullpen/tabs/
git commit -m "feat(bullpen-dash): tables helper + Session Detail tab"
```

---

### Task 5: Development Trends tab

**Files:**
- Create: `app/dashboards/bullpen/tabs/trends.py`
- Test: `tests/test_bullpen_dash.py` (append)

**Interfaces:**
- Consumes: `B.trend_by_session`, `charts.trend_fig`, `plots.color_for`.
- Produces:
  - `render(pitcher_id, start, end) -> html.Div` (metric RadioItems `bp-trend-metric`, chip row, `dcc.Store` `bp-trend-active` + `bp-trend-data`, body `bp-trend-body`)
  - `chip_row(pitch_types) -> html.Div` (pattern-matched chips `{"type":"bp-trend-chip","index":pt}`)
  - `body(df, metric, active) -> component`

- [ ] **Step 1: Write failing tests** — append to `tests/test_bullpen_dash.py`:

```python
def test_trends_render_has_controls_live():
    from app.dashboards.bullpen.tabs import trends
    s = str(trends.render(GEIS, "2025-09-01", "2026-05-13"))
    assert "bp-trend-metric" in s and "bp-trend-active" in s and "bp-trend-body" in s


def test_trends_render_empty_pitcher():
    from app.dashboards.bullpen.tabs import trends
    assert "Select a pitcher" in str(trends.render(None, "2025-09-01", "2026-05-13"))


def test_trends_body_one_session_note():
    from app.dashboards.bullpen.tabs import trends
    one = _trend_df().iloc[[0, 2]].copy()   # both rows share date 2026-05-06
    assert "2 session" in str(trends.body(one, "velocity", ["Fastball", "Slider"])).lower() \
        or "one session" in str(trends.body(one, "velocity", ["Fastball", "Slider"])).lower()


def test_trends_body_two_sessions_renders_graph():
    from app.dashboards.bullpen.tabs import trends
    out = trends.body(_trend_df(), "velocity", ["Fastball", "Slider"])
    assert out is not None and "Graph" in str(type(out)) or "dcc.Graph" in str(out)
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_bullpen_dash.py -k trends -q`
Expected: FAIL.

- [ ] **Step 3: Implement** — create `app/dashboards/bullpen/tabs/trends.py`:

```python
"""Development Trends tab — per-pitch-type metric trends across sessions."""
from __future__ import annotations

from dash import dcc, html

from app.data import bullpen as B
from app.dashboards.bullpen import charts
from app.reports.plots import color_for

_MUTED = {"padding": "12px", "color": "#555"}
_METRICS = [("velocity", "Velocity"), ("spin", "Spin"),
            ("movement", "Movement"), ("command", "Command")]


def chip_row(pitch_types) -> html.Div:
    chips = []
    for pt in pitch_types:
        col = color_for(pt)
        chips.append(html.Button(
            str(pt), id={"type": "bp-trend-chip", "index": str(pt)}, n_clicks=0,
            style={"border": f"2px solid {col}", "background": col, "color": "#fff",
                   "borderRadius": "14px", "padding": "3px 12px", "margin": "0 6px 6px 0",
                   "cursor": "pointer", "fontFamily": "Teko, sans-serif", "fontSize": "15px"}))
    return html.Div(chips, style={"margin": "8px 0"})


def body(df, metric, active):
    if df is None or df.empty:
        return html.Div("No bullpen data in this date range.", style=_MUTED)
    if df["date"].nunique() < 2:
        return html.Div("Only one session in range — trends need ≥2 sessions.", style=_MUTED)
    return dcc.Graph(figure=charts.trend_fig(df, metric, active), style={"height": "460px"})


def render(pitcher_id, start, end) -> html.Div:
    if pitcher_id is None:
        return html.Div("Select a pitcher.", style=_MUTED)
    df = B.trend_by_session(int(pitcher_id), start, end)
    types = sorted(df["tagged_pitch_type"].unique().tolist()) if not df.empty else []
    controls = html.Div([
        dcc.RadioItems(id="bp-trend-metric",
                       options=[{"label": lbl, "value": val} for val, lbl in _METRICS],
                       value="velocity", inline=True,
                       style={"fontFamily": "Teko, sans-serif", "fontSize": "16px"}),
        chip_row(types),
    ])
    return html.Div([
        controls,
        dcc.Store(id="bp-trend-active", data=types),
        dcc.Store(id="bp-trend-data", data=(df.to_json(orient="split") if not df.empty else None)),
        html.Div(id="bp-trend-body", children=body(df, "velocity", types)),
    ])
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_bullpen_dash.py -k trends -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/bullpen/tabs/trends.py tests/test_bullpen_dash.py
git commit -m "feat(bullpen-dash): Development Trends tab"
```

---

### Task 6: Layout (shell, sidebar, selector row, tabs, stores)

**Files:**
- Create: `app/dashboards/bullpen/layout.py`
- Test: `tests/test_bullpen_dash.py` (append)

**Interfaces:**
- Consumes: `selectors.*`, `B.session_options`, `B.bullpen_session_summary`, `B.pitcher_name`, shell `header`/`BANNER`/`CRIMSON`/`PHOTO_PLACEHOLDER`, `date_range.date_picker`, `roster_media.player_media_by_name`.
- Produces: `serve_layout() -> html.Div`; `sidebar(pitcher_id, start, end) -> html.Div`; module constants `WINDOW_MIN = "2025-09-01"`.

- [ ] **Step 1: Write failing tests** — append to `tests/test_bullpen_dash.py`:

```python
def test_sidebar_shows_range_tiles_live():
    from app.dashboards.bullpen import layout
    s = str(layout.sidebar(GEIS, "2025-09-01", "2026-05-13"))
    for label in ("SESSIONS", "PITCHES", "PITCH TYPES", "LAST"):
        assert label in s


def test_serve_layout_wires_tabs_and_window(server):
    import inspect
    from app.dashboards.bullpen import layout
    src = inspect.getsource(layout.serve_layout)
    assert '"session"' in src and '"trends"' in src
    assert "Session Detail" in src and "Development Trends" in src
    assert layout.WINDOW_MIN == "2025-09-01"
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_bullpen_dash.py -k "sidebar or serve_layout" -q`
Expected: FAIL.

- [ ] **Step 3: Implement** — create `app/dashboards/bullpen/layout.py`:

```python
"""The bullpen dashboard shell: sidebar + selector row + tab frame."""
from __future__ import annotations

from datetime import date

from dash import dcc, html
from flask_login import current_user

from app.data import bullpen as B
from app.data import roster_media
from app.dashboards import date_range as dr
from app.dashboards.shell import BANNER, CRIMSON, PHOTO_PLACEHOLDER, header
from app.dashboards.bullpen import selectors

WINDOW_MIN = "2025-09-01"


def _tile(label, value):
    return html.Div([
        html.Div(value, style={"fontSize": "28px", "fontWeight": "bold", "color": CRIMSON}),
        html.Div(label, style={"fontSize": "13px", "color": "#555"}),
    ], style={"textAlign": "center", "padding": "6px 10px",
              "backgroundColor": "rgba(255,255,255,0.8)", "borderRadius": "8px"})


def sidebar(pitcher_id, start, end) -> html.Div:
    if pitcher_id is None:
        return html.Div("Select a pitcher.", style={"padding": "12px"})
    name = B.pitcher_name(int(pitcher_id)) or str(pitcher_id)
    summ = B.bullpen_session_summary(int(pitcher_id), start, end)
    media = roster_media.player_media_by_name(name)
    photo = media.get("photo_url") or PHOTO_PLACEHOLDER
    jersey = f"#{media['jersey']} · " if media.get("jersey") else ""
    return html.Div([
        html.Img(src=photo, style={"width": "100%", "borderRadius": "8px",
                                   "border": "4px solid white",
                                   "background": "rgba(255,255,255,0.6)"}),
        html.Div(f"{jersey}{name}",
                 style={"fontSize": "24px", "fontWeight": "bold", "marginTop": "8px"}),
        html.Div([_tile("SESSIONS", summ["sessions"]), _tile("PITCHES", summ["pitches"]),
                  _tile("PITCH TYPES", summ["pitch_types"]), _tile("LAST", summ["last_date"])],
                 style={"display": "grid", "gridTemplateColumns": "1fr 1fr",
                        "gap": "6px", "marginTop": "10px"}),
        html.Div("Stats reflect the selected date range.",
                 style={"fontSize": "12px", "color": "#555", "marginTop": "6px"}),
    ], style={"padding": "8px"})


def serve_layout() -> html.Div:
    if not current_user.is_authenticated:
        return html.Div("Please log in.")
    is_coach = bool(getattr(current_user, "is_coach", False))
    own = getattr(current_user, "trackman_id", None)
    pitchers = selectors.pitcher_options(is_coach=is_coach, own_trackman_id=own)
    default_pitcher = selectors.resolve_pitcher(
        pitchers[0]["value"] if pitchers else None, is_coach=is_coach, own_trackman_id=own)

    start_d, end_d = WINDOW_MIN, date.today().isoformat()
    sess = B.session_options(default_pitcher, start_d, end_d) if default_pitcher is not None else None
    session_opts = selectors.session_dropdown_options(sess)
    default_session = session_opts[0]["value"] if session_opts else None

    selector_row = html.Div([
        html.Div([
            html.Label("Pitcher", style={"color": "white", "fontWeight": "bold"}),
            dcc.Dropdown(id="bp-pitcher-dd", options=pitchers, value=default_pitcher,
                         clearable=False, disabled=not is_coach, style={"minWidth": "220px"}),
        ]),
        html.Div([
            html.Label("Date range", style={"color": "white", "fontWeight": "bold"}),
            dr.date_picker("bp", start_d, end_d, min_date=WINDOW_MIN, max_date=end_d),
        ]),
        html.Div([
            html.Label("Session (detail)", style={"color": "white", "fontWeight": "bold"}),
            dcc.Dropdown(id="bp-session-dd", options=session_opts, value=default_session,
                         clearable=False, style={"minWidth": "220px"}),
        ]),
    ], style={"display": "flex", "gap": "16px", "alignItems": "flex-end",
              "padding": "12px 16px", "backgroundColor": BANNER})

    tabs = dcc.Tabs(id="bp-tabs", value="session", children=[
        dcc.Tab(label="Session Detail", value="session"),
        dcc.Tab(label="Development Trends", value="trends"),
    ])

    return html.Div([
        dcc.Store(id="bp-selection", data={"pitcher_id": default_pitcher,
                                           "session_date": default_session,
                                           "start": start_d, "end": end_d}),
        header(back_href="/pitching", back_label="← Pitching"),
        html.Div([
            html.Div(id="bp-sidebar", children=sidebar(default_pitcher, start_d, end_d),
                     style={"width": "240px", "flexShrink": "0"}),
            html.Div([selector_row, tabs,
                      html.Div(id="bp-tab-content", style={"padding": "8px 16px"})],
                     style={"flexGrow": "1"}),
        ], style={"display": "flex", "gap": "16px", "padding": "16px",
                  "alignItems": "flex-start"}),
    ])
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_bullpen_dash.py -k "sidebar or serve_layout" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/bullpen/layout.py tests/test_bullpen_dash.py
git commit -m "feat(bullpen-dash): layout shell, sidebar, selector row, tabs"
```

---

### Task 7: Callbacks

**Files:**
- Create: `app/dashboards/bullpen/callbacks.py`
- Test: `tests/test_bullpen_dash.py` (append)

**Interfaces:**
- Consumes: `layout`, `selectors`, `B.session_options`, tabs `session_detail`/`trends`, `date_range`, `charts` (via trends).
- Produces: `register_callbacks(dash_app) -> None`.
- Component ids (from Task 6 + tabs): `bp-pitcher-dd`, `bp-daterange` (start_date/end_date), `bp-session-dd`, `bp-selection`, `bp-sidebar`, `bp-tabs`, `bp-tab-content`, `bp-trend-metric`, `bp-trend-active`, `bp-trend-data`, `bp-trend-body`, chips `{"type":"bp-trend-chip","index":pt}`.

- [ ] **Step 1: Write failing test** — append to `tests/test_bullpen_dash.py`:

```python
def test_register_callbacks_adds_callbacks(server):
    from dash import Dash
    from app.dashboards.bullpen import layout, callbacks
    app = Dash(__name__, server=server, url_base_pathname="/dash/bptest/",
               suppress_callback_exceptions=True)
    app.layout = layout.serve_layout
    before = len(app.callback_map)
    callbacks.register_callbacks(app)
    assert len(app.callback_map) > before
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_bullpen_dash.py -k register_callbacks -q`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement** — create `app/dashboards/bullpen/callbacks.py`:

```python
"""Dash callbacks: selection -> stores -> reactive sidebar/session-dd/tab/trends."""
from __future__ import annotations

import pandas as pd
from dash import ALL, Input, Output, State, ctx, html
from flask_login import current_user

from app.data import bullpen as B
from app.dashboards.bullpen import layout, selectors
from app.dashboards.bullpen.tabs import session_detail, trends
from app.reports.plots import color_for


def _resolve(pitcher_id):
    is_coach = bool(getattr(current_user, "is_coach", False))
    own = getattr(current_user, "trackman_id", None)
    return selectors.resolve_pitcher(pitcher_id, is_coach=is_coach, own_trackman_id=own)


def register_callbacks(dash_app) -> None:

    # Pitcher or date-range change -> refresh session dropdown (default most-recent).
    @dash_app.callback(
        Output("bp-session-dd", "options"), Output("bp-session-dd", "value"),
        Input("bp-pitcher-dd", "value"),
        Input("bp-daterange", "start_date"), Input("bp-daterange", "end_date"),
        prevent_initial_call=True,
    )
    def _on_pitcher_or_range(pitcher_id, start, end):
        pid = _resolve(pitcher_id)
        if pid is None or not start or not end:
            return [], None
        opts = selectors.session_dropdown_options(B.session_options(pid, start, end))
        return opts, (opts[0]["value"] if opts else None)

    # Any selection change -> selection store + sidebar.
    @dash_app.callback(
        Output("bp-selection", "data"), Output("bp-sidebar", "children"),
        Input("bp-pitcher-dd", "value"), Input("bp-session-dd", "value"),
        State("bp-daterange", "start_date"), State("bp-daterange", "end_date"),
    )
    def _on_selection(pitcher_id, session_date, start, end):
        pid = _resolve(pitcher_id)
        data = {"pitcher_id": pid, "session_date": session_date, "start": start, "end": end}
        return data, layout.sidebar(pid, start, end)

    # Tab or selection change -> render the active tab.
    @dash_app.callback(
        Output("bp-tab-content", "children"),
        Input("bp-tabs", "value"), Input("bp-selection", "data"),
    )
    def _render_tab(tab, sel):
        sel = sel or {}
        pid = sel.get("pitcher_id")
        if tab == "trends":
            return trends.render(pid, sel.get("start"), sel.get("end"))
        return session_detail.render(pid, sel.get("session_date"))

    # Trend chip click -> toggle the pitch type in the active-set store.
    @dash_app.callback(
        Output("bp-trend-active", "data"),
        Input({"type": "bp-trend-chip", "index": ALL}, "n_clicks"),
        State("bp-trend-active", "data"), prevent_initial_call=True,
    )
    def _trend_toggle(_clicks, active):
        tid = ctx.triggered_id
        if not tid:
            return active
        pt = tid["index"]
        active = list(active or [])
        return [p for p in active if p != pt] if pt in active else active + [pt]

    # Metric / active-set change -> re-render the trend body from the stored df.
    @dash_app.callback(
        Output("bp-trend-body", "children"),
        Input("bp-trend-metric", "value"), Input("bp-trend-active", "data"),
        State("bp-trend-data", "data"), prevent_initial_call=True,
    )
    def _trend_body(metric, active, data_json):
        if not data_json:
            return html.Div("No bullpen data in this date range.",
                            style={"padding": "12px", "color": "#555"})
        import io
        df = pd.read_json(io.StringIO(data_json), orient="split")
        return trends.body(df, metric or "velocity", active or [])

    # Dim deselected chips.
    @dash_app.callback(
        Output({"type": "bp-trend-chip", "index": ALL}, "style"),
        Input("bp-trend-active", "data"),
        State({"type": "bp-trend-chip", "index": ALL}, "id"),
    )
    def _trend_chip_styles(active, ids):
        active = set(active or [])
        out = []
        for i in ids:
            pt = i["index"]; col = color_for(pt); on = pt in active
            out.append({"border": f"2px solid {col}",
                        "background": col if on else "#fff",
                        "color": "#fff" if on else col,
                        "borderRadius": "14px", "padding": "3px 12px",
                        "margin": "0 6px 6px 0", "cursor": "pointer",
                        "opacity": "1" if on else ".55",
                        "fontFamily": "Teko, sans-serif", "fontSize": "15px"})
        return out
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_bullpen_dash.py -k register_callbacks -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/bullpen/callbacks.py tests/test_bullpen_dash.py
git commit -m "feat(bullpen-dash): reactive callbacks (selection, tabs, trend filters)"
```

---

### Task 8: Mount the app + Pitching-hub card (integration)

**Files:**
- Create: `app/dashboards/bullpen/index.py`
- Modify: `app/dashboards/__init__.py` (register build fn)
- Modify: `app/templates/main/pitching_hub.html` (add card)
- Test: `tests/test_bullpen_dash.py` (append); `tests/test_home.py` or hub test (append card assertion)

**Interfaces:**
- Consumes: `layout.serve_layout`, `callbacks.register_callbacks`, shell `index_string`.
- Produces: `build_bullpen_dash(server) -> Dash` mounted at `/dash/bullpen/`.

- [ ] **Step 1: Write failing tests** — append to `tests/test_bullpen_dash.py`:

```python
def test_build_bullpen_dash_mounts(server):
    rules = {r.rule for r in server.url_map.iter_rules()}
    assert any(r.startswith("/dash/bullpen/") for r in rules)


def test_pitching_hub_has_bullpen_dashboard_card(server):
    server.config["WTF_CSRF_ENABLED"] = False
    from app.auth.models import User
    from app.extensions import db
    with server.app_context():
        u = User(email="c@lmu.edu", name="Coach", role="coach"); u.set_password("x")
        db.session.add(u); db.session.commit()
    client = server.test_client()
    with client.session_transaction() as s:
        pass
    client.post("/login", data={"email": "c@lmu.edu", "password": "x"})
    html_body = client.get("/pitching").get_data(as_text=True)
    assert "Bullpen Dashboard" in html_body and "/dash/bullpen/" in html_body
```

> If `User(...)`/login wiring differs from the above, mirror the exact pattern already used in `tests/test_home.py` for an authenticated coach GET of `/pitching`. The assertion that matters: the rendered `/pitching` contains `Bullpen Dashboard` and `/dash/bullpen/`.

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_bullpen_dash.py -k "mounts or hub_has_bullpen" -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Create `app/dashboards/bullpen/index.py`:

```python
"""Bullpen Dash app factory, mounted at /dash/bullpen/."""
from __future__ import annotations

from dash import Dash

from app.dashboards.shell import index_string
from app.dashboards.bullpen import callbacks, layout


def build_bullpen_dash(server) -> Dash:
    dash_app = Dash(__name__, server=server, url_base_pathname="/dash/bullpen/",
                    suppress_callback_exceptions=True)
    dash_app.index_string = index_string()
    dash_app.layout = layout.serve_layout
    callbacks.register_callbacks(dash_app)
    return dash_app
```

Modify `app/dashboards/__init__.py` `register_dashboards` — add after the practice build:

```python
    from app.dashboards.bullpen.index import build_bullpen_dash
    build_bullpen_dash(server)
```

Modify `app/templates/main/pitching_hub.html` — add a 4th card to the `card_grid` list:

```jinja
  {"title": "Bullpen Dashboard", "desc": "Explore bullpen sessions and track pitch development over time.", "href": "/dash/bullpen/"}
```

(Add a trailing comma to the current last card so the list stays valid.)

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_bullpen_dash.py -q`
Expected: PASS (all bullpen-dash tests).

- [ ] **Step 5: Full suite + commit**

Run: `python -m pytest -q`
Expected: PASS (no regressions).

```bash
git add app/dashboards/bullpen/index.py app/dashboards/__init__.py app/templates/main/pitching_hub.html tests/test_bullpen_dash.py
git commit -m "feat(bullpen-dash): mount /dash/bullpen/ + Pitching-hub card"
```

---

## Self-Review

**Spec coverage:**
- §3 placement/entry point → Task 8 (hub card + mount). ✅
- §4 package structure → Tasks 2–8 create every file. ✅
- §5 scoping (coach/player) → Task 2 selectors + Task 7 `_resolve`. ✅
- §6 selectors/sidebar/date-window → Task 6 (WINDOW_MIN, bounded picker, tiles). ✅
- §7 Tab A Session Detail → Task 4; Tab B Trends (metric selector + chips + proxy) → Task 5. ✅
- §8 data helpers → Task 1. ✅
- §9 Plotly charts via `color_for` → Task 3. ✅
- §10 tests → every task adds tests; `test_bullpen_dash.py` mirrors `test_pitching_dash.py`. ✅
- Backfill fallout (stale `test_max_date_is_stale_2025`) → fixed in Task 1. ✅

**Placeholder scan:** No TBD/TODO; all steps carry real code. The one soft spot (Task 8's login test wiring) explicitly points to the existing `test_home.py` pattern with a concrete fallback assertion.

**Type consistency:** `session_options`/`bullpen_session_summary`/`trend_by_session`/`pitcher_name` signatures identical across Tasks 1/4/5/6/7. Component ids consistent between Task 6 (layout), Task 5 (trends store/body ids), and Task 7 (callback ids): `bp-pitcher-dd`, `bp-daterange`, `bp-session-dd`, `bp-selection`, `bp-sidebar`, `bp-tabs`, `bp-tab-content`, `bp-trend-metric`, `bp-trend-active`, `bp-trend-data`, `bp-trend-body`, `bp-trend-chip`. `df_table(color_col=...)` used with `"pitch"` (summary) and `"tagged_pitch_type"` (per-pitch) — both real columns. `trend_fig(df, metric, active_types)` signature matches call sites in Task 5 body.

**Notes for the executor:** All data tests hit the live analytics DB (BULLPEN now current through 2026-05-13). Charts/selectors/tabs use synthetic frames and run offline. Run non-ASCII-printing commands with `PYTHONIOENCODING=utf-8`.
