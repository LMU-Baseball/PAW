# Catching Dashboard Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three catching-dashboard enhancements — fixed-aspect (proportionate) strike-zone charts, a call-type chip filter on Overall Framing (scatter only), and a Caught-Stealing trend chart (CS% + avg pop over game dates) that follows the date-range selection.

**Architecture:** In-place edits to `app/dashboards/catching/{charts.py,callbacks.py,tabs/framing.py,tabs/caught_stealing.py}` and `app/data/catching.py`. Reuses the pitching chip pattern (`chip_row` + toggle/style callbacks) and the shipped date-range wiring from sub-project B.

**Tech Stack:** Python, Flask, Dash, Plotly, pandas; pytest.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-07-23-catching-enhancements-design.md`. Base branch `feat/catching-enhancements` (off `feat/dashboards-date-range`).
- **Chips filter the scatter ONLY** — the Framing Summary table stays computed from the full dropdown-filtered df.
- **CS trend follows the selection** — plots the games in the loaded df; single-game (≤1 distinct `game_date`) shows a "widen the range" note.
- **No DB in tabs/charts** — pure `df → components`/`figure`. DB only in `app/data/catching.py` + callbacks.
- **Brand:** Teko font, crimson `#9A0021`, blue `#0076A5`; `CALLTYPE_COLORS` from `charts.py` (Stolen=`#000000`, Lost=`#9A0021`, Correct=`#cccccc`). Transparent `paper_bgcolor`, near-white `plot_bgcolor`.
- **Warehouse:** `fact_tm_game_pitch` joined to `dim_tm_game` for `game_date`.
- **Tests:** `python -m pytest -q`; Windows headless prefix `PYTHONIOENCODING=utf-8`. Live-DB tests follow the existing unguarded convention.

---

### Task 1: Fixed-aspect strike-zone charts

**Files:**
- Modify: `app/dashboards/catching/charts.py` (`framing_scatter`, `framing_facets`)
- Test: `tests/test_catching_dash.py` (append)

**Interfaces:**
- Produces: `framing_scatter` / `framing_facets` figures whose y-axis is aspect-locked to x (`scaleanchor="x", scaleratio=1`), so the zone is proportionate at any width.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_catching_dash.py`:

```python
def test_framing_scatter_is_aspect_locked():
    from app.dashboards.catching import charts
    fig = charts.framing_scatter(_sample_df())
    assert fig.layout.yaxis.scaleanchor == "x"
    assert fig.layout.yaxis.scaleratio == 1


def test_framing_facets_is_aspect_locked():
    from app.dashboards.catching import charts
    fig = charts.framing_facets(_sample_df(), by="batter_side", title="Batter Side")
    # first facet's y-axis is locked to its x-axis
    assert fig.layout.yaxis.scaleanchor == "x"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_catching_dash.py -k aspect_locked -v`
Expected: FAIL (`scaleanchor` is None).

- [ ] **Step 3: Implement in `app/dashboards/catching/charts.py`**

In `framing_scatter`, after the existing `_base_axes(fig)` call (and before/after `update_layout`), add:

```python
    fig.update_yaxes(scaleanchor="x", scaleratio=1)
```

In `framing_facets`, inside the `for i, v in enumerate(vals, start=1):` loop, after `_base_axes(fig, row=1, col=i)`, add the per-cell aspect lock (each cell's y anchors to its own x — `x`, `x2`, `x3`, …):

```python
        fig.update_yaxes(scaleanchor=("x" if i == 1 else f"x{i}"),
                         scaleratio=1, row=1, col=i)
```

And in the `if not vals:` fallback branch (single empty cell), after `_base_axes(fig, row=1, col=1)`:

```python
        fig.update_yaxes(scaleanchor="x", scaleratio=1, row=1, col=1)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_catching_dash.py -k aspect_locked -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/catching/charts.py tests/test_catching_dash.py
