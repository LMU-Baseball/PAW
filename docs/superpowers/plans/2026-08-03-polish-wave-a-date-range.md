# Polish Wave A — Global Date-Range Dropdown (SP1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace the calendar-first date picker on every stats dashboard with a preset dropdown (This Season / Past Week / Month / 3 Months / 6 Months / Year / Custom Range), anchored to the selection's latest data date, defaulting to "This Season."

**Architecture:** Add pure preset helpers + a `date_control` component to the shared `app/dashboards/date_range.py`. The preset dropdown WRITES into each dashboard's existing `{prefix}-daterange` DatePickerRange (start_date/end_date); all existing downstream callbacks that read `{prefix}-daterange` stay untouched. Each dashboard swaps `date_picker(...)` → `date_control(...)` and replaces its "pitcher→range" callback with a "preset(+pitcher)→range+calendar-visibility" callback.

**Tech Stack:** Dash, pure Python date logic, pytest.

## Global Constraints

- Python 3.12; `from __future__ import annotations`.
- Preset values (exact strings): `"season"`, `"week"`, `"month"`, `"3months"`, `"6months"`, `"year"`, `"custom"`. Labels: "This Season", "Past Week", "Past Month", "Past 3 Months", "Past 6 Months", "Past Year", "Custom Range".
- **Anchor = the latest data date for the current selection**, not `today`.
- **Season block:** Jan–Jun → Spring `[Jan 1, anchor]`; Jul–Dec → Fall `[Jul 1, anchor]`.
- Default preset everywhere = `"season"`.
- The calendar (`{prefix}-daterange`) stays the canonical range holder; the preset callback sets its `start_date`/`end_date`. Downstream range-consuming callbacks are unchanged.
- Bullpen keeps its `min_date=2025-09-01` cap on the calendar.
- Tests: `flask` not on PATH → `python -m pytest`; live-DB tests unguarded (repo convention); prefix `PYTHONIOENCODING=utf-8` for non-ASCII output. Run full suite before each commit.

---

### Task 1: Shared preset helpers + `date_control` component

**Files:**
- Modify: `app/dashboards/date_range.py`
- Test: `tests/test_date_range.py` (new)

**Interfaces produced:**
- `PRESETS: list[tuple[str,str]]`, `preset_options() -> list[dict]`
- `season_block(anchor) -> (date, date)`
- `preset_range(preset, anchor) -> (date, date) | None` (None for "custom")
- `date_control(id_prefix, anchor, *, min_date=None, max_date=None, preset="season") -> html.Div`

- [ ] **Step 1: Write failing tests** — create `tests/test_date_range.py`:

```python
from datetime import date
from app.dashboards import date_range as dr


def test_season_block_spring_and_fall():
    assert dr.season_block("2026-05-13") == (date(2026, 1, 1), date(2026, 5, 13))
    assert dr.season_block(date(2025, 11, 4)) == (date(2025, 7, 1), date(2025, 11, 4))
    # boundaries
    assert dr.season_block("2026-06-30")[0] == date(2026, 1, 1)
    assert dr.season_block("2026-07-01")[0] == date(2026, 7, 1)


def test_preset_range_windows():
    a = date(2026, 5, 13)
    assert dr.preset_range("season", a) == (date(2026, 1, 1), a)
    assert dr.preset_range("week", a) == (date(2026, 5, 6), a)
    assert dr.preset_range("month", a) == (date(2026, 4, 13), a)
    assert dr.preset_range("3months", a) == (date(2026, 2, 12), a)
    assert dr.preset_range("6months", a) == (date(2025, 11, 13), a)
    assert dr.preset_range("year", a) == (date(2025, 5, 13), a)
    assert dr.preset_range("custom", a) is None


def test_preset_options_shape_and_order():
    opts = dr.preset_options()
    assert opts[0] == {"label": "This Season", "value": "season"}
    assert opts[-1] == {"label": "Custom Range", "value": "custom"}
    assert {o["value"] for o in opts} == {"season", "week", "month", "3months",
                                          "6months", "year", "custom"}


def test_date_control_ids_and_hidden_calendar():
    comp = dr.date_control("pit", "2026-05-13")
    s = str(comp)
    assert "pit-date-preset" in s and "pit-daterange" in s and "pit-cal-wrap" in s
    # calendar hidden by default (season preset)
    assert "none" in s
```

