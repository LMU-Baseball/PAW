"""Tests for the app factory, login, and player/coach role access control."""
import os
import tempfile

import pytest

from app import create_app
from app.auth.access import can_view_player
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
        coach = User(email="coach@lmu.edu", name="Coach K", role="coach")
        coach.set_password("pw-coach")
        player = User(email="player@lmu.edu", name="Devan O", role="player",
                      trackman_id=694990)
        player.set_password("pw-player")
        db.session.add_all([coach, player])
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
def client(app):
    return app.test_client()


def _login(client, email, password):
    return client.post("/login", data={"email": email, "password": password},
                       follow_redirects=True)


# --------------------------- model / role logic ---------------------------

def test_password_hashing(app):
    with app.app_context():
        u = User(email="x@y.z", name="X", role="coach")
        u.set_password("secret")
        assert u.password_hash != "secret"
        assert u.check_password("secret")
        assert not u.check_password("wrong")


def test_coach_can_view_anyone(app):
    with app.app_context():
        coach = User.query.filter_by(email="coach@lmu.edu").first()
        assert coach.is_coach
        assert coach.can_view_player(694990)
        assert coach.can_view_player(111111)


def test_player_can_view_everyone(app):
    # Team-transparent model: a player VIEWS every player (edit stays coach-only).
    with app.app_context():
        player = User.query.filter_by(email="player@lmu.edu").first()
        assert not player.is_coach
        assert player.can_view_player(694990)          # own id
        assert player.can_view_player(111111)          # someone else -- now allowed
        assert player.can_view_player(None)


def test_can_view_player_helper_anonymous():
    class Anon:
        is_authenticated = False
    assert can_view_player(Anon(), 694990) is False


# --------------------------- auth flow ------------------------------------

def test_login_required_redirects(client):
    resp = client.get("/")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_login_success(client):
    resp = _login(client, "coach@lmu.edu", "pw-coach")
    assert resp.status_code == 200
    # Home hero greets the user; the name is wrapped in markup, so match the name.
    assert b"Coach K" in resp.data


def test_login_bad_password(client):
    resp = _login(client, "coach@lmu.edu", "nope")
    assert b"Invalid email or password." in resp.data


def test_logout(client):
    _login(client, "coach@lmu.edu", "pw-coach")
    resp = client.get("/logout", follow_redirects=True)
    assert resp.status_code == 200
    assert b"Sign in" in resp.data


def test_email_case_insensitive(client):
    resp = _login(client, "COACH@LMU.EDU", "pw-coach")
    assert b"Coach K" in resp.data


def test_open_redirect_blocked(client):
    # An absolute off-site 'next' must be ignored after login.
    resp = client.post("/login?next=https://evil.com",
                       data={"email": "coach@lmu.edu", "password": "pw-coach"})
    assert resp.status_code == 302
    assert "evil.com" not in resp.headers["Location"]


# --------------------------- dash protection ------------------------------

def test_dash_requires_login(client):
    resp = client.get("/dash/hitting/")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_dash_accessible_after_login(client):
    _login(client, "player@lmu.edu", "pw-player")
    resp = client.get("/dash/hitting/")
    assert resp.status_code == 200


# --------------------------- change password ------------------------------

def test_change_password_requires_login(client):
    resp = client.get("/change-password")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_change_password_wrong_current_rejected(client):
    _login(client, "coach@lmu.edu", "pw-coach")
    resp = client.post("/change-password", data={
        "current_password": "not-it", "new_password": "brand-new-pw",
        "confirm": "brand-new-pw"}, follow_redirects=True)
    assert b"Current password is incorrect." in resp.data


def test_change_password_mismatch_rejected(client):
    _login(client, "coach@lmu.edu", "pw-coach")
    resp = client.post("/change-password", data={
        "current_password": "pw-coach", "new_password": "brand-new-pw",
        "confirm": "different-pw"}, follow_redirects=True)
    assert b"Passwords must match." in resp.data


def test_change_password_success_updates_login(client):
    _login(client, "coach@lmu.edu", "pw-coach")
    resp = client.post("/change-password", data={
        "current_password": "pw-coach", "new_password": "brand-new-pw",
        "confirm": "brand-new-pw"}, follow_redirects=True)
    assert b"Password changed." in resp.data
    client.get("/logout")
    # old password no longer works; the new one does
    assert b"Invalid email or password." in _login(client, "coach@lmu.edu", "pw-coach").data
    assert b"Coach K" in _login(client, "coach@lmu.edu", "brand-new-pw").data
