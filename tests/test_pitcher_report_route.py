"""Tests for the pitcher postgame PDF download route (auth + role gating)."""
from unittest.mock import patch

import pytest

from app import create_app
from app.auth.access import can_view_pitcher_report
from app.extensions import db
from app.auth.models import User
from config import Config


@pytest.fixture
def app_ctx(tmp_path):
    # NOTE: create_app() calls db.create_all() against the *default* config
    # (instance/paw_app.db) as its very last step, before we could override
    # SQLALCHEMY_DATABASE_URI via app.config.update() -- flask-sqlalchemy
    # then caches an engine bound to that default URI for this app object,
    # so a later config.update() would silently be ignored (and tests would
    # leak state into the real app DB across runs). Passing a TestConfig
    # subclass into create_app() up front, as tests/test_auth.py does,
    # avoids that.
    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 't.db'}"

    app = create_app(TestConfig)
    with app.app_context():
        coach = User(email="c@lmu.edu", name="Coach C", role="coach")
        coach.set_password("x")
        player = User(email="p@lmu.edu", name="Player P", role="player",
                      trackman_id=694990)
        player.set_password("x")
        db.session.add_all([coach, player])
        db.session.commit()
    return app


def _login(client, email):
    # NOTE: auth_bp is registered with no url_prefix, so the login route is
    # "/login", not "/auth/login".
    return client.post("/login", data={"email": email, "password": "x"},
                       follow_redirects=True)


def test_anonymous_gets_401_or_redirect(app_ctx):
    client = app_ctx.test_client()
    resp = client.get("/reports/pitcher/166/1.pdf")
    assert resp.status_code in (302, 401)


def test_coach_gets_pdf(app_ctx):
    client = app_ctx.test_client()
    _login(client, "c@lmu.edu")
    with patch("app.reports.routes.build_pitcher_postgame", return_value=b"%PDF-mock"):
        resp = client.get("/reports/pitcher/166/1.pdf")
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    assert resp.data.startswith(b"%PDF-")


# --------------------------- can_view_pitcher_report unit tests ------------

class _StubUser:
    """Minimal stand-in for the attributes can_view_pitcher_report reads."""
    def __init__(self, is_authenticated=True, role="player", trackman_id=None):
        self.is_authenticated = is_authenticated
        self.role = role
        self.trackman_id = trackman_id


# NOTE: can_view_pitcher_report imports pitcher_tm_id_for *inside* the function
# body (`from app.data.pitching import pitcher_tm_id_for`), so the name is
# resolved from app.data.pitching at call time -- that is the correct patch
# target (patching app.auth.access.pitcher_tm_id_for would have no effect,
# since no such module-level name exists there).
def test_can_view_anonymous_is_false():
    assert can_view_pitcher_report(_StubUser(is_authenticated=False), 1) is False


def test_can_view_coach_is_true_without_db(monkeypatch):
    def _boom(pid):  # pragma: no cover - must never be called for a coach
        raise AssertionError("coach path must not hit the warehouse")
    monkeypatch.setattr("app.data.pitching.pitcher_tm_id_for", _boom)
    assert can_view_pitcher_report(_StubUser(role="coach"), 1) is True


def test_can_view_player_matching_id_is_true(monkeypatch):
    monkeypatch.setattr("app.data.pitching.pitcher_tm_id_for", lambda pid: 694990)
    assert can_view_pitcher_report(
        _StubUser(role="player", trackman_id=694990), 1) is True


def test_can_view_player_matching_id_str_int_coerces(monkeypatch):
    # trackman_id stored as int, tm_id looked up as str (or vice versa) -- the
    # str()-cast comparison must still match.
    monkeypatch.setattr("app.data.pitching.pitcher_tm_id_for", lambda pid: "694990")
    assert can_view_pitcher_report(
        _StubUser(role="player", trackman_id=694990), 1) is True


def test_can_view_player_mismatched_id_is_false(monkeypatch):
    monkeypatch.setattr("app.data.pitching.pitcher_tm_id_for", lambda pid: 111111)
    assert can_view_pitcher_report(
        _StubUser(role="player", trackman_id=694990), 1) is False


def test_can_view_player_no_tm_id_is_false(monkeypatch):
    monkeypatch.setattr("app.data.pitching.pitcher_tm_id_for", lambda pid: None)
    assert can_view_pitcher_report(
        _StubUser(role="player", trackman_id=694990), 1) is False


# --------------------------- route-level player gating ---------------------

def test_player_gets_403_for_other_pitcher(app_ctx, monkeypatch):
    # Player's trackman_id is 694990; this pitcher maps to a different tm id.
    monkeypatch.setattr("app.data.pitching.pitcher_tm_id_for", lambda pid: 111111)
    client = app_ctx.test_client()
    _login(client, "p@lmu.edu")
    with patch("app.reports.routes.build_pitcher_postgame", return_value=b"%PDF-mock"):
        resp = client.get("/reports/pitcher/166/1.pdf")
    assert resp.status_code == 403


def test_player_gets_pdf_for_own_pitcher(app_ctx, monkeypatch):
    # This pitcher maps to the player's own trackman_id -> allowed.
    monkeypatch.setattr("app.data.pitching.pitcher_tm_id_for", lambda pid: 694990)
    client = app_ctx.test_client()
    _login(client, "p@lmu.edu")
    with patch("app.reports.routes.build_pitcher_postgame", return_value=b"%PDF-mock"):
        resp = client.get("/reports/pitcher/166/1.pdf")
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    assert resp.data.startswith(b"%PDF-")