- [ ] **Step 2: Run to verify fail** — `python -m pytest tests/test_date_range.py -q` → FAIL (helpers/component missing).

- [ ] **Step 3: Implement** — add to `app/dashboards/date_range.py` (keep existing `date_picker`, `game_options`, `range_scoreboard_text`, `ALL_IN_RANGE`):

```python
from datetime import date, timedelta

PRESETS = [
    ("season", "This Season"), ("week", "Past Week"), ("month", "Past Month"),
    ("3months", "Past 3 Months"), ("6months", "Past 6 Months"),
    ("year", "Past Year"), ("custom", "Custom Range"),
]
_PRESET_DAYS = {"week": 7, "month": 30, "3months": 90, "6months": 182, "year": 365}


def preset_options() -> list[dict]:
    return [{"label": lbl, "value": val} for val, lbl in PRESETS]


def _as_date(d) -> date:
    if isinstance(d, date):
        return d
    return date.fromisoformat(str(d)[:10])


def season_block(anchor) -> tuple[date, date]:
    """Half-year block containing `anchor`: Jan-Jun -> Spring [Jan 1, anchor];
    Jul-Dec -> Fall [Jul 1, anchor]."""
    a = _as_date(anchor)
    start = date(a.year, 1, 1) if a.month <= 6 else date(a.year, 7, 1)
    return start, a


def preset_range(preset, anchor):
    """Resolve a preset to (start, end) anchored at `anchor`. None for 'custom'
    (the caller keeps the calendar's own dates)."""
    a = _as_date(anchor)
    if preset == "season":
        return season_block(a)
    days = _PRESET_DAYS.get(preset)
    if days is None:
        return None
    return a - timedelta(days=days), a


def date_control(id_prefix, anchor, *, min_date=None, max_date=None, preset="season"):
    """Preset dropdown + a calendar (shown only for 'custom'). The calendar keeps
    id f'{id_prefix}-daterange' so existing downstream callbacks are unchanged."""
    from dash import dcc, html
    rng = preset_range(preset, anchor) or (min_date, max_date)
    start, end = rng
    return html.Div([
        dcc.Dropdown(id=f"{id_prefix}-date-preset", options=preset_options(),
                     value=preset, clearable=False, style={"minWidth": "175px"}),
        html.Div(
            date_picker(id_prefix, str(start) if start else None,
                        str(end) if end else None, min_date=min_date, max_date=max_date),
            id=f"{id_prefix}-cal-wrap",
            style={"display": "block" if preset == "custom" else "none",
                   "marginTop": "6px"}),
    ])
```

- [ ] **Step 4: Run to verify pass** — `python -m pytest tests/test_date_range.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/date_range.py tests/test_date_range.py
git commit -m "feat(date-range): shared preset helpers + date_control component"
```

---

### Task 2: Wire the bullpen dashboard onto `date_control`

**Files:**
- Modify: `app/dashboards/bullpen/layout.py` (swap the picker; compute anchor)
- Modify: `app/dashboards/bullpen/callbacks.py` (add preset→range callback)
- Test: `tests/test_bullpen_dash.py` (append)

**Interfaces consumed:** `dr.date_control`, `dr.preset_range`, `B.session_options`. Existing ids: `bp-pitcher-dd`, `bp-daterange`, `bp-session-dd`, `bp-selection`.

**Context:** The bullpen anchor = the pitcher's most-recent session date within the window. Compute via `B.session_options(pid, WINDOW_MIN, today)` (already returns newest-first) → first row's `date`, falling back to `today` when empty.

- [ ] **Step 1: Write failing test** — append to `tests/test_bullpen_dash.py`:

```python
def test_bullpen_layout_uses_preset_dropdown(server):
    import inspect
    from app.dashboards.bullpen import layout
    src = inspect.getsource(layout.serve_layout)
    assert "date_control" in src and "bp-date-preset" not in src  # id comes from component
    # the component provides bp-date-preset; assert control is used, not raw date_picker
    assert "date_picker(" not in src


def test_bullpen_preset_callback_registered(server):
    from dash import Dash
    from app.dashboards.bullpen import layout, callbacks
    app = Dash(__name__, server=server, url_base_pathname="/dash/bptest2/",
               suppress_callback_exceptions=True)
    app.layout = layout.serve_layout
    callbacks.register_callbacks(app)
    outs = {str(k) for k in app.callback_map}
    assert any("bp-daterange" in o for o in outs)  # a callback now writes the range
```

