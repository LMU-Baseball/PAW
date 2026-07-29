# Player-Card Sidebar Stats Implementation Plan (SP2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Pitching sidebar tiles become Appearances / IP / K% / Walk% / Barrel%, scoped to the selected date range.

**Architecture:** New `P.range_summary(pid, start, end)` loads the date-bounded pitch df (reusing `range_pitches_for`) and computes the five metrics via existing transforms plus two new helpers (`format_ip`, `barrel_pct_ev`). `layout.sidebar` gains `start`/`end` args; `_on_selection` (which already has them) passes them through.

**Tech Stack:** Flask + Dash, pandas, pytest.

## Global Constraints

- Barrel% here uses the coaches' simplified **95+ mph EV** definition (drops the LineDrive/FlyBall qualifier the report's `P.barrel_pct` keeps) — implement as a SEPARATE `barrel_pct_ev`; do NOT modify `barrel_pct`.
- Keep `P.season_summary` (may be referenced/tested elsewhere) — add alongside, don't replace.
- Run: `python -m pytest -q`. Commit after each task. No `git stash/reset/checkout/clean`.

---

### Task 1: Data helpers — `format_ip`, `barrel_pct_ev`, `range_summary`

**Files:**
- Modify: `app/data/pitching.py`
- Test: `tests/test_pitching.py`

**Interfaces:**
- Produces:
  - `format_ip(outs: int) -> str` (baseball innings: `outs//3 . outs%3`).
  - `barrel_pct_ev(df) -> tuple[float, int]` (EV≥95 InPlay / InPlay).
  - `range_summary(pitcher_id, start=None, end=None) -> dict` with keys
    `appearances, ip, k_pct, bb_pct, barrel_pct` (all display strings).

- [ ] **Step 1: Write failing tests**

