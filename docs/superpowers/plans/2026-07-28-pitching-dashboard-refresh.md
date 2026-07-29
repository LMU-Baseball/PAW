# Pitching Dashboard Refresh Implementation Plan (SP1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the coaches' naming conventions across the dashboards, retire the standalone RHH v. LHH tab, and add count/result/handedness filters to Movement Profile + a handedness toggle to Zone Frequency.

**Architecture:** Pure label/text edits for renames (internal tab `value` keys unchanged so callbacks/tests keep working). The RHH/LHH split becomes a handedness toggle filter on Movement Profile. New filters are pure DataFrame masks applied in the existing `-body` callbacks via a testable helper; no new DB queries.

**Tech Stack:** Flask + Dash (Plotly), pandas, pytest. Windows/PowerShell dev host.

## Global Constraints

- Keep internal `dcc.Tab` `value` keys UNCHANGED (`breakdown`/`location`/`outings`/`pitchlevel`/`counts`/`heatmaps`); change only display `label`s.
- Keep Dash component **ids** stable where callbacks already reference them (`hm-side` etc.) — swap widget types without renaming ids.
- Run the full suite with `python -m pytest -q` from the repo root. Single test: `python -m pytest tests/test_pitching_dash.py::test_name -q`.
- Do NOT delete `P.splits_by_batter_side` or `P.fig_location_split` — `splits_by_batter_side` is still unit-tested (`tests/test_pitching.py:102`), and `fig_location_split` is kept for reuse.
- Commit after each task. Never run `git stash/reset/checkout/clean`.
- Renames apply EVERYWHERE the names appear (pitching + hitting + catching hub cards; catching "Pitch Level" tab).

---

### Task 1: Tab + hub-card renames

**Files:**
- Modify: `app/dashboards/pitching/layout.py:105-113` (tab labels)
- Modify: `app/dashboards/catching/layout.py:109` ("Pitch Level" → "Outing Video")
- Modify: `app/templates/main/pitching_hub.html:8`, `app/templates/main/hitting_hub.html:8`, `app/templates/main/catching_hub.html:8` ("Stats Dashboard" → "Player Dashboard")
- Test: `tests/test_pitching_dash.py:202,238,239`, `tests/test_catching_dash.py:434`

**Interfaces:**
- Consumes: nothing new.
- Produces: nothing new (labels only).

- [ ] **Step 1: Update the tab-label assertions to the new labels (make them fail)**

In `tests/test_pitching_dash.py` change:
```python
# line ~202
assert '"pitchlevel"' in src and "Outing Video" in src
# line ~238
assert '"counts"' in src and "Count Performance" in src
# line ~239
assert '"heatmaps"' in src and "Zone Frequency" in src
```
In `tests/test_catching_dash.py` line ~434:
```python
assert '"pitchlevel"' in src and "Outing Video" in src
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_pitching_dash.py::test_pitching_tabs_include_pitch_level tests/test_pitching_dash.py::test_pitching_tabs_include_counts_and_heatmaps tests/test_catching_dash.py -q`
Expected: FAIL (source still has old labels).

- [ ] **Step 3: Rename the pitching tab labels**

In `app/dashboards/pitching/layout.py`, the `dcc.Tabs` children become (values unchanged):
```python
tabs = dcc.Tabs(id="tabs", value="breakdown", children=[
    dcc.Tab(label="Personal Breakdown", value="breakdown"),
    dcc.Tab(label="Movement Profile", value="location"),
    dcc.Tab(label="Outing Overview", value="outings"),
    dcc.Tab(label="Outing Video", value="pitchlevel"),
    dcc.Tab(label="Count Performance", value="counts"),
    dcc.Tab(label="Zone Frequency", value="heatmaps"),
])
```
(Note: the `splits` tab line is REMOVED here — this is also covered by Task 2; removing it now is fine.)

- [ ] **Step 4: Rename the catching "Pitch Level" tab**

In `app/dashboards/catching/layout.py:109`:
```python
dcc.Tab(label="Outing Video", value="pitchlevel"),
```

- [ ] **Step 5: Rename the hub cards**

In each of `pitching_hub.html`, `hitting_hub.html`, `catching_hub.html` line 8, change `"title": "Stats Dashboard"` → `"title": "Player Dashboard"`. Also update the pitching card `desc` to `"Personal breakdown, movement profile, count performance, zone frequency."`.

