# Dashboard Round 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-game coach notes to all three game dashboards, plus catching legend/filter tweaks, hitting pitch-color consistency, and batted-ball fan sizing.

**Architecture:** A shared `GameNote` model in the app SQLite DB + shared note-card component/callbacks, wired identically into hitting/pitching/catching. The rest are targeted edits to chart builders, tables, and one tab. Pure helpers get unit tests; Dash render/UI get render + structural tests.

**Tech Stack:** Python, Flask + Flask-SQLAlchemy, Dash, Plotly, pandas, pytest.

## Global Constraints

- Notes are coach-write / player-read; stored in the app DB (`db` = Flask-SQLAlchemy), keyed `(module, subject_id, game_id)`. `module` ∈ {"hitting","pitching","catching"}; `subject_key` = "batter_id"/"pitcher_id"/"catcher_id".
- Brand crimson `#9A0021`; brand blue `#0076A5`. No new brand hues. Font `"Teko, sans-serif"`.
- Pitch colors: the single source of truth is `app.data.pitching.pitch_color` / `PITCH_COLORS`.
- The range sentinel is `app.dashboards.date_range.ALL_IN_RANGE`; notes are disabled for it and for `game_id is None`.
- All Dash apps run with `suppress_callback_exceptions=True`, so dynamically-rendered inner ids bind.
- Do NOT run `git stash/reset/checkout/clean`. Only `git add <named files>` + commit.
- Run the full suite with `python -m pytest -q` (currently 297 passing; must stay green).
- Restart the dev server by port owner (`Get-NetTCPConnection -LocalPort 8050 -State Listen`), never by process name.

---

### Task 1: GameNote model + note helpers

**Files:**
- Create: `app/data/notes.py`
- Modify: `app/__init__.py` (import the model before `db.create_all()`)
- Test: `tests/test_notes.py` (create)

**Interfaces:**
- Produces: `GameNote` (db.Model); `get_note(module, subject_id, game_id) -> str`; `upsert_note(module, subject_id, game_id, text, author_id=None) -> None` (empty/whitespace text deletes); `delete_note(module, subject_id, game_id) -> None`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_notes.py`:

```python
"""Tests for per-game coach notes (app DB)."""
import pytest

from app import create_app
from config import Config


@pytest.fixture
def app(tmp_path):
    class TestConfig(Config):
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 't.db'}"
    return create_app(TestConfig)


def test_upsert_get_update_delete(app):
    from app.data import notes
    with app.app_context():
        assert notes.get_note("hitting", 806253, 315) == ""
        notes.upsert_note("hitting", 806253, 315, "good AB", author_id=1)
        assert notes.get_note("hitting", 806253, 315) == "good AB"
        # update in place (no duplicate row)
        notes.upsert_note("hitting", 806253, 315, "great AB", author_id=1)
        assert notes.get_note("hitting", 806253, 315) == "great AB"
        # empty text deletes
        notes.upsert_note("hitting", 806253, 315, "   ", author_id=1)
        assert notes.get_note("hitting", 806253, 315) == ""
        # explicit delete is a no-op when absent
        notes.delete_note("hitting", 806253, 315)
        assert notes.get_note("hitting", 806253, 315) == ""


def test_notes_are_keyed_by_module_subject_game(app):
    from app.data import notes
    with app.app_context():
        notes.upsert_note("hitting", 1, 100, "H")
        notes.upsert_note("pitching", 1, 100, "P")
        assert notes.get_note("hitting", 1, 100) == "H"
        assert notes.get_note("pitching", 1, 100) == "P"
        assert notes.get_note("catching", 1, 100) == ""
        # None subject/game -> "" without raising
        assert notes.get_note("hitting", None, 100) == ""
        notes.upsert_note("hitting", None, 100, "x")  # no-op, no raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_notes.py -v`
Expected: FAIL (`app.data.notes` does not exist).

- [ ] **Step 3: Implement**

Create `app/data/notes.py`:

