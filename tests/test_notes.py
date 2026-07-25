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