git commit -m "feat(catching): aspect-lock framing scatter + facets (proportionate zone)"
```

---

### Task 2: `game_date` on loaders + caught-stealing trend transform

**Files:**
- Modify: `app/data/catching.py` (`game_pitches_for`, `range_pitches_for`; add `caught_stealing_trend`)
- Test: `tests/test_catching.py` (append)

**Interfaces:**
- Consumes: `caught_stealing_events` (existing).
- Produces:
  - `game_pitches_for` / `range_pitches_for` dfs now include a `game_date` column.
  - `caught_stealing_trend(df) -> pd.DataFrame[game_date, attempts, caught, cs_pct, avg_pop]` (per-game-date; dates with ≥1 attempt; sorted).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_catching.py`:

```python
def test_caught_stealing_trend():
    import pandas as pd
    from app.data import catching as C
    df = pd.DataFrame([
        {"play_result": "CaughtStealing", "pop_time": 1.9, "exchange_time": 0.7,
         "throw_speed": 80.0, "game_date": "2026-04-01"},
        {"play_result": "StolenBase", "pop_time": 2.1, "exchange_time": 0.75,
         "throw_speed": 78.0, "game_date": "2026-04-01"},
        {"play_result": "StolenBase", "pop_time": None, "exchange_time": None,
         "throw_speed": None, "game_date": "2026-04-08"},
        {"play_result": "Single", "pop_time": None, "exchange_time": None,
         "throw_speed": None, "game_date": "2026-04-08"},
    ])
    t = C.caught_stealing_trend(df)
    assert list(t["game_date"]) == ["2026-04-01", "2026-04-08"]
    assert list(t["attempts"]) == [2, 1]
    assert list(t["caught"]) == [1, 0]
    assert t.iloc[0]["cs_pct"] == 50.0 and t.iloc[1]["cs_pct"] == 0.0
    assert t.iloc[0]["avg_pop"] == 2.0 and t.iloc[1]["avg_pop"] is None


def test_caught_stealing_trend_empty():
    import pandas as pd
    from app.data import catching as C
    assert C.caught_stealing_trend(pd.DataFrame()).empty
    # df with no CS attempts -> empty trend
    only_single = pd.DataFrame([{"play_result": "Single", "game_date": "2026-04-01"}])
    assert C.caught_stealing_trend(only_single).empty


def test_game_pitches_for_has_game_date():
    from app.data import catching as C
    cats = C.wh_lmu_catchers()
    if cats.empty:
        import pytest; pytest.skip("no catchers")
    cid = int(cats.iloc[0]["CatcherId"])
    g = C.games_for_catcher(cid)
    if g.empty:
        import pytest; pytest.skip("no games")
    df = C.game_pitches_for(int(g.iloc[0]["game_id"]), cid)
    assert "game_date" in df.columns
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_catching.py -k "caught_stealing_trend or game_date" -v`
Expected: FAIL (`caught_stealing_trend` missing / `game_date` not in `game_pitches_for`).

- [ ] **Step 3: Implement in `app/data/catching.py`**

Change `game_pitches_for` to join `dim_tm_game` and select `game_date`:

```python
def game_pitches_for(game_id: int, catcher_id: int) -> pd.DataFrame:
    """Pitch-level rows for one catcher in one game (sibling-id union)."""
    ids = _sibling_catcher_ids(catcher_id)
    marks, params = _in_clause(ids)
    params["gid"] = int(game_id)
    return query_df(
        f"""
        SELECT f.*, g.game_date
          FROM fact_tm_game_pitch f
          JOIN dim_tm_game g ON g.game_id = f.game_id
         WHERE f.game_id = :gid AND f.catcher_id IN ({marks})
         ORDER BY f.pitch_no
        """,
        params,
    )
```

Change `range_pitches_for`'s SELECT from `SELECT f.*` to `SELECT f.*, g.game_date` (the `dim_tm_game g` join is already present). Leave the rest as-is.

Add the transform (near the other caught-stealing functions):

