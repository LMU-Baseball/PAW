"""`flask roster-reconcile` CLI command."""
import os
import tempfile

from click.testing import CliRunner

from app import create_app
from config import Config


def _test_app():
    """Mirrors tests/test_auth.py's `app` fixture: a real create_app() with the
    AUTH db pointed at a throwaway sqlite file (ANALYTICS_DB_URL is untouched,
    so lmu_roster.reconcile_ids -- monkeypatched below anyway -- would still
    resolve against the real analytics DB if it weren't mocked)."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    class TestConfig(Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = "sqlite:///" + path.replace("\\", "/")

    return create_app(TestConfig)


def test_roster_reconcile_command_runs_and_reports_count(monkeypatch):
    from app.data import lmu_roster
    monkeypatch.setattr(lmu_roster, "reconcile_ids", lambda season, engine=None: 3)
    app = _test_app()
    runner = CliRunner()
    result = runner.invoke(app.cli, ["roster-reconcile", "--season", "1899/1900"])
    assert result.exit_code == 0
    assert "1899/1900" in result.output
    assert "3" in result.output