- [ ] **Step 6: Run the targeted tests to verify they pass**

Run: `python -m pytest tests/test_pitching_dash.py tests/test_catching_dash.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/dashboards/pitching/layout.py app/dashboards/catching/layout.py app/templates/main/pitching_hub.html app/templates/main/hitting_hub.html app/templates/main/catching_hub.html tests/test_pitching_dash.py tests/test_catching_dash.py
git commit -m "feat(dashboards): rename tabs + hub cards per coach naming conventions"
```

---

### Task 2: Delete the RHH v. LHH (splits) tab

**Files:**
- Modify: `app/dashboards/pitching/layout.py` (splits `dcc.Tab` already removed in Task 1 — verify)
- Modify: `app/dashboards/pitching/callbacks.py` (remove `rhh_lhh` import; remove `_render_tab` `splits` branch lines ~134-135; remove `_splits_toggle`/`_splits_body`/`_splits_chip_styles` lines ~196-234)
- Delete: `app/dashboards/pitching/tabs/rhh_lhh.py`
- Test: `tests/test_pitching_dash.py` (new test)

**Interfaces:**
- Consumes: nothing new.
- Produces: `serve_layout` source no longer contains `"splits"`; `callbacks.register_callbacks` still imports/registers cleanly.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_pitching_dash.py`:
```python
def test_splits_tab_removed():
    import inspect
    from app.dashboards.pitching import layout, callbacks
    src = inspect.getsource(layout.serve_layout)
    assert '"splits"' not in src and "RHH v. LHH" not in src
    # callbacks module still imports without rhh_lhh
    assert not hasattr(callbacks, "rhh_lhh")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pitching_dash.py::test_splits_tab_removed -q`
Expected: FAIL (rhh_lhh still imported / splits branch present).

- [ ] **Step 3: Remove the splits import + render branch in callbacks.py**

In `app/dashboards/pitching/callbacks.py`:
- Change the tabs import line to drop `rhh_lhh`:
```python
from app.dashboards.pitching.tabs import (last_outings, location_movement,
                                          pitch_breakdown, counts, heatmaps)
```
- Remove the `_render_tab` branch:
```python
        if tab == "splits":
            return rhh_lhh.render(df)
```
- Delete the three splits callbacks entirely: `_splits_toggle`, `_splits_body`, `_splits_chip_styles` (the `Output("splits-active"...)`, `Output("splits-body"...)`, and `Output({"type": "splits-chip"...}, "style")` callbacks, lines ~196-234).

- [ ] **Step 4: Delete the tab module**

```bash
git rm app/dashboards/pitching/tabs/rhh_lhh.py
```

- [ ] **Step 5: Verify the layout no longer lists splits**

Confirm `app/dashboards/pitching/layout.py` `dcc.Tabs` has no `value="splits"` tab (removed in Task 1).

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_pitching_dash.py tests/test_pitching.py -q`
Expected: PASS (including `test_splits_cover_both_sides_keys`, which tests the retained `P.splits_by_batter_side`).

- [ ] **Step 7: Commit**

```bash
git add app/dashboards/pitching/callbacks.py app/dashboards/pitching/tabs/rhh_lhh.py tests/test_pitching_dash.py
git commit -m "feat(pitching): retire RHH v. LHH tab (folds into Movement Profile handedness toggle)"
```

---

### Task 3: Movement Profile filters (count + result + handedness)

**Files:**
- Modify: `app/dashboards/pitching/tabs/location_movement.py` (add `apply_filters` helper + filter-control row in `render`)
- Modify: `app/dashboards/pitching/callbacks.py` (`_lm_body` reads the new filters)
- Test: `tests/test_pitching_dash.py`

**Interfaces:**
- Consumes: `P.pitch_type`, `P.count_states`, `P.pretty_result` (existing).
- Produces:
  - `location_movement.apply_filters(df, *, pitch_types=None, counts=None, results=None, hand="All") -> pd.DataFrame` (pure).
  - New component ids in `render`: `lm-count` (multi Dropdown), `lm-result` (multi Dropdown), `lm-hand` (RadioItems; values `"All"/"Right"/"Left"`).

- [ ] **Step 1: Write the failing test for the filter helper**