```python
def caught_stealing_trend(df: pd.DataFrame) -> pd.DataFrame:
    """Per-game-date caught-stealing trend. PROVISIONAL v1.

    Columns: game_date, attempts, caught, cs_pct, avg_pop. Only dates with >=1
    stolen-base attempt; sorted by date. Sparse by nature (few attempts/season).
    """
    cols = ["game_date", "attempts", "caught", "cs_pct", "avg_pop"]
    ev = caught_stealing_events(df)
    if ev.empty or "game_date" not in ev.columns:
        return pd.DataFrame(columns=cols)
    rows = []
    for d, sub in ev.groupby("game_date"):
        n = len(sub)
        c = int(sub["Caught"].sum())
        pops = sub["pop_time"].dropna()
        rows.append({
            "game_date": d, "attempts": n, "caught": c,
            "cs_pct": round(100.0 * c / n, 1),
            "avg_pop": None if pops.empty else round(float(pops.mean()), 2),
        })
    return pd.DataFrame(rows, columns=cols).sort_values("game_date").reset_index(drop=True)
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_catching.py -k "caught_stealing_trend or game_date" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/data/catching.py tests/test_catching.py
git commit -m "feat(catching-data): game_date on loaders + caught_stealing_trend transform"
```

---

### Task 3: Caught-Stealing trend chart + tab wiring

**Files:**
- Modify: `app/dashboards/catching/charts.py` (add `caught_stealing_trend_fig`)
- Modify: `app/dashboards/catching/tabs/caught_stealing.py` (insert trend + single-game note)
- Test: `tests/test_catching_dash.py` (append)

**Interfaces:**
- Consumes: `C.caught_stealing_trend`, `C.caught_stealing_events`, `C.caught_stealing_summary`.
- Produces: `charts.caught_stealing_trend_fig(trend_df) -> go.Figure`; the Caught Stealing tab shows tiles → trend chart (+ note) → table.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_catching_dash.py`:

```python
def test_caught_stealing_trend_fig_builds():
    import pandas as pd
    from app.dashboards.catching import charts
    empty = charts.caught_stealing_trend_fig(pd.DataFrame(
        columns=["game_date", "attempts", "caught", "cs_pct", "avg_pop"]))
    assert empty is not None
    one = charts.caught_stealing_trend_fig(pd.DataFrame([
        {"game_date": "2026-04-01", "attempts": 2, "caught": 1,
         "cs_pct": 50.0, "avg_pop": 2.0}]))
    assert one is not None
    multi = charts.caught_stealing_trend_fig(pd.DataFrame([
        {"game_date": "2026-04-01", "attempts": 2, "caught": 1, "cs_pct": 50.0, "avg_pop": 2.0},
        {"game_date": "2026-04-08", "attempts": 1, "caught": 0, "cs_pct": 0.0, "avg_pop": None}]))
    assert len(multi.data) >= 1


def _has_graph(component):
    """True if a dcc.Graph appears anywhere in the component tree."""
    from dash import dcc
    if isinstance(component, dcc.Graph):
        return True
    ch = getattr(component, "children", None)
    if ch is None or isinstance(ch, str):
        return False
    kids = ch if isinstance(ch, (list, tuple)) else [ch]
    return any(_has_graph(k) for k in kids)


