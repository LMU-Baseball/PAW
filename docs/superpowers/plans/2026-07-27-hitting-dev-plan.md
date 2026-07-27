# Hitting Development Plan Tab — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add a per-player, coach-authored **Development Plan** tab to the hitting dashboard (coach edits, player reads), stored in the app DB.

**Architecture:** A new `DevPlan` app-DB model + get/upsert/delete helpers in `app/data/dev_plans.py`, mirroring `app/data/notes.py` but keyed by (module, subject_id) with no game_id. A tab module renders an editable card for coaches / read-only text for players, mirroring `notes_ui`. The hitting `callbacks.py` gains a render branch + save/delete callbacks.

**Tech Stack:** Flask-SQLAlchemy, Dash (`dcc.Textarea`, buttons, callbacks), pytest.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-27-hitting-dev-plan-design.md`. Branch `feat/pitch-level-video`.
- Mirror `app/data/notes.py` (model + get/upsert/delete) and `app/dashboards/notes_ui.py` (card styling + coach-gated callbacks).
- App-DB models auto-create via `db.create_all()` in `create_app`, but ONLY if imported first — add `from app.data import dev_plans  # noqa: F401` beside the existing `from app.data import notes` line in `app/__init__.py`.
- Selection store key: `batter_id`. `current_user.is_coach` gates writes. `current_user` is already imported in the hitting `callbacks.py`.
- Colors: crimson `#9A0021`, font `Teko, sans-serif`. Full suite stays green. Run `python -m pytest -q`.

---

### Task 1: Data model `app/data/dev_plans.py` + registration

**Files:**
- Create: `app/data/dev_plans.py`
- Modify: `app/__init__.py` (add the import beside `notes`, ~line 28)
- Test: `tests/test_dev_plans.py`

**Interfaces — Produces:** `DevPlan` model; `get_plan(module, subject_id) -> str`; `upsert_plan(module, subject_id, text, author_id=None) -> None`; `delete_plan(module, subject_id) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dev_plans.py
"""Tests for per-player development plans (app DB)."""
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
    from app.data import dev_plans
    with app.app_context():
        assert dev_plans.get_plan("hitting", 806253) == ""
        dev_plans.upsert_plan("hitting", 806253, "work on load timing", author_id=1)
        assert dev_plans.get_plan("hitting", 806253) == "work on load timing"
        dev_plans.upsert_plan("hitting", 806253, "stay through the ball", author_id=1)
        assert dev_plans.get_plan("hitting", 806253) == "stay through the ball"
        dev_plans.upsert_plan("hitting", 806253, "   ", author_id=1)  # blank deletes
        assert dev_plans.get_plan("hitting", 806253) == ""
        dev_plans.delete_plan("hitting", 806253)  # no-op when absent
        assert dev_plans.get_plan("hitting", 806253) == ""


def test_keyed_by_module_subject(app):
    from app.data import dev_plans
    with app.app_context():
        dev_plans.upsert_plan("hitting", 1, "H")
        dev_plans.upsert_plan("pitching", 1, "P")
        assert dev_plans.get_plan("hitting", 1) == "H"
        assert dev_plans.get_plan("pitching", 1) == "P"
        assert dev_plans.get_plan("catching", 1) == ""
        assert dev_plans.get_plan("hitting", None) == ""  # None subject -> "", no raise
        dev_plans.upsert_plan("hitting", None, "x")        # no-op, no raise
```

- [ ] **Step 2: Run test** — `python -m pytest tests/test_dev_plans.py -q` → FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement**

```python
# app/data/dev_plans.py
"""Per-player coach-authored development plans, stored in the app DB.

One plan per (module, subject_id) — e.g. a hitter's development plan. Coaches
write; players read. Mirrors app/data/notes.py but without a game_id.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.extensions import db


class DevPlan(db.Model):
    __tablename__ = "dev_plans"
    __table_args__ = (
        db.UniqueConstraint("module", "subject_id", name="uq_dev_plan"),
    )
    id = db.Column(db.Integer, primary_key=True)
    module = db.Column(db.String(16), nullable=False)
    subject_id = db.Column(db.Integer, nullable=False)
    text = db.Column(db.Text, nullable=False, default="")
    author_id = db.Column(db.Integer, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=True)


def _row(module, subject_id):
    return db.session.scalar(db.select(DevPlan).filter_by(
        module=module, subject_id=int(subject_id)))


def get_plan(module, subject_id) -> str:
    if subject_id is None:
        return ""
    row = _row(module, subject_id)
    return row.text if row else ""


def upsert_plan(module, subject_id, text, author_id=None) -> None:
    if subject_id is None:
        return
    text = (text or "").strip()
    if not text:
        delete_plan(module, subject_id)
        return
    row = _row(module, subject_id)
    if row is None:
        row = DevPlan(module=module, subject_id=int(subject_id))
        db.session.add(row)
    row.text = text
    row.author_id = author_id
    row.updated_at = datetime.now(timezone.utc)
    db.session.commit()


def delete_plan(module, subject_id) -> None:
    if subject_id is None:
        return
    db.session.execute(db.delete(DevPlan).filter_by(
        module=module, subject_id=int(subject_id)))
    db.session.commit()
```