Add to `tests/test_pitching_dash.py`:
```python
def test_movement_profile_apply_filters():
    import pandas as pd
    from app.dashboards.pitching.tabs import location_movement as lm
    df = pd.DataFrame({
        "balls": [0, 1, 0], "strikes": [0, 2, 0],
        "pitch_call": ["StrikeSwinging", "BallCalled", "InPlay"],
        "batter_side": ["Right", "Left", "Right"],
        "tagged_pitch_type": ["Fastball", "Slider", "Fastball"],
        "auto_pitch_type": ["Fastball", "Slider", "Fastball"],
        "rel_speed": [92.0, 84.0, 91.0]})
    # handedness toggle keeps only Right
    assert set(lm.apply_filters(df, hand="Right")["batter_side"]) == {"Right"}
    # result filter (pretty labels) keeps only In Play
    assert list(lm.apply_filters(df, results=["In Play"])["pitch_call"]) == ["InPlay"]
    # count filter keeps only 0-2
    assert list(lm.apply_filters(df, counts=["1-2"])["balls"]) == [1]
    # pitch-type filter
    assert set(lm.apply_filters(df, pitch_types=["Slider"])["tagged_pitch_type"]) == {"Slider"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pitching_dash.py::test_movement_profile_apply_filters -q`
Expected: FAIL (`apply_filters` not defined).

- [ ] **Step 3: Add `apply_filters` + the filter row to location_movement.py**

Add the pure helper:
```python
def apply_filters(df: pd.DataFrame, *, pitch_types=None, counts=None,
                  results=None, hand="All") -> pd.DataFrame:
    """Compose the Movement Profile filters (all AND-ed). Pure."""
    if df is None or df.empty:
        return df
    d = df
    if pitch_types is not None:
        d = d[P.pitch_type(d).isin(pitch_types)]
    if counts is not None:
        cs = (d["balls"].astype("Int64").astype(str) + "-"
              + d["strikes"].astype("Int64").astype(str))
        d = d[cs.isin(counts)]
    if results is not None:
        d = d[d["pitch_call"].map(P.pretty_result).isin(results)]
    if hand and hand != "All":
        d = d[d["batter_side"] == hand]
    return d
```
Add a filter-control row builder and include it in `render` above `#lm-body`:
```python
def _filter_row(df: pd.DataFrame) -> html.Div:
    counts = P.count_states(df)
    results = sorted({P.pretty_result(c) for c in df["pitch_call"].dropna().unique()})
    ctl = {"minWidth": "180px"}
    return html.Div([
        dcc.Dropdown(id="lm-count", multi=True, placeholder="Count(s)",
                     options=[{"label": c, "value": c} for c in counts],
                     value=counts, style=ctl),
        dcc.Dropdown(id="lm-result", multi=True, placeholder="Result(s)",
                     options=[{"label": r, "value": r} for r in results],
                     value=results, style=ctl),
        dcc.RadioItems(id="lm-hand", inline=True, value="All",
                       options=[{"label": "All", "value": "All"},
                                {"label": "vs RHH", "value": "Right"},
                                {"label": "vs LHH", "value": "Left"}],
                       style={"display": "inline-flex", "gap": "10px",
                              "alignItems": "center"}),
    ], style={"display": "flex", "gap": "12px", "flexWrap": "wrap",
              "alignItems": "center", "margin": "6px 0"})
```
Update `render`:
```python
def render(df: pd.DataFrame) -> html.Div:
    if df.empty:
        return html.Div("No pitch data.")
    return html.Div([chip_row(df, "lm"), _filter_row(df),
                     html.Div(id="lm-body", children=body(df))])
```

- [ ] **Step 4: Run the helper test to verify it passes**

Run: `python -m pytest tests/test_pitching_dash.py::test_movement_profile_apply_filters -q`
Expected: PASS.

- [ ] **Step 5: Rewire `_lm_body` in callbacks.py to apply all filters**

Replace the existing `_lm_body` callback:
```python
    @dash_app.callback(
        Output("lm-body", "children"),
        Input("lm-active", "data"), Input("lm-count", "value"),
        Input("lm-result", "value"), Input("lm-hand", "value"),
        State("game-data", "data"),
    )
    def _lm_body(active, counts_sel, results_sel, hand, data_json):
        df = _read_game_df(data_json)
        df = location_movement.apply_filters(
            df, pitch_types=active, counts=counts_sel,
            results=results_sel, hand=hand or "All")
        return location_movement.body(df)
```