def test_caught_stealing_tab_has_trend_graph():
    from app.dashboards.catching.tabs import caught_stealing
    assert _has_graph(caught_stealing.render(_sample_df()))
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_catching_dash.py -k "trend_fig or trend_graph" -v`
Expected: FAIL (`caught_stealing_trend_fig` missing / no Graph in tab).

- [ ] **Step 3: Add `caught_stealing_trend_fig` to `app/dashboards/catching/charts.py`**

```python
def caught_stealing_trend_fig(trend_df: pd.DataFrame) -> go.Figure:
    """Dual-axis trend: CS% (crimson, left) + Avg Pop time (blue, right) by game date."""
    fig = go.Figure()
    if trend_df is not None and not trend_df.empty:
        x = trend_df["game_date"].astype(str)
        fig.add_trace(go.Scatter(
            x=x, y=trend_df["cs_pct"], name="CS%", yaxis="y",
            mode="markers+lines", marker=dict(color=CRIMSON, size=10),
            line=dict(color=CRIMSON, width=2),
            hovertext=[f"{a} att · {c} caught" for a, c in
                       zip(trend_df["attempts"], trend_df["caught"])],
            hoverinfo="text+y",
        ))
        fig.add_trace(go.Scatter(
            x=x, y=trend_df["avg_pop"], name="Avg Pop (s)", yaxis="y2",
            mode="markers+lines", marker=dict(color="#0076A5", size=9),
            line=dict(color="#0076A5", width=2, dash="dot"),
        ))
    fig.update_layout(
        title="Caught Stealing Trend",
        xaxis=dict(title="Game"),
        yaxis=dict(title="CS%", range=[0, 100], side="left"),
        yaxis2=dict(title="Avg Pop (s)", overlaying="y", side="right",
                    showgrid=False),
        height=340, margin=dict(l=40, r=40, t=40, b=40),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.85)",
        font=dict(family="Teko, sans-serif"),
        legend=dict(orientation="h", y=1.12),
    )
    return fig
```

`CRIMSON` is already imported in `charts.py` (from `app.dashboards.shell`). Confirm; if not, import it.

- [ ] **Step 4: Wire the trend into `app/dashboards/catching/tabs/caught_stealing.py`**

Add imports at top:

```python
from dash import dcc, html
from app.dashboards.catching import charts, tables
```

(Adjust the existing import line — the module currently imports `tables` and `html`; add `dcc` and `charts`.)

In `render(df)`, build the trend + note and insert it between `tiles` and `table`. Replace the final `return` with:

```python
    trend = C.caught_stealing_trend(df)
    n_games = df["game_date"].nunique() if ("game_date" in df.columns and not df.empty) else 0
    trend_children = [section("Caught Stealing Trend"),
                      dcc.Graph(figure=charts.caught_stealing_trend_fig(trend))]
    if n_games <= 1:
        trend_children.append(html.Div(
            "Select 'All games in range' or widen the date range to see a trend.",
            style={"fontSize": "12px", "color": "#888", "marginTop": "4px"}))

    return html.Div([section("Caught Stealing"), tiles, *trend_children, table])
```

- [ ] **Step 5: Run to verify they pass**

Run: `python -m pytest tests/test_catching_dash.py -k "trend_fig or trend_graph" -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/dashboards/catching/charts.py app/dashboards/catching/tabs/caught_stealing.py tests/test_catching_dash.py
git commit -m "feat(catching): caught-stealing trend chart (CS% + avg pop by game)"
```

---

### Task 4: Call-type chip filter on Overall Framing (scatter only)

**Files:**
- Modify: `app/dashboards/catching/tabs/framing.py` (`call_chip_row`, `body` gains `active_calls`, `render` adds chips)
- Modify: `app/dashboards/catching/callbacks.py` (chip toggle + style callbacks; `call-active` Input on `_framing_body`)
- Test: `tests/test_catching_dash.py` (append)

**Interfaces:**
- Consumes: `charts.CALLTYPE_COLORS`, `C.add_framing_cols`, `C.apply_framing_filters`, `C.framing_table`, `charts.framing_scatter`, `tables.df_table`.
- Produces: chips with ids `{"type":"call-chip","index":<call>}` + `dcc.Store(id="call-active")`; `body(df, *, bat_side, pitcher_throws, pitch_speed, zone, active_calls=None)` — scatter filtered to `active_calls`, table from all calls.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_catching_dash.py`:

