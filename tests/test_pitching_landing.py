"""Tests for the pitching-report landing page (game picker -> pitcher links)."""
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
        db.session.add(coach)
        db.session.commit()
    return app


def _login(client, email):
    return client.post("/login", data={"email": email, "password": "x"},
                       follow_redirects=True)


_GAMES = pd.DataFrame([
    {"game_id": 166, "game_date": "2026-05-10", "season_label": "Spring 2026",
     "game_type": "Conference", "home_team": "LMU", "away_team": "SMC"},
    {"game_id": 120, "game_date": "2026-04-01", "season_label": "Spring 2026",
     "game_type": "Conference", "home_team": "USD", "away_team": "LMU"},
])

_PITCHERS = pd.DataFrame([
    {"game_id": 166, "player_id": 1, "display_name": "Laine, Avery"},
    {"game_id": 166, "player_id": 2, "display_name": "Proskey, Calvin"},
])


def test_anonymous_redirects(app_ctx):
    resp = app_ctx.test_client().get("/reports/pitching")
    assert resp.status_code in (302, 401)


def test_landing_lists_games(app_ctx, monkeypatch):
    monkeypatch.setattr("app.data.pitching.recent_games", lambda limit=25: _GAMES)
    client = app_ctx.test_client()
    _login(client, "c@lmu.edu")
    resp = client.get("/reports/pitching")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'name="game_id"' in body      # the picker control
    assert "SMC" in body and "USD" in body  # both games offered


def test_landing_shows_pitchers_and_download_links(app_ctx, monkeypatch):
    monkeypatch.setattr("app.data.pitching.recent_games", lambda limit=25: _GAMES)
    monkeypatch.setattr("app.data.pitching.pitchers_for_game",
                        lambda gid: _PITCHERS)
    client = app_ctx.test_client()
    _login(client, "c@lmu.edu")
    resp = client.get("/reports/pitching?game_id=166")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Laine, Avery" in body
    assert "Proskey, Calvin" in body
    # a working link to the existing PDF route for each pitcher
    assert "/reports/pitcher/166/1.pdf" in body
    assert "/reports/pitcher/166/2.pdf" in body