```python
"""Per-game coach notes, stored in the app DB and shared across game dashboards."""
from __future__ import annotations

from datetime import datetime

from app.extensions import db


class GameNote(db.Model):
    __tablename__ = "game_notes"
    __table_args__ = (
        db.UniqueConstraint("module", "subject_id", "game_id", name="uq_game_note"),
    )
    id = db.Column(db.Integer, primary_key=True)
    module = db.Column(db.String(16), nullable=False)
    subject_id = db.Column(db.Integer, nullable=False)
    game_id = db.Column(db.Integer, nullable=False)
    text = db.Column(db.Text, nullable=False, default="")
    author_id = db.Column(db.Integer, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=True)


def _row(module, subject_id, game_id):
    return db.session.scalar(db.select(GameNote).filter_by(
        module=module, subject_id=int(subject_id), game_id=int(game_id)))


def get_note(module, subject_id, game_id) -> str:
    if subject_id is None or game_id is None:
        return ""
    row = _row(module, subject_id, game_id)
    return row.text if row else ""


def upsert_note(module, subject_id, game_id, text, author_id=None) -> None:
    if subject_id is None or game_id is None:
        return
    text = (text or "").strip()
    if not text:
        delete_note(module, subject_id, game_id)
        return
    row = _row(module, subject_id, game_id)
    if row is None:
        row = GameNote(module=module, subject_id=int(subject_id), game_id=int(game_id))
        db.session.add(row)
    row.text = text
    row.author_id = author_id
    row.updated_at = datetime.utcnow()
    db.session.commit()


def delete_note(module, subject_id, game_id) -> None:
    if subject_id is None or game_id is None:
        return
    db.session.execute(db.delete(GameNote).filter_by(
        module=module, subject_id=int(subject_id), game_id=int(game_id)))
    db.session.commit()
```

In `app/__init__.py`, import the model so `db.create_all()` builds the table — add right after the auth-models import (`from app.auth import models  # noqa: F401`):

```python
    from app.data import notes  # noqa: F401  (registers GameNote for create_all)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_notes.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/data/notes.py app/__init__.py tests/test_notes.py
git commit -m "feat(notes): GameNote app-DB model + get/upsert/delete helpers"
```

---

### Task 2: Shared note-card component + callbacks

**Files:**
- Create: `app/dashboards/notes_ui.py`
- Test: `tests/test_notes_ui.py` (create)

**Interfaces:**
- Consumes: `app.data.notes`, `app.dashboards.date_range.ALL_IN_RANGE`.
- Produces: `note_card(module) -> html.Div` (id `f"{module}-note-card"`); `register_note_callbacks(dash_app, module, subject_key) -> None`; `_render_note(module, subject_id, game_id, is_coach) -> html.Div` (pure, testable).

- [ ] **Step 1: Write the failing test**

Create `tests/test_notes_ui.py`:

```python
"""Tests for the shared note-card component."""
from dash import dcc, html


def _walk(node, pred, out):
    if pred(node):
        out.append(node)
    ch = getattr(node, "children", None)
    kids = ch if isinstance(ch, (list, tuple)) else ([ch] if ch is not None else [])
    for k in kids:
        if hasattr(k, "children") or pred(k):
            _walk(k, pred, out)
    return out


def test_note_card_has_module_id():
    from app.dashboards import notes_ui
    card = notes_ui.note_card("pitching")
    assert card.id == "pitching-note-card"


def test_render_note_coach_has_textarea_and_buttons():
    from app.dashboards import notes_ui
    # coach + a concrete game -> editable
    view = notes_ui._render_note("hitting", 806253, 315, is_coach=True)
    tas = _walk(view, lambda n: isinstance(n, dcc.Textarea), [])
    btns = _walk(view, lambda n: isinstance(n, html.Button), [])
    assert any(t.id == "hitting-note-text" for t in tas)
    assert {b.id for b in btns} >= {"hitting-note-save", "hitting-note-delete"}


def test_render_note_player_is_read_only():
    from app.dashboards import notes_ui
    view = notes_ui._render_note("hitting", 806253, 315, is_coach=False)
    tas = _walk(view, lambda n: isinstance(n, dcc.Textarea), [])
    assert not tas  # player never gets an editor


def test_render_note_range_or_none_game_is_hint():
    from app.dashboards import notes_ui
    from app.dashboards.date_range import ALL_IN_RANGE
    for gid in (None, ALL_IN_RANGE):
        view = notes_ui._render_note("hitting", 806253, gid, is_coach=True)
        btns = _walk(view, lambda n: isinstance(n, html.Button), [])
        assert not btns  # no Save/Delete when there's no single game


def test_register_note_callbacks_binds(monkeypatch):
    from app.dashboards import notes_ui

    class FakeApp:
        def __init__(self):
            self.n = 0
        def callback(self, *a, **k):
            def deco(fn):
                self.n += 1
                return fn
            return deco

    app = FakeApp()
    notes_ui.register_note_callbacks(app, "catching", "catcher_id")
    assert app.n == 3  # render + save + delete
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_notes_ui.py -v`
Expected: FAIL (`app.dashboards.notes_ui` does not exist).