```python
def test_framing_render_has_call_chips():
    from app.dashboards.catching.tabs import framing
    comp = framing.render(_sample_df())
    ids = _collect_ids(comp)  # helper already in this test file
    assert "call-active" in ids


def test_framing_body_call_filter_scatter_only():
    from app.dashboards.catching.tabs import framing
    from app.data import catching as C
    df = _sample_df()
    # Full body vs body filtered to a single call type
    full = framing.body(df, bat_side="All", pitcher_throws="All",
                        pitch_speed="All", zone="All")
    filtered = framing.body(df, bat_side="All", pitcher_throws="All",
                            pitch_speed="All", zone="All",
                            active_calls=["Stolen Strike"])
    # The summary table (fr-summary) is identical regardless of active_calls
    # (table uses all calls). Locate the DataTable data in each tree.
    def find_table(c):
        from dash import dash_table
        out = []
        def walk(x):
            if isinstance(x, dash_table.DataTable):
                out.append(x)
            ch = getattr(x, "children", None)
            if ch and not isinstance(ch, str):
                for k in (ch if isinstance(ch, (list, tuple)) else [ch]):
                    walk(k)
        walk(c)
        return out
    assert find_table(full)[0].data == find_table(filtered)[0].data
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_catching_dash.py -k "call_chips or call_filter" -v`
Expected: FAIL (`call-active` not present / `active_calls` not accepted).

- [ ] **Step 3: Edit `app/dashboards/catching/tabs/framing.py`**

Add imports/uses of `charts.CALLTYPE_COLORS`. Add the chip row helper:

```python
from app.dashboards.catching import charts, tables

_CALL_ORDER = ["Stolen Strike", "Lost Strike", "Correct Call"]


def call_chip_row() -> html.Div:
    """Clickable chip per call type (all active by default); filters the scatter."""
    chips = [html.Button(
        ct, id={"type": "call-chip", "index": ct}, n_clicks=0,
        style={"border": f"2px solid {charts.CALLTYPE_COLORS[ct]}",
               "background": charts.CALLTYPE_COLORS[ct], "color": "#fff",
               "borderRadius": "14px", "padding": "3px 12px",
               "margin": "0 6px 6px 0", "cursor": "pointer",
               "fontFamily": "Teko, sans-serif", "fontSize": "15px"})
        for ct in _CALL_ORDER]
    return html.Div([dcc.Store(id="call-active", data=list(_CALL_ORDER)),
                     html.Div(chips)], style={"margin": "6px 0"})
```

Change `body` to filter the scatter by `active_calls` (table unchanged):

```python
def body(df, *, bat_side="All", pitcher_throws="All", pitch_speed="All",
         zone="All", active_calls=None) -> html.Div:
    if df.empty:
        return html.Div("No pitch data.")
    f = C.add_framing_cols(df)
    f = C.apply_framing_filters(f, bat_side=bat_side, pitcher_throws=pitcher_throws,
                                pitch_speed=pitch_speed, zone=zone)
    summ = C.framing_table(f)
    table_df = pd.DataFrame([{_TABLE_LABELS[k]: _fmt(k, summ[k]) for k in _TABLE_LABELS}])
    scatter_df = f if active_calls is None else f[f["CallType"].isin(active_calls)]
    return html.Div([
        dcc.Graph(figure=charts.framing_scatter(scatter_df)),
        section("Framing Summary"),
        tables.df_table(table_df, id_="fr-summary"),
    ])
```

In `render(df)`, add the chip row into the filter area (e.g. directly after the dropdown filter row, before `fr-body`):

```python
        call_chip_row(),
```

(Place it as a child in the returned `html.Div` list, between the dropdown-filters Div and the `html.Div(id="fr-body", ...)`.)

- [ ] **Step 4: Edit `app/dashboards/catching/callbacks.py`**

Ensure `ALL`, `ctx` are imported from dash (`from dash import ALL, Input, Output, State, ctx, html`). Add `from app.dashboards.catching import charts` if needed for colors (the style callback uses `charts.CALLTYPE_COLORS`).

Add `Input("call-active", "data")` to `_framing_body` and pass it through:

