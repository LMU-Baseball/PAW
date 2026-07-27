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
