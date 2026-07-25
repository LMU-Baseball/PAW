"""Tests for the shared note-card component."""
import pytest
from dash import dcc, html

from app import create_app
from config import Config


@pytest.fixture(autouse=True)
def _app_context(tmp_path):
    """_render_note touches app.data.notes (db.session), which needs an app
    context; provide one for every test in this module (same pattern as
    tests/test_notes.py and tests/test_hitting_dash.py)."""
    class TestConfig(Config):
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 't.db'}"
    app = create_app(TestConfig)
    with app.app_context():
        yield


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