- [ ] **Step 3: Implement**

Create `app/dashboards/notes_ui.py`:

```python
"""Shared per-game coach-note card + callbacks for the game dashboards."""
from __future__ import annotations

from dash import Input, Output, State, dcc, html
from flask_login import current_user

from app.data import notes
from app.dashboards import date_range as dr

_CRIMSON = "#9A0021"
_BOX = {"fontStyle": "italic", "padding": "10px 12px",
        "backgroundColor": "rgba(255,255,255,0.75)", "borderRadius": "8px"}


def note_card(module: str) -> html.Div:
    """Persistent container; populated by the render callback on selection change."""
    return html.Div(id=f"{module}-note-card", style={"margin": "8px 0"})


def _header():
    return html.Div("Coach Note", style={"color": _CRIMSON, "fontWeight": "bold",
                                         "fontSize": "16px", "marginBottom": "4px"})


def _render_note(module: str, subject_id, game_id, is_coach: bool) -> html.Div:
    if subject_id is None or game_id is None or game_id == dr.ALL_IN_RANGE:
        return html.Div([_header(), html.Div(
            "Select a single game to add a note.", style={**_BOX, "color": "#888"})])
    text = notes.get_note(module, subject_id, game_id)
    if not is_coach:
        return html.Div([_header(),
                         html.Div(text or "No note for this game.", style=_BOX)])
    return html.Div([
        _header(),
        dcc.Textarea(id=f"{module}-note-text", value=text,
                     style={"width": "100%", "minHeight": "70px", "padding": "8px",
                            "borderRadius": "8px", "fontFamily": "Teko, sans-serif",
                            "fontSize": "15px"}),
        html.Div([
            html.Button("Save", id=f"{module}-note-save", n_clicks=0,
                        style={"background": _CRIMSON, "color": "#fff", "border": "none",
                               "borderRadius": "8px", "padding": "6px 16px",
                               "cursor": "pointer", "fontFamily": "Teko, sans-serif",
                               "marginRight": "8px"}),
            html.Button("Delete", id=f"{module}-note-delete", n_clicks=0,
                        style={"background": "#fff", "color": _CRIMSON,
                               "border": f"2px solid {_CRIMSON}", "borderRadius": "8px",
                               "padding": "5px 14px", "cursor": "pointer",
                               "fontFamily": "Teko, sans-serif"}),
            html.Span(id=f"{module}-note-status",
                      style={"marginLeft": "10px", "color": "#555", "fontSize": "14px"}),
        ], style={"marginTop": "6px"}),
    ])


def register_note_callbacks(dash_app, module: str, subject_key: str) -> None:
    @dash_app.callback(
        Output(f"{module}-note-card", "children"),
        Input("selection", "data"),
    )
    def _note_render(sel):
        sel = sel or {}
        is_coach = bool(getattr(current_user, "is_coach", False))
        return _render_note(module, sel.get(subject_key), sel.get("game_id"), is_coach)

    @dash_app.callback(
        Output(f"{module}-note-status", "children"),
        Input(f"{module}-note-save", "n_clicks"),
        State(f"{module}-note-text", "value"), State("selection", "data"),
        prevent_initial_call=True,
    )
    def _note_save(_n, text, sel):
        if not getattr(current_user, "is_coach", False):
            return "Coaches only."
        sel = sel or {}
        gid = sel.get("game_id")
        if sel.get(subject_key) is None or gid is None or gid == dr.ALL_IN_RANGE:
            return ""
        notes.upsert_note(module, sel[subject_key], gid, text,
                          getattr(current_user, "id", None))
        return "Saved." if (text or "").strip() else "Deleted."

    @dash_app.callback(
        Output(f"{module}-note-text", "value"),
        Output(f"{module}-note-status", "children", allow_duplicate=True),
        Input(f"{module}-note-delete", "n_clicks"),
        State("selection", "data"),
        prevent_initial_call=True,
    )
    def _note_delete(_n, sel):
        if not getattr(current_user, "is_coach", False):
            return "", "Coaches only."
        sel = sel or {}
        gid = sel.get("game_id")
        if sel.get(subject_key) is not None and gid is not None and gid != dr.ALL_IN_RANGE:
            notes.delete_note(module, sel[subject_key], gid)
        return "", "Deleted."
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_notes_ui.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/notes_ui.py tests/test_notes_ui.py
git commit -m "feat(notes): shared note-card component + render/save/delete callbacks"
```

