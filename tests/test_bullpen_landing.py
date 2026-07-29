"""Tests for the bullpen-report landing page + self-only PDF gate."""
import pandas as pd
import pytest

from app import create_app
from app.extensions import db
from app.auth.models import User
from config import Config


@pytest.fixture
def app_ctx(tmp_path):
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
                      trackman_id="824645")  # matches Geis's bullpen PitcherId
        player.set_password("x")
        db.session.add_all([coach, player])
        db.session.commit()
    return app


def _login(client, email):
    return client.post("/login", data={"email": email, "password": "x"},
                       follow_redirects=True)


def test_anonymous_redirects(app_ctx):
    resp = app_ctx.test_client().get("/reports/bullpen")
    assert resp.status_code in (302, 401)


def test_bullpen_landing_ok_for_coach(app_ctx, monkeypatch):
    monkeypatch.setattr(
        "app.data.bullpen.lmu_bullpen_pitchers",
        lambda: pd.DataFrame([{"pitcher_id": 824645, "pitcher": "Geis, Jake",
                               "sessions": 13, "last_date": "2025-02-06"}]))
    monkeypatch.setattr("app.data.bullpen.bullpen_data_max_date",
                        lambda: "2025-04-14")
    client = app_ctx.test_client()
    _login(client, "c@lmu.edu")
    resp = client.get("/reports/bullpen")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Bullpen" in body and "Geis, Jake" in body
    assert "2025-04-14" in body   # stale-data banner


def test_bullpen_pdf_player_self_only(app_ctx):
    """A player requesting another pitcher's bullpen is forbidden (gate before build)."""
    client = app_ctx.test_client()
    _login(client, "p@lmu.edu")
    resp = client.get("/reports/bullpen/999999/2025-02-06.pdf")
    assert resp.status_code == 403


def test_bullpen_landing_player_sees_only_self(app_ctx, monkeypatch):
    """A player's pitcher list is filtered to themselves — no enumeration leak."""
    monkeypatch.setattr(
        "app.data.bullpen.lmu_bullpen_pitchers",
        lambda: pd.DataFrame([
            {"pitcher_id": 824645, "pitcher": "Geis, Jake", "sessions": 13,
             "last_date": "2025-02-06"},
            {"pitcher_id": 111111, "pitcher": "Other, Guy", "sessions": 5,
             "last_date": "2025-01-01"}]))
    monkeypatch.setattr("app.data.bullpen.bullpen_data_max_date", lambda: "2025-04-14")
    client = app_ctx.test_client()
    _login(client, "p@lmu.edu")  # trackman_id 824645 == Geis
    body = client.get("/reports/bullpen").get_data(as_text=True)
    assert "Geis, Jake" in body        # sees self
    assert "Other, Guy" not in body    # does NOT see other pitchers
