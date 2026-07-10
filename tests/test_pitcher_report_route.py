"""Tests for the pitcher postgame PDF download route (auth + role gating)."""
from unittest.mock import patch

import pytest

from app import create_app
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
        db.session.add(coach)
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
