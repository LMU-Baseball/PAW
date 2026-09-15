"""Tests for the `flask set-trackman-id` user-management CLI command."""
import os
import tempfile

import pytest

from app import create_app
from app.auth.models import User
from app.extensions import db
from config import Config


@pytest.fixture()
def app():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = "sqlite:///" + path.replace("\\", "/")

    application = create_app(TestConfig)
    with application.app_context():
        user = User(email="player@lmu.edu", name="Devan O", role="player")
        user.set_password("pw-player")
        db.session.add(user)
        db.session.commit()

    yield application

    with application.app_context():
        db.session.remove()
        db.engine.dispose()
    try:
        os.remove(path)
    except PermissionError:
        pass  # Windows may still hold the handle briefly; temp file is harmless


@pytest.fixture()
def runner(app):
    return app.test_cli_runner()


def test_set_trackman_id_updates_existing_user(app, runner):
    result = runner.invoke(args=["set-trackman-id", "--email", "player@lmu.edu",
                                 "--trackman-id", "694990"])
    assert result.exit_code == 0
    assert "Linked player@lmu.edu -> trackman_id 694990." in result.output
    with app.app_context():
        user = User.query.filter_by(email="player@lmu.edu").first()
        assert user.trackman_id == 694990


def test_set_trackman_id_missing_user_errors(runner):
    result = runner.invoke(args=["set-trackman-id", "--email", "nobody@lmu.edu",
                                 "--trackman-id", "1"])
    assert result.exit_code != 0
    assert "No user with email: nobody@lmu.edu" in result.output


def test_set_role_updates_existing_user(app, runner):
    result = runner.invoke(args=["set-role", "--email", "player@lmu.edu", "--role", "coach"])
    assert result.exit_code == 0
    assert "Set player@lmu.edu role to coach." in result.output
    with app.app_context():
        assert User.query.filter_by(email="player@lmu.edu").first().role == "coach"


def test_set_role_missing_user_errors(runner):
    result = runner.invoke(args=["set-role", "--email", "nobody@lmu.edu", "--role", "coach"])
    assert result.exit_code != 0
    assert "No user with email: nobody@lmu.edu" in result.output


def test_set_active_can_deactivate_and_reactivate(app, runner):
    result = runner.invoke(args=["set-active", "--email", "player@lmu.edu", "--inactive"])
    assert result.exit_code == 0
    assert "Account deactivated: player@lmu.edu." in result.output
    with app.app_context():
        assert User.query.filter_by(email="player@lmu.edu").first().is_active is False

    result = runner.invoke(args=["set-active", "--email", "player@lmu.edu", "--active"])
    assert result.exit_code == 0
    assert "Account activated: player@lmu.edu." in result.output
    with app.app_context():
        assert User.query.filter_by(email="player@lmu.edu").first().is_active is True


def test_set_active_missing_user_errors(runner):
    result = runner.invoke(args=["set-active", "--email", "nobody@lmu.edu", "--active"])
    assert result.exit_code != 0
    assert "No user with email: nobody@lmu.edu" in result.output