---

### Task 3: Wire notes into hitting, pitching, catching

**Files:**
- Modify: `app/dashboards/hitting/layout.py`, `app/dashboards/pitching/layout.py`, `app/dashboards/catching/layout.py` (insert the card)
- Modify: `app/dashboards/hitting/callbacks.py`, `app/dashboards/pitching/callbacks.py`, `app/dashboards/catching/callbacks.py` (register note callbacks)
- Modify: `app/dashboards/hitting/tabs/game_level.py` (drop in-tab note) + the hitting `_render_tab` "game" branch
- Test: `tests/test_notes_ui.py` (append) + updates to existing dashboard tests if they assert the note block

**Interfaces:**
- Consumes: `notes_ui.note_card`, `notes_ui.register_note_callbacks`.
- Produces: each dashboard layout contains `f"{module}-note-card"`; note callbacks registered; hitting Game Level no longer renders a note block.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_notes_ui.py`:

```python
def test_game_level_has_no_inline_note_block():
    import inspect
    from app.dashboards.hitting.tabs import game_level
    src = inspect.getsource(game_level)
    assert "No note for this game." not in src  # note moved to the shared card
    assert "Coach Note" not in src


def test_dashboard_callbacks_register_notes():
    import inspect
    for mod, key in [("hitting", "batter_id"), ("pitching", "pitcher_id"),
                     ("catching", "catcher_id")]:
        cb = __import__(f"app.dashboards.{mod}.callbacks", fromlist=["x"])
        src = inspect.getsource(cb)
        assert "register_note_callbacks" in src
        assert f'"{key}"' in src


def test_dashboard_layouts_place_note_card():
    import inspect
    for mod in ("hitting", "pitching", "catching"):
        lay = __import__(f"app.dashboards.{mod}.layout", fromlist=["x"])
        assert f'note_card("{mod}")' in inspect.getsource(lay)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_notes_ui.py::test_game_level_has_no_inline_note_block tests/test_notes_ui.py::test_dashboard_callbacks_register_notes tests/test_notes_ui.py::test_dashboard_layouts_place_note_card -v`
Expected: FAIL.

- [ ] **Step 3: Implement — layouts**

In each of `hitting/layout.py`, `pitching/layout.py`, `catching/layout.py`, add the import and insert the card between the selector row and the tabs. Import (top of each file):

```python
from app.dashboards import notes_ui
```

In `serve_layout`, the inner content Div currently looks like
`html.Div([selector_row, tabs, html.Div(id="tab-content", ...)], ...)` (hitting/pitching)
or the catching equivalent. Insert the card so it reads:

```python
            html.Div([selector_row, notes_ui.note_card("hitting"), tabs,
                      html.Div(id="tab-content", style={"padding": "8px 16px"})],
                     style={"flexGrow": "1"}),
```

Use `"pitching"` / `"catching"` in the respective files. (Match each file's existing
structure — only add `notes_ui.note_card("<module>")` between the selector row and
`tabs`; keep everything else.)

- [ ] **Step 4: Implement — callback registration**

At the end of each dashboard's `register_callbacks(dash_app)` body, add (import `notes_ui` at the top of each callbacks file):

```python
    notes_ui.register_note_callbacks(dash_app, "hitting", "batter_id")
```

Use `("pitching", "pitcher_id")` and `("catching", "catcher_id")` in the respective
files.

- [ ] **Step 5: Implement — drop hitting's in-tab note**

In `app/dashboards/hitting/tabs/game_level.py`, remove the `note` param, the
`note_block`, and the `_section("Coach Note", ...)` entry. New `render`:

```python
def render(game_df: pd.DataFrame) -> html.Div:
    line = hitting.game_batting_line(game_df)
    line_df = pd.DataFrame([line])
    _drop = ["Avg QC+", "Avg PathQ+"]
    bb_overall = hitting.batted_ball_profile(game_df).drop(columns=_drop, errors="ignore")
    bb_pt = hitting.batted_ball_profile(game_df, by_pitch_type=True).drop(
        columns=_drop, errors="ignore")
    return html.Div([
        _section("Batting Line", tables.stat_table(line_df, id="tbl-line")),
        _section("Batted Ball Profile", tables.stat_table(bb_overall, id="tbl-bb")),
        _section("Batted Ball by Pitch Type", tables.stat_table(bb_pt, id="tbl-bb-pt")),
    ], style={"padding": "10px 4px"})