- [ ] **Step 2: Run to verify fail** — `python -m pytest tests/test_bullpen_dash.py -k "preset" -q` → FAIL.

- [ ] **Step 3: Implement**

In `app/dashboards/bullpen/layout.py` `serve_layout`, replace the `dr.date_picker("bp", ...)` line inside the selector row with:

```python
            dr.date_control("bp", start_d, min_date=WINDOW_MIN, max_date=end_d, preset="season"),
```

and set the initial range from the season preset so the first render matches the default. Just above `selector_row`, replace the `start_d, end_d = WINDOW_MIN, date.today().isoformat()` block's use so the initial selection store still gets a concrete range:

```python
    anchor = _bullpen_anchor(default_pitcher)  # helper below
    s0, e0 = dr.preset_range("season", anchor)
    start_d, end_d = str(s0), str(e0)
    # WINDOW_MIN remains the calendar min; end bound = today
    cal_max = date.today().isoformat()
```

Add a module helper in `layout.py`:

```python
def _bullpen_anchor(pitcher_id):
    if pitcher_id is None:
        return date.today().isoformat()
    s = B.session_options(int(pitcher_id), WINDOW_MIN, date.today().isoformat())
    return str(s.iloc[0]["date"]) if not s.empty else date.today().isoformat()
```

Pass `max_date=cal_max` (not `end_d`) to `date_control` so the calendar can still reach today for custom ranges. Keep `dcc.Store` `bp-selection` seeded with `start_d/end_d`.

In `app/dashboards/bullpen/callbacks.py`, add a callback (and register it) that resolves the preset:

```python
    @dash_app.callback(
        Output("bp-daterange", "start_date"), Output("bp-daterange", "end_date"),
        Output("bp-cal-wrap", "style"),
        Input("bp-date-preset", "value"), Input("bp-pitcher-dd", "value"),
        prevent_initial_call=True,
    )
    def _on_preset(preset, pitcher_id):
        from dash import no_update
        show = {"display": "block" if preset == "custom" else "none", "marginTop": "6px"}
        if preset == "custom":
            return no_update, no_update, show
        pid = _resolve(pitcher_id)
        anchor = layout._bullpen_anchor(pid)
        s, e = dr.preset_range(preset, anchor)
        return str(s), str(e), show
```

Import `date_range as dr` in callbacks.py if not present. Because `bp-daterange` start/end are already Inputs to the existing `_on_pitcher_or_range`/`_on_selection`, setting them here cascades correctly (Dash orders producer→consumer).

- [ ] **Step 4: Run to verify pass** — `python -m pytest tests/test_bullpen_dash.py -q` → PASS. Then full suite.

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/bullpen/layout.py app/dashboards/bullpen/callbacks.py tests/test_bullpen_dash.py
git commit -m "feat(date-range): bullpen dashboard on preset dropdown"
```

---

### Task 3: Wire the pitching dashboard

**Files:**
- Modify: `app/dashboards/pitching/layout.py`, `app/dashboards/pitching/callbacks.py`
- Test: `tests/test_pitching_dash.py` (append)

**Context:** Pitching currently has `_on_pitcher_range` (pitcher → `pit-daterange` start/end = the pitcher's game span). REPLACE that with a preset callback. Anchor = `P.games_for_pitcher(pid)["game_date"].max()`.

- [ ] **Step 1: Write failing test** — append to `tests/test_pitching_dash.py`:

```python
def test_pitching_uses_preset_control():
    import inspect
    from app.dashboards.pitching import layout
    src = inspect.getsource(layout.serve_layout)
    assert "date_control" in src and "date_picker(" not in src


def test_pitching_preset_callback_writes_range(server):
    from dash import Dash
    from app.dashboards.pitching import layout, callbacks
    app = Dash(__name__, server=server, url_base_pathname="/dash/pittest2/",
               suppress_callback_exceptions=True)
    app.layout = layout.serve_layout
    callbacks.register_callbacks(app)
    assert any("pit-daterange" in str(k) for k in app.callback_map)
    assert any("pit-date-preset" in str(v.inputs) for v in app.callback_map.values())