Append to `tests/test_pitching.py`:
```python
def test_format_ip():
    from app.data import pitching as P
    assert P.format_ip(0) == "0.0"
    assert P.format_ip(1) == "0.1"
    assert P.format_ip(3) == "1.0"
    assert P.format_ip(8) == "2.2"


def test_barrel_pct_ev_drops_la_qualifier():
    import pandas as pd
    from app.data import pitching as P
    # 3 balls in play: two at 95+ (one GroundBall — would be excluded by the
    # report's LD/FB def but INCLUDED here), one under 95.
    df = pd.DataFrame({
        "pitch_call": ["InPlay", "InPlay", "InPlay", "StrikeCalled"],
        "exit_speed": [98.0, 96.0, 80.0, None],
        "tagged_hit_type": ["GroundBall", "LineDrive", "FlyBall", None]})
    pct, n = P.barrel_pct_ev(df)
    assert n == 2 and pct == round(100 * 2 / 3, 1)


def test_range_summary_shape_and_date_bounding(real_pitcher):
    from app.data import pitching as P
    g = P.games_for_pitcher(real_pitcher)
    start, end = str(g["game_date"].min()), str(g["game_date"].max())
    full = P.range_summary(real_pitcher, start, end)
    assert set(full) == {"appearances", "ip", "k_pct", "bb_pct", "barrel_pct"}
    assert full["k_pct"].endswith("%") and full["ip"]  # display strings
    # a single-day range has <= the full appearances count
    one = P.range_summary(real_pitcher, start, start)
    assert int(one["appearances"]) <= int(full["appearances"])
```
(`real_pitcher` fixture already exists in this test module.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pitching.py::test_format_ip tests/test_pitching.py::test_barrel_pct_ev_drops_la_qualifier -q`
Expected: FAIL (helpers not defined).

- [ ] **Step 3: Implement the helpers in `app/data/pitching.py`**

Add near the other metric primitives (after `barrel_pct`):
```python
def format_ip(outs: int) -> str:
    """Baseball innings-pitched from total outs: whole innings . trailing outs."""
    outs = int(outs or 0)
    return f"{outs // 3}.{outs % 3}"


def barrel_pct_ev(df: pd.DataFrame) -> tuple[float, int]:
    """Barrel% — coaches' SIMPLIFIED def: balls-in-play with exit_speed >= 95,
    over balls-in-play. Intentionally DROPS the LineDrive/FlyBall qualifier that
    `barrel_pct` keeps (the two therefore differ by design). PROVISIONAL."""
    bip = df[df["pitch_call"] == "InPlay"]
    barrels = int((bip["exit_speed"] >= 95).sum())
    return _pct(barrels, len(bip)), barrels
```
Add near `season_summary`:
```python
def range_summary(pitcher_id, start=None, end=None) -> dict:
    """Date-range-scoped sidebar tiles: Appearances / IP / K% / Walk% / Barrel%.
    Loads the date-bounded pitch df (whole-career when start/end missing) and
    computes via the shared transforms. PROVISIONAL metric defs."""
    pid = int(pitcher_id)
    if start and end:
        df = range_pitches_for(pid, start, end)
    else:
        ids = _sibling_pitcher_ids(pid)
        marks = ", ".join(f":id{i}" for i in range(len(ids)))
        params = {f"id{i}": v for i, v in enumerate(ids)}
        df = query_df(
            f"SELECT * FROM fact_tm_game_pitch WHERE pitcher_id IN ({marks})",
            params)
    if df is None or df.empty:
        return {"appearances": "—", "ip": "—", "k_pct": "—",
                "bb_pct": "—", "barrel_pct": "—"}
    return {
        "appearances": str(int(df["game_id"].nunique())),
        "ip": format_ip(int(df["outs_on_play"].sum())),
        "k_pct": f"{k_pct(df)[0]:.1f}%",
        "bb_pct": f"{bb_pct(df)[0]:.1f}%",
        "barrel_pct": f"{barrel_pct_ev(df)[0]:.1f}%",
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_pitching.py::test_format_ip tests/test_pitching.py::test_barrel_pct_ev_drops_la_qualifier tests/test_pitching.py::test_range_summary_shape_and_date_bounding -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/data/pitching.py tests/test_pitching.py
git commit -m "feat(pitching): range_summary + format_ip + barrel_pct_ev (95+ EV) helpers"
```

---

### Task 2: Wire the five date-range tiles into the sidebar

**Files:**
- Modify: `app/dashboards/pitching/layout.py` (`sidebar` signature + tiles + footnote; `serve_layout` initial call; keep `_tile`)
- Modify: `app/dashboards/pitching/callbacks.py` (`_on_selection` passes `start`/`end`)
- Test: `tests/test_pitching_dash.py`

**Interfaces:**
- Consumes: `P.range_summary(pid, start, end)`.
- Produces: `layout.sidebar(pitcher_id, start=None, end=None)`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_pitching_dash.py`:
```python
def test_sidebar_shows_five_range_tiles(real_pitcher):
    from app.dashboards.pitching import layout
    from app.data import pitching as P
    g = P.games_for_pitcher(real_pitcher)
    start, end = str(g["game_date"].min()), str(g["game_date"].max())
    s = str(layout.sidebar(real_pitcher, start, end))
    for label in ("APP", "IP", "K%", "BB%", "Barrel%"):
        assert label in s
```
(`real_pitcher` fixture exists in this module.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pitching_dash.py::test_sidebar_shows_five_range_tiles -q`
Expected: FAIL (only APP/PITCHES/K/BB today; `sidebar` takes no start/end).

- [ ] **Step 3: Update `sidebar` in layout.py**

Change the signature and the summary + tiles block:
```python
def sidebar(pitcher_id, start=None, end=None) -> html.Div:
    if pitcher_id is None:
        return html.Div("Select a pitcher.", style={"padding": "12px"})
    prof = P.pitcher_profile(int(pitcher_id))
    summ = P.range_summary(int(pitcher_id), start, end)
    photo = prof["photo"] or PHOTO_PLACEHOLDER
    jersey = f"#{prof['jersey']} · " if prof["jersey"] else ""
    meta = " · ".join([x for x in (prof["class_year"], prof["position"],
                                   f"Throws {prof['throws']}" if prof["throws"] else "") if x])
    return html.Div([
        html.Img(src=photo, style={"width": "100%", "borderRadius": "8px",
                                   "border": "4px solid white",
                                   "background": "rgba(255,255,255,0.6)"}),
        html.Div(f"{jersey}{prof['name'] or '—'}",
                 style={"fontSize": "26px", "fontWeight": "bold", "marginTop": "8px"}),
        html.Div(meta, style={"fontSize": "16px", "color": "#555"}),
        html.Div([_tile("APP", summ["appearances"]), _tile("IP", summ["ip"]),
                  _tile("K%", summ["k_pct"]), _tile("BB%", summ["bb_pct"]),
                  _tile("Barrel%", summ["barrel_pct"])],
                 style={"display": "grid", "gridTemplateColumns": "1fr 1fr",
                        "gap": "6px", "marginTop": "10px"}),
        html.Div("Stats reflect the selected date range · Barrel = 95+ mph EV (provisional).",
                 style={"fontSize": "12px", "color": "#555", "marginTop": "4px"}),
    ], style={"padding": "8px"})
```

- [ ] **Step 4: Pass start/end at the two call sites**

In `layout.serve_layout`, the initial sidebar child:
```python
            html.Div(id="sidebar", children=sidebar(default_pitcher, start_d, end_d),
                     style={"width": "240px", "flexShrink": "0"}),
```
In `callbacks._on_selection`, the return:
```python
        return ({"pitcher_id": pid, "game_id": game_id, "start": start, "end": end},
                layout.sidebar(pid, start, end), sb)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python -m pytest tests/test_pitching_dash.py::test_sidebar_shows_five_range_tiles -q`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS (baseline 347 + new tests).

- [ ] **Step 7: Commit**

```bash
git add app/dashboards/pitching/layout.py app/dashboards/pitching/callbacks.py tests/test_pitching_dash.py
git commit -m "feat(pitching): date-range sidebar tiles (APP/IP/K%/BB%/Barrel%)"
```

---

## Self-Review

**Spec coverage:** tiles APP/IP/K%/BB%/Barrel% → Task 2. Date-range-aware → `range_summary` + `_on_selection` passthrough (Tasks 1–2). Barrel = 95+ EV simplified def → `barrel_pct_ev` (Task 1). IP baseball format → `format_ip` (Task 1).

**Placeholder scan:** none.

**Type consistency:** `range_summary` returns the exact 5 keys the sidebar reads (`appearances/ip/k_pct/bb_pct/barrel_pct`). `sidebar(pid, start, end)` signature matches both call sites. `barrel_pct` left untouched (constraint honored).

**Live gate:** verify on `python run.py` that changing the date range updates the tiles (combine with the SP1 live click-through).