```

In `app/dashboards/hitting/callbacks.py`, the `_render_tab` "game" branch changes from
`return game_level.render(df, note="")` to `return game_level.render(df)` (drop the
comment about legacy notes too).

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_notes_ui.py tests/test_hitting_dash.py tests/test_pitching_dash.py tests/test_catching_dash.py -q`
Expected: PASS (fix any existing hitting test that asserted the old inline note block by removing that assertion).

- [ ] **Step 7: Commit**

```bash
git add app/dashboards/hitting app/dashboards/pitching app/dashboards/catching tests/test_notes_ui.py
git commit -m "feat(notes): wire the shared note card into all three game dashboards"
```

---

### Task 4: Catching — remove framing legends

**Files:**
- Modify: `app/dashboards/catching/charts.py` (`framing_scatter`, `framing_facets`)
- Test: `tests/test_catching_dash.py` (append)

**Interfaces:**
- Produces: `framing_scatter` and `framing_facets` both render with `showlegend=False`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_catching_dash.py`:

```python
def test_framing_legends_are_off():
    import pandas as pd
    from app.dashboards.catching import charts
    df = pd.DataFrame([
        {"plate_loc_side": s, "plate_loc_height": h, "izt_zone": z,
         "pitch_call": "StrikeCalled", "batter_side": "Right",
         "pitcher_throws": "Right", "rel_speed": 90.0}
        for s, h, z in [(-0.5, 2.5, "1"), (0.5, 2.5, "Ball")]
    ])
    assert charts.framing_scatter(df).layout.showlegend is False
    assert charts.framing_facets(df, by="batter_side",
                                 title="Batter Side").layout.showlegend is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_catching_dash.py::test_framing_legends_are_off -v`
Expected: FAIL (`framing_scatter` has `showlegend=True`; facets default legend on).

- [ ] **Step 3: Implement**

In `app/dashboards/catching/charts.py::framing_scatter`, change the layout
`showlegend=True` to `showlegend=False`.

In `framing_facets`, add `showlegend=False` to the `fig.update_layout(...)` call
(alongside `title=title, height=360*nrows, ...`).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_catching_dash.py::test_framing_legends_are_off -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/catching/charts.py tests/test_catching_dash.py
git commit -m "feat(catching): remove framing scatter + facet legends"
```

---

### Task 5: Catching — Static Framing call-type chips

**Files:**
- Modify: `app/dashboards/catching/tabs/static_framing.py` (chip row + body split)
- Modify: `app/dashboards/catching/callbacks.py` (static-call toggle/body/styles)
- Test: `tests/test_catching_dash.py` (append)

**Interfaces:**
- Consumes: `charts.CALLTYPE_COLORS`, `C.add_framing_cols`.
- Produces: `static_framing.body(df, active_calls=None) -> html.Div`; `static_framing.render(df)` shows a `static-call-chip` row + `static-body`; catching callbacks add `_static_call_toggle`/`_static_body`/`_static_call_styles`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_catching_dash.py`:

```python
def test_static_framing_has_call_chips_and_filters():
    import inspect
    import pandas as pd
    from app.dashboards.catching.tabs import static_framing
    src = inspect.getsource(static_framing)
    assert "static-call-chip" in src and "static-call-active" in src
    df = pd.DataFrame([
        {"plate_loc_side": s, "plate_loc_height": h, "izt_zone": z,
         "pitch_call": pc, "batter_side": "Right", "pitcher_throws": "Right",
         "rel_speed": 90.0}
        for s, h, z, pc in [(-0.5, 2.5, "1", "StrikeCalled"),
                            (0.6, 2.6, "Ball", "StrikeCalled")]
    ])
    # body accepts an active_calls filter and still renders
    assert static_framing.body(df, active_calls=["Stolen Strike"]) is not None
    assert static_framing.body(df, active_calls=None) is not None