```

- [ ] **Step 2: Run to verify fail** — `python -m pytest tests/test_pitching_dash.py -k "preset" -q` → FAIL.

- [ ] **Step 3: Implement**

In `pitching/layout.py`, replace `dr.date_picker("pit", start_d, end_d)` with:
```python
            dr.date_control("pit", (end_d or date.today().isoformat()),
                            min_date=start_d, max_date=end_d, preset="season"),
```
(import `from datetime import date` if absent). Seed the initial `start_d/end_d` from the season preset when a default pitcher exists:
```python
    if default_game is not None and games_df is not None and not games_df.empty:
        anchor = str(games_df["game_date"].max())
        s0, e0 = dr.preset_range("season", anchor)
        # clamp to available bounds
        start_d = max(str(s0), str(games_df["game_date"].min()))
        end_d = anchor
```
(place after `games_df` is loaded; keep the empty-df branch as-is.)

In `pitching/callbacks.py`, REPLACE `_on_pitcher_range` with `_on_preset`:
```python
    @dash_app.callback(
        Output("pit-daterange", "start_date"), Output("pit-daterange", "end_date"),
        Output("pit-cal-wrap", "style"),
        Input("pit-date-preset", "value"), Input("pitcher-dd", "value"),
        prevent_initial_call=True,
    )
    def _on_preset(preset, pitcher_id):
        from dash import no_update
        show = {"display": "block" if preset == "custom" else "none", "marginTop": "6px"}
        if preset == "custom":
            return no_update, no_update, show
        is_coach = bool(getattr(current_user, "is_coach", False))
        own = getattr(current_user, "trackman_id", None)
        pid = selectors.resolve_pitcher(pitcher_id, is_coach=is_coach, own_trackman_id=own)
        g = P.games_for_pitcher(pid) if pid else None
        if g is None or g.empty:
            return no_update, no_update, show
        anchor = str(g["game_date"].max())
        s, e = dr.preset_range(preset, anchor)
        s = max(str(s), str(g["game_date"].min()))
        return s, str(e), show
```
Delete the old `_on_pitcher_range`. The existing `_on_range` (reads `pit-daterange` → outing options) is unchanged.

- [ ] **Step 4: Run to verify pass** — `python -m pytest tests/test_pitching_dash.py -q`, then full suite.

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/pitching/layout.py app/dashboards/pitching/callbacks.py tests/test_pitching_dash.py
git commit -m "feat(date-range): pitching dashboard on preset dropdown"
```

---

### Task 4: Wire the catching dashboard

**Files:** `app/dashboards/catching/layout.py`, `app/dashboards/catching/callbacks.py`; test `tests/test_catching_dash.py` (append).

Catching mirrors pitching exactly (same `_on_*_range` → `cat-daterange` pattern, prefix `cat`, selector id for the catcher — check the file for the catcher dropdown id, likely `catcher-dd`).