In `app/__init__.py`, add the import beside the notes one (so the model registers before `db.create_all()`):
```python
    from app.data import notes  # noqa: F401  (registers GameNote for create_all)
    from app.data import dev_plans  # noqa: F401  (registers DevPlan for create_all)
```

- [ ] **Step 4: Run tests** — `python -m pytest tests/test_dev_plans.py -q` → PASS.
- [ ] **Step 5: Commit**

```bash
git add app/data/dev_plans.py app/__init__.py tests/test_dev_plans.py
git commit -m "feat(dev-plans): DevPlan app-DB model + get/upsert/delete helpers"
```

---

### Task 2: Dev Plan tab + wiring

**Files:**
- Create: `app/dashboards/hitting/tabs/dev_plan.py`
- Modify: `app/dashboards/hitting/layout.py` (tabs list)
- Modify: `app/dashboards/hitting/callbacks.py` (imports; `_render_tab` branch; two callbacks)
- Test: `tests/test_hitting_dash.py` (append)

**Interfaces — Produces:** `dev_plan.render(subject_id, is_coach) -> html.Div`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_hitting_dash.py`)

```python
def test_dev_plan_render_prompt_coach_player():
    from app.dashboards.hitting.tabs import dev_plan
    # no hitter selected -> prompt
    assert "Select a hitter" in str(dev_plan.render(None, True))


def test_hitting_tabs_include_dev_plan():
    import inspect
    from app.dashboards.hitting import layout
    src = inspect.getsource(layout.serve_layout)
    assert '"devplan"' in src and "Dev Plan" in src
```

- [ ] **Step 2: Run test** — `python -m pytest tests/test_hitting_dash.py -k "dev_plan_render or include_dev_plan" -q` → FAIL.

- [ ] **Step 3: Implement**

```python
# app/dashboards/hitting/tabs/dev_plan.py
"""Development Plan tab: per-player coach-authored plan (coach edits, player reads)."""
from __future__ import annotations

from dash import dcc, html

from app.data import dev_plans

_CRIMSON = "#9A0021"
_BOX = {"fontStyle": "italic", "padding": "10px 12px",
        "backgroundColor": "rgba(255,255,255,0.75)", "borderRadius": "8px"}


def _header():
    return html.Div("Development Plan", style={"color": _CRIMSON, "fontWeight": "bold",
                    "fontSize": "18px", "marginBottom": "6px"})


def render(subject_id, is_coach: bool) -> html.Div:
    if subject_id is None:
        return html.Div([_header(),
                         html.Div("Select a hitter.", style={**_BOX, "color": "#888"})])
    text = dev_plans.get_plan("hitting", subject_id)
    if not is_coach:
        return html.Div([_header(),
                         html.Div(text or "No development plan yet.", style=_BOX)])
    return html.Div([
        _header(),
        dcc.Textarea(id="devplan-text", value=text,
                     style={"width": "100%", "minHeight": "220px", "padding": "10px",
                            "borderRadius": "8px", "fontFamily": "Teko, sans-serif",
                            "fontSize": "16px"}),
        html.Div([
            html.Button("Save", id="devplan-save", n_clicks=0,
                        style={"background": _CRIMSON, "color": "#fff", "border": "none",
                               "borderRadius": "8px", "padding": "6px 18px",
                               "cursor": "pointer", "fontFamily": "Teko, sans-serif",
                               "marginRight": "8px"}),
            html.Button("Delete", id="devplan-delete", n_clicks=0,
                        style={"background": "#fff", "color": _CRIMSON,
                               "border": f"2px solid {_CRIMSON}", "borderRadius": "8px",
                               "padding": "5px 16px", "cursor": "pointer",
                               "fontFamily": "Teko, sans-serif"}),
            html.Span(id="devplan-status",
                      style={"marginLeft": "10px", "color": "#555", "fontSize": "14px"}),
        ], style={"marginTop": "8px"}),
    ], style={"padding": "10px 4px", "maxWidth": "820px"})