def test_catching_callbacks_have_static_call():
    import inspect
    from app.dashboards.catching import callbacks
    src = inspect.getsource(callbacks)
    assert "static-call-active" in src and "static-body" in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_catching_dash.py::test_static_framing_has_call_chips_and_filters tests/test_catching_dash.py::test_catching_callbacks_have_static_call -v`
Expected: FAIL.

- [ ] **Step 3: Implement — the tab**

Replace `app/dashboards/catching/tabs/static_framing.py`:

```python
"""Static Framing tab: call-type chips + 4 faceted stolen/lost scatters."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import catching as C
from app.dashboards.catching import charts
from app.dashboards.shell import section

_FACETS = [
    ("batter_side", "Batter Side"),
    ("pitcher_throws", "Pitcher Side"),
    ("PitchSpeed", "Pitch Speed"),
    ("Zone", "Zone Location"),
]
_CALL_ORDER = ["Stolen Strike", "Lost Strike", "Correct Call"]


def call_chip_row() -> html.Div:
    chips = [html.Button(
        ct, id={"type": "static-call-chip", "index": ct}, n_clicks=0,
        style={"border": f"2px solid {charts.CALLTYPE_COLORS[ct]}",
               "background": charts.CALLTYPE_COLORS[ct], "color": "#fff",
               "borderRadius": "14px", "padding": "3px 12px",
               "margin": "0 6px 6px 0", "cursor": "pointer",
               "fontFamily": "Teko, sans-serif", "fontSize": "15px"})
        for ct in _CALL_ORDER]
    return html.Div([dcc.Store(id="static-call-active", data=list(_CALL_ORDER)),
                     html.Div(chips)], style={"margin": "6px 0"})


def body(df: pd.DataFrame, active_calls=None) -> html.Div:
    if df.empty:
        return html.Div("No pitch data.")
    f = C.add_framing_cols(df)
    if active_calls is not None:
        f = f[f["CallType"].isin(active_calls)]
    graphs = []
    for by, title in _FACETS:
        graphs.append(section(title))
        graphs.append(dcc.Graph(figure=charts.framing_facets(f, by=by, title=title)))
    return html.Div(graphs)


def render(df: pd.DataFrame) -> html.Div:
    if df.empty:
        return html.Div("No pitch data.")
    return html.Div([call_chip_row(),
                     html.Div(id="static-body", children=body(df))])
```

- [ ] **Step 4: Implement — the callbacks**

In `app/dashboards/catching/callbacks.py`, add (inside `register_callbacks`, mirroring the existing `call-*` trio):

```python
    @dash_app.callback(
        Output("static-call-active", "data"),
        Input({"type": "static-call-chip", "index": ALL}, "n_clicks"),
        State("static-call-active", "data"),
        prevent_initial_call=True,
    )
    def _static_call_toggle(_clicks, active):
        tid = ctx.triggered_id
        if not tid:
            return active
        ct = tid["index"]
        active = list(active or [])
        return [c for c in active if c != ct] if ct in active else active + [ct]

    @dash_app.callback(
        Output("static-body", "children"),
        Input("static-call-active", "data"), State("game-data", "data"),
    )
    def _static_body(active, data_json):
        df = _read_game_df(data_json)
        if df.empty:
            return html.Div("No pitch data.")
        return static_framing.body(df, active_calls=active)

    @dash_app.callback(
        Output({"type": "static-call-chip", "index": ALL}, "style"),
        Input("static-call-active", "data"),
        State({"type": "static-call-chip", "index": ALL}, "id"),
    )
    def _static_call_styles(active, ids):
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

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_catching_dash.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/dashboards/catching/tabs/static_framing.py app/dashboards/catching/callbacks.py tests/test_catching_dash.py
git commit -m "feat(catching): static-framing call-type chips filtering all facets"
```

---

### Task 6: Hitting — pitch-color consistency with pitching

**Files:**
- Modify: `app/dashboards/hitting/charts.py` (`color_for` delegates; `PITCH_COLORS` repointed)
- Modify: `app/dashboards/hitting/tables.py` (`stat_table` colors `TaggedPitchType`)
- Test: `tests/test_hitting_dash.py` (append)

**Interfaces:**
- Consumes: `app.data.pitching.pitch_color`, `app.data.pitching.PITCH_COLORS`.
- Produces: `charts.color_for(pt) == pitching.pitch_color(pt)`; `stat_table(df, color_col="TaggedPitchType")` colors that column, no-op when absent.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_hitting_dash.py`:

```python
def test_hitting_pitch_colors_match_pitching():
    from app.dashboards.hitting import charts
    from app.data import pitching as P
    for pt in ("Fastball", "ChangeUp", "Cutter", "Slider", "Sinker", "Curveball"):
        assert charts.color_for(pt) == P.pitch_color(pt)


def test_stat_table_colors_tagged_pitch_type():
    import pandas as pd
    from app.dashboards.hitting import tables
    from app.data import pitching as P
    df = pd.DataFrame({"TaggedPitchType": ["Slider", "Sinker"], "Balls": [0, 1]})
    tbl = tables.stat_table(df, id="t")
    conds = tbl.style_data_conditional or []
    colored = {c.get("color") for c in conds
               if c.get("if", {}).get("column_id") == "TaggedPitchType"}
    assert P.pitch_color("Slider") in colored and P.pitch_color("Sinker") in colored
    # no-op without the column
    plain = tables.stat_table(pd.DataFrame({"PA": [1]}), id="t2")
    assert not any(c.get("if", {}).get("column_id") == "TaggedPitchType"
                   for c in (plain.style_data_conditional or []))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_hitting_dash.py::test_hitting_pitch_colors_match_pitching tests/test_hitting_dash.py::test_stat_table_colors_tagged_pitch_type -v`
Expected: FAIL (hitting palette differs; `stat_table` has no coloring).

- [ ] **Step 3: Implement**

In `app/dashboards/hitting/charts.py`, replace the local `PITCH_COLORS`/`_DEFAULT_COLOR`/`color_for` with a delegation to pitching (keep `PITCH_COLORS` as an alias for any external importer):

```python
from app.data import pitching as _pitching

PITCH_COLORS = _pitching.PITCH_COLORS  # single source of truth (matches pitchers)


def color_for(pitch_type: str) -> str:
    return _pitching.pitch_color(pitch_type)
```

(Delete the old `PITCH_COLORS = {...}` dict, `_DEFAULT_COLOR`, and the old
`color_for` body.)

In `app/dashboards/hitting/tables.py`, add the coloring to `stat_table`:

```python
from app.data.pitching import pitch_color as _pitch_color


def stat_table(df: pd.DataFrame, *, id: str | None = None,
               color_col: str = "TaggedPitchType") -> dash_table.DataTable:
    d = _format(df)
    cols = [{"name": c, "id": c} for c in d.columns]
    conditional = []
    if color_col in d.columns:
        for pt in d[color_col].dropna().unique():
            conditional.append({
                "if": {"filter_query": f'{{{color_col}}} = "{str(pt)}"',
                       "column_id": color_col},
                "color": _pitch_color(str(pt)), "fontWeight": "bold"})
    return dash_table.DataTable(
        id=id or "stat-table",
        columns=cols,
        data=d.to_dict("records"),
        style_as_list_view=True,
        style_header={"backgroundColor": "#9A0021", "color": "white",
                      "fontWeight": "bold", "textAlign": "center"},
        style_cell={"textAlign": "center", "padding": "6px 10px",
                    "fontFamily": "Teko, sans-serif", "fontSize": "16px"},
        style_data={"backgroundColor": "rgba(255,255,255,0.85)"},
        style_data_conditional=conditional,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_hitting_dash.py::test_hitting_pitch_colors_match_pitching tests/test_hitting_dash.py::test_stat_table_colors_tagged_pitch_type -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/hitting/charts.py app/dashboards/hitting/tables.py tests/test_hitting_dash.py
git commit -m "feat(hitting): pitch colors match pitching + colored TaggedPitchType column"
```

---

### Task 7: Batted Ball fan — match landing scale + de-overlap labels

**Files:**
- Modify: `app/dashboards/hitting_practice/charts.py` (`spray_distribution_fan`)
- Test: `tests/test_hitting_practice_dash.py` (append)

**Interfaces:**
- Produces: `spray_distribution_fan` uses x-range `[-340, 340]`; infield `%` annotations sit at radius ≥ 108.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_hitting_practice_dash.py`:

```python
def test_fan_matches_landing_scale_and_labels_spread():
    import pandas as pd
    import numpy as np
    from app.dashboards.hitting_practice import charts
    from app.data import practice as P
    plays = pd.DataFrame([
        {"horizontal_angle": -30.0, "distance_feet": 100.0, "exit_velocity": 85.0, "hit_type": 1},
        {"horizontal_angle": 10.0, "distance_feet": 120.0, "exit_velocity": 88.0, "hit_type": 1},
    ])
    fig = charts.spray_distribution_fan(P.spray_fan(plays))
    assert list(fig.layout.xaxis.range) == [-340, 340]
    # infield-ring (near home) labels are pushed out to >= 108 ft radius
    radii = [float(np.hypot(a.x, a.y)) for a in fig.layout.annotations]
    assert radii and min(radii) >= 108.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_hitting_practice_dash.py::test_fan_matches_landing_scale_and_labels_spread -v`
Expected: FAIL (x-range is `[-440,440]`; infield label radius ~75).

- [ ] **Step 3: Implement**

In `app/dashboards/hitting_practice/charts.py::spray_distribution_fan`:

Change the annotation radius line from
`mid_r = (float(row["r0"]) + float(row["r1"])) / 2.0`
to:

```python
            mid_r = max((float(row["r0"]) + float(row["r1"])) / 2.0, 108.0)
```

Change the xaxis range in `fig.update_layout(...)` from
`xaxis=dict(range=[-P.FAN_DISPLAY_MAX, P.FAN_DISPLAY_MAX], visible=False)`
to:

```python
        xaxis=dict(range=[-340, 340], visible=False),
```

(Leave the yaxis range at `[-20, P.FAN_DISPLAY_MAX + 20]`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_hitting_practice_dash.py::test_fan_matches_landing_scale_and_labels_spread tests/test_hitting_practice_dash.py::test_spray_fan_hover_has_balls_ev_dist -v`
Expected: PASS (both).

- [ ] **Step 5: Commit**

```bash
git add app/dashboards/hitting_practice/charts.py tests/test_hitting_practice_dash.py
git commit -m "feat(practice): fan matches landing scale + spreads infield labels"
```

---

### Task 8: Full-suite gate + live smoke

**Files:** none (verification only)

- [ ] **Step 1: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS (≥ 297 + the new tests; 0 failures).

- [ ] **Step 2: Restart the dev server by port owner**

```powershell
Get-NetTCPConnection -LocalPort 8050 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```
Confirm the port is free, then relaunch one instance: `PYTHONIOENCODING=utf-8 python run.py`.

- [ ] **Step 3: Live smoke, both roles**

Coach (`coach@lmu.edu` / `paw2026`) and player (`hitter@lmu.edu` / `paw2026`):
  - Notes: on hitting/pitching/catching, a "Coach Note" card sits above the tabs. Coach can type + Save + Delete on a single game; picking "All games in range" shows the hint; player sees the saved note read-only. Save then reselect the game → the note persists.
  - Catching: Overall Framing has no right legend; Static Framing shows Stolen/Lost/Correct chips that filter all four facets and has no right legend.
  - Hitting: PA-table `TaggedPitchType` text and the pitch dots are colored the same as the pitching dashboard (e.g. ChangeUp is purple).
  - Practice → Batted Ball: the fan is the same size as the landing chart and the infield % labels no longer overlap.

- [ ] **Step 4: Commit any smoke-fix follow-ups** (only if the smoke surfaces a defect).

---

## Self-Review

**Spec coverage:** A (notes) → Tasks 1 (model) + 2 (UI) + 3 (wiring). B (Overall legend) → Task 4. C (Static chips + legend) → Tasks 4 (facet legend) + 5 (chips). D (hitting colors) → Task 6. E (fan) → Task 7. Every section maps to a task.

**Placeholder scan:** No TBD/TODO/"handle edge cases". All code steps carry real code.

**Type consistency:**
- `get_note`/`upsert_note`/`delete_note` (Task 1) consumed by `notes_ui` (Task 2). `GameNote` registered for `create_all` via the Task 1 `app/__init__.py` import.
- `note_card`/`register_note_callbacks`/`_render_note` (Task 2) consumed by Task 3 wiring and Task 2/3 tests.
- `subject_key` values ("batter_id"/"pitcher_id"/"catcher_id") match each dashboard's `selection` store keys (verified in the callbacks).
- `charts.CALLTYPE_COLORS` + `C.add_framing_cols` (existing) consumed by Task 5; `framing_facets` legend-off (Task 4) applies to the facets Task 5 renders.
- `pitching.pitch_color`/`PITCH_COLORS` consumed by Task 6 (both charts + tables).

**Ordering note:** Task 2 depends on Task 1; Task 3 depends on Tasks 1–2; Task 5's facets rely on Task 4's legend-off (Task 4 first). Tasks 6–7 are independent. Existing tests re-run in each task's Step 6/4 continue to hold; the one known update is any hitting test asserting the old inline "Coach Note" (removed in Task 3 Step 6).