- [ ] **Step 1: Write failing test** — append to `tests/test_catching_dash.py` (mirror Task 3's two tests with prefix `cat` and url `/dash/cattest2/`; assert `date_control` used and a callback writes `cat-daterange` from `cat-date-preset`).

- [ ] **Step 2: Run to verify fail.**

- [ ] **Step 3: Implement** — in `catching/layout.py` replace `dr.date_picker("cat", ...)` with `dr.date_control("cat", anchor, min_date=start_d, max_date=end_d, preset="season")` and seed the initial range from the season preset (mirror Task 3, using catching's games_df). In `catching/callbacks.py` replace the catcher→range callback with `_on_preset` (Output `cat-daterange` start/end + `cat-cal-wrap` style; Inputs `cat-date-preset` + the catcher dropdown id; anchor = catching games_df `game_date.max()`, clamped to min). Read the file first to match its exact selector id and `games_for_*` helper name.

- [ ] **Step 4: Run to verify pass** — file suite + full suite.

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/catching/ tests/test_catching_dash.py
git commit -m "feat(date-range): catching dashboard on preset dropdown"
```

---

### Task 5: Wire the hitting (game) dashboard

**Files:** `app/dashboards/hitting/layout.py`, `app/dashboards/hitting/callbacks.py`; test `tests/test_hitting_dash.py` (append).

Hitting mirrors pitching (prefix `hit`, batter dropdown id — check file, likely `batter-dd`; anchor = hitting games_df `game_date.max()`).

- [ ] **Step 1: Write failing test** — append to `tests/test_hitting_dash.py` (mirror Task 3 with prefix `hit`, url `/dash/hittest2/`).

- [ ] **Step 2: Run to verify fail.**

- [ ] **Step 3: Implement** — read `hitting/layout.py` + `callbacks.py` to match exact ids/helpers, then apply the same swap: `date_control("hit", ...)` in layout (seed initial range from season preset), replace the batter→range callback with `_on_preset` (Output `hit-daterange` + `hit-cal-wrap`; Inputs `hit-date-preset` + batter dropdown; anchor = games max date, clamped).

- [ ] **Step 4: Run to verify pass** — file suite + full suite.

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/hitting/ tests/test_hitting_dash.py
git commit -m "feat(date-range): hitting dashboard on preset dropdown"
```

---

### Task 6: Align the hitting-practice dashboard to the shared control

**Files:** `app/dashboards/hitting_practice/layout.py`, `app/dashboards/hitting_practice/callbacks.py`; test `tests/test_hitting_practice_dash.py` (append).

Practice already has a `prac-date-preset` dropdown with a DIFFERENT option set and today-anchored logic (`P.preset_date_range`). Bring it in line: use `dr.date_control("prac", anchor, ...)` with the shared PRESETS (adds This Season default + Past 6 Months + Custom Range), anchored to the latest practice session date.

**Context:** practice anchor = latest `session_date` in the loaded plays (`P.date_bounds()` returns `(min, max)`; use `max`). The practice range callback currently reads `prac-date-preset` (old values) → sets the calendar; update it to use `dr.preset_range(preset, anchor)` and the new option set, and to toggle `prac-cal-wrap`.

- [ ] **Step 1: Write failing test** — append to `tests/test_hitting_practice_dash.py`: assert `serve_layout` source uses `date_control`, and that the preset callback resolves via `dr.preset_range` (source check) / a callback writes `prac-daterange`.

- [ ] **Step 2: Run to verify fail.**

- [ ] **Step 3: Implement** — read the practice layout + callbacks; replace the inline `dcc.Dropdown(id="prac-date-preset", options=[...old...])` + `dr.date_picker("prac", ...)` with `dr.date_control("prac", anchor, min_date=str(min_d), max_date=str(max_d), preset="season")` where `anchor = str(max_d)`. Update the practice range callback to output `prac-daterange` start/end + `prac-cal-wrap` style from `dr.preset_range(preset, anchor)` (keep the `"custom"` → show-calendar / no_update behavior). Remove the now-unused `P.preset_date_range` call from the layout (leave the function; it may be tested — check `tests/test_practice*.py` and keep it if referenced).

- [ ] **Step 4: Run to verify pass** — file suite + full suite (confirm no practice regressions).

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/hitting_practice/ tests/test_hitting_practice_dash.py
git commit -m "feat(date-range): hitting-practice dashboard on shared preset control"
```

---

## Self-Review

- **Spec coverage (SP1):** preset dropdown + This Season default + anchor-to-latest + Custom calendar → Task 1 (logic) + Tasks 2–6 (every dashboard). ✅
- **Placeholder scan:** Tasks 4/5/6 say "read the file to match exact ids/helper names" — deliberate, because those files' selector ids (catcher/batter dropdown, `games_for_*`) must be confirmed at implementation; the pattern + all new code is fully specified. Not a vague requirement.
- **Type consistency:** `preset_range`/`season_block`/`date_control` signatures identical across tasks. Component ids consistent: `{prefix}-date-preset`, `{prefix}-daterange`, `{prefix}-cal-wrap` for prefixes bp/pit/cat/hit/prac. The `_on_preset` callback shape (3 outputs: daterange start, end, cal-wrap style) is identical across dashboards.
- **Risk:** the preset callback and the existing range-consuming callbacks both touch `{prefix}-daterange`; Dash orders producer→consumer (preset writes start/end; `_on_range`/`_on_selection` read them). `prevent_initial_call=True` on `_on_preset` avoids a redundant first fire (layout already seeds the season range). Confirmed safe by the same cascade already working in the current pitching `_on_pitcher_range`.