- [ ] **Step 6: Add a render-contains test + run the suite**

Add to `tests/test_pitching_dash.py`:
```python
def test_movement_profile_render_has_filters():
    from app.dashboards.pitching.tabs import location_movement as lm
    s = str(lm.render(_pitch_df()))
    assert "lm-count" in s and "lm-result" in s and "lm-hand" in s
```
Run: `python -m pytest tests/test_pitching_dash.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/dashboards/pitching/tabs/location_movement.py app/dashboards/pitching/callbacks.py tests/test_pitching_dash.py
git commit -m "feat(pitching): Movement Profile count/result/handedness filters"
```

---

### Task 4: Zone Frequency handedness toggle restyle

**Files:**
- Modify: `app/dashboards/pitching/tabs/heatmaps.py` (`hm-side` Dropdown → RadioItems pills; keep id + values)
- Test: `tests/test_pitching_dash.py:227` (existing) + one new assertion

**Interfaces:**
- Consumes: nothing new.
- Produces: `hm-side` is now a `dcc.RadioItems` with values `"All"/"Right"/"Left"` and labels `All`/`vs RHH`/`vs LHH`. `callbacks._hm_body` is UNCHANGED (still reads `hm-side` value; the value strings are preserved).

- [ ] **Step 1: Extend the existing heatmaps render test (make it fail)**

In `tests/test_pitching_dash.py`, extend `test_heatmaps_tab_render_has_controls_and_body`:
```python
def test_heatmaps_tab_render_has_controls_and_body():
    from app.dashboards.pitching.tabs import heatmaps
    out = heatmaps.render(_pitch_df())
    s = str(out)
    assert "hm-pt" in s and "hm-side" in s and "hm-count" in s and "hm-body" in s
    assert "vs RHH" in s and "vs LHH" in s   # handedness toggle labels
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pitching_dash.py::test_heatmaps_tab_render_has_controls_and_body -q`
Expected: FAIL (labels not present yet).

- [ ] **Step 3: Swap the hm-side widget to RadioItems in heatmaps.py**

Replace the `hm-side` Dropdown in `render` with:
```python
            dcc.RadioItems(id="hm-side", inline=True, value="All",
                           options=[{"label": "All", "value": "All"},
                                    {"label": "vs RHH", "value": "Right"},
                                    {"label": "vs LHH", "value": "Left"}],
                           style={"display": "inline-flex", "gap": "10px",
                                  "alignItems": "center", "minWidth": "220px"}),
```
Leave `hm-pt`, `hm-count`, `hm-body`, and `callbacks._hm_body` untouched (values `"All"/"Right"/"Left"` are preserved, so `df[df["batter_side"] == side]` still works).

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_pitching_dash.py::test_heatmaps_tab_render_has_controls_and_body -q`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS (all previously-green tests + the new ones; baseline was 346).

- [ ] **Step 6: Commit**

```bash
git add app/dashboards/pitching/tabs/heatmaps.py tests/test_pitching_dash.py
git commit -m "feat(pitching): Zone Frequency handedness toggle (All / vs RHH / vs LHH)"
```

---

## Self-Review

**Spec coverage** (against `2026-07-28-pitching-dashboard-refresh-design.md`):
- Tab renames → Task 1. Hub cards "Player Dashboard" (all 3 hubs) → Task 1. Catching "Outing Video" → Task 1.
- Delete RHH v. LHH tab → Task 2.
- Movement Profile count/result/handedness filters → Task 3.
- Zone Frequency handedness toggle → Task 4.
- Constraint "keep `splits_by_batter_side`/`fig_location_split`" honored (Global Constraints + Task 2 note).

**Placeholder scan:** none — every step has concrete code or an exact command.

**Type consistency:** `apply_filters` signature identical in Task 3 definition and the `_lm_body` call. `hm-side` values `"All"/"Right"/"Left"` consistent between Task 4 widget and the untouched `_hm_body`. Tab `value` keys unchanged throughout.

**Note on live-render:** after Task 4, verify live via `python run.py` (kill by port owner first, §3b) — click Movement Profile (filters mask charts+table) and Zone Frequency (toggle) as a coach; this is the final human gate, not a test.