```python
    @dash_app.callback(
        Output("fr-body", "children"),
        Input("fr-bat", "value"), Input("fr-throws", "value"),
        Input("fr-speed", "value"), Input("fr-zone", "value"),
        Input("call-active", "data"),
        State("game-data", "data"),
    )
    def _framing_body(bat, throws, speed, zone, active_calls, data_json):
        df = _read_game_df(data_json)
        if df.empty:
            return html.Div("No pitch data.")
        return framing.body(df, bat_side=bat or "All", pitcher_throws=throws or "All",
                            pitch_speed=speed or "All", zone=zone or "All",
                            active_calls=active_calls)
```

Add the chip toggle + style callbacks (mirror pitching `_lm_toggle`/`_lm_chip_styles`):

```python
    @dash_app.callback(
        Output("call-active", "data"),
        Input({"type": "call-chip", "index": ALL}, "n_clicks"),
        State("call-active", "data"),
        prevent_initial_call=True,
    )
    def _call_toggle(_clicks, active):
        tid = ctx.triggered_id
        if not tid:
            return active
        ct = tid["index"]
        active = list(active or [])
        return [c for c in active if c != ct] if ct in active else active + [ct]

    @dash_app.callback(
        Output({"type": "call-chip", "index": ALL}, "style"),
        Input("call-active", "data"),
        State({"type": "call-chip", "index": ALL}, "id"),
    )
    def _call_chip_styles(active, ids):
        active = set(active or [])
        out = []
        for i in ids:
            ct = i["index"]; col = charts.CALLTYPE_COLORS[ct]; on = ct in active
            out.append({"border": f"2px solid {col}",
                        "background": col if on else "#fff",
                        "color": "#fff" if on else col,
                        "borderRadius": "14px", "padding": "3px 12px",
                        "margin": "0 6px 6px 0", "cursor": "pointer",
                        "opacity": "1" if on else ".55",
                        "fontFamily": "Teko, sans-serif", "fontSize": "15px"})
        return out
```

- [ ] **Step 5: Run tests + full suite**

Run: `python -m pytest tests/test_catching_dash.py -q` then `python -m pytest -q`
Expected: PASS (all).

- [ ] **Step 6: Commit**

```bash
git add app/dashboards/catching/ tests/test_catching_dash.py
git commit -m "feat(catching): call-type chip filter on Overall Framing (scatter only)"
```

---

### Task 5: Live smoke + review prep

**Files:** none (verification only; scratchpad allowed).

- [ ] **Step 1: Live smoke**

Scratchpad script (not committed): in `create_app().app_context()`, pick the first LMU catcher, load a single game and a pooled range (`C.range_pitches_for`), and assert:
- `charts.framing_scatter(df).layout.yaxis.scaleanchor == "x"`,
- `framing.body(df, active_calls=["Stolen Strike"])` renders,
- `caught_stealing.render(pooled)` renders and `C.caught_stealing_trend(pooled)` returns rows (or prints its length),
- `game_pitches_for`/`range_pitches_for` include `game_date`.

Run: `PYTHONIOENCODING=utf-8 python <scratchpad>/smoke_catching_enh.py`
Expected: all succeed; print the trend row count.

- [ ] **Step 2: Update memory + request final review**

Append the outcome to `memory/MEMORY.md` §3h. Then request a whole-branch code review (superpowers:requesting-code-review) for the A branch before it stacks further.

---

## Notes for the implementer

- The chip pattern is copied from `app/dashboards/pitching/tabs/location_movement.py` (`chip_row`) + `callbacks.py` (`_lm_toggle`/`_lm_chip_styles`); keep it consistent.
- `active_calls=None` means "all calls" (initial render before the store is read) — the scatter must show everything in that case.
- The summary table must NOT depend on `active_calls` (scatter-only filter) — the test asserts this.
- Adding `game_date` to the loaders is harmless to the framing/static tabs (they select specific columns); it exists so the caught-stealing trend can group by date.