```

In `app/dashboards/hitting/layout.py`, add the tab after Last 27 PA:
```python
    tabs = dcc.Tabs(id="tabs", value="game", children=[
        dcc.Tab(label="Game Level", value="game"),
        dcc.Tab(label="Plate Appearances", value="pa"),
        dcc.Tab(label="Zone Location", value="zone"),
        dcc.Tab(label="Video", value="video"),
        dcc.Tab(label="Balls in Play", value="bip"),
        dcc.Tab(label="Last 27 PA", value="last27"),
        dcc.Tab(label="Dev Plan", value="devplan"),
    ])
```

In `app/dashboards/hitting/callbacks.py`:

(a) Add imports: `dev_plan` to the tabs import, and `dev_plans` from data:
```python
from app.dashboards.hitting.tabs import (game_level, plate_appearances as pa,
                                         zone_location as zl, balls_in_play, last_27,
                                         dev_plan)
from app.data import dev_plans
```
(`hitting_wh`, `video as videodata`, `current_user` are already imported — keep them.)

(b) Add a `devplan` branch at the TOP of `_render_tab` (uses `sel` + `current_user`):
```python
        if tab == "devplan":
            sel = sel or {}
            is_coach = bool(getattr(current_user, "is_coach", False))
            return dev_plan.render(sel.get("batter_id"), is_coach)
```

(c) Add two callbacks in `register_callbacks` (before the `videotab.register_callbacks`/`notes_ui.register_note_callbacks` lines):
```python
    @dash_app.callback(
        Output("devplan-status", "children"),
        Input("devplan-save", "n_clicks"),
        State("devplan-text", "value"), State("selection", "data"),
        prevent_initial_call=True,
    )
    def _devplan_save(_n, text, sel):
        if not getattr(current_user, "is_coach", False):
            return "Coaches only."
        sel = sel or {}
        bid = sel.get("batter_id")
        if bid is None:
            return ""
        dev_plans.upsert_plan("hitting", bid, text, getattr(current_user, "id", None))
        return "Saved." if (text or "").strip() else "Deleted."

    @dash_app.callback(
        Output("devplan-text", "value"),
        Output("devplan-status", "children", allow_duplicate=True),
        Input("devplan-delete", "n_clicks"), State("selection", "data"),
        prevent_initial_call=True,
    )
    def _devplan_delete(_n, sel):
        if not getattr(current_user, "is_coach", False):
            return "", "Coaches only."
        sel = sel or {}
        bid = sel.get("batter_id")
        if bid is not None:
            dev_plans.delete_plan("hitting", bid)
        return "", "Deleted."
```

- [ ] **Step 4: Run tests** — `python -m pytest tests/test_hitting_dash.py -q` → PASS.
- [ ] **Step 5: Commit**

```bash
git add app/dashboards/hitting/tabs/dev_plan.py app/dashboards/hitting/layout.py app/dashboards/hitting/callbacks.py tests/test_hitting_dash.py
git commit -m "feat(hitting): Development Plan tab (coach edits, player reads)"
```

---

### Task 3: Full-suite + live smoke

- [ ] **Step 1:** `python -m pytest -q` → all green.
- [ ] **Step 2: In-process smoke:**

```python
from app import create_app
from config import Config
class T(Config):
    TESTING = True; SECRET_KEY = "x"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
app = create_app(T)
with app.app_context():
    from app.data import dev_plans
    dev_plans.upsert_plan("hitting", 806253, "attack fastballs early", author_id=1)
    print("roundtrip:", dev_plans.get_plan("hitting", 806253))
from app.dashboards.hitting.tabs import dev_plan
print("coach render has textarea:", "devplan-text" in str(dev_plan.render(806253, True)))
print("player render read-only:", "devplan-text" not in str(dev_plan.render(806253, False)))
```
Expected: roundtrip text, coach render has the textarea, player render does not.

- [ ] **Step 3:** Commit any smoke fixes if needed.

## Notes for the implementer
- The `devplan` branch renders per-player and does not need game data, so it belongs at the top of `_render_tab` with the other `sel`-based branches (video/bip/last27), not among the df-based ones.
- `allow_duplicate=True` on the second `devplan-status` output is required because two callbacks write it (mirrors `notes_ui`).
- Do not add a coach-note card to this tab.
