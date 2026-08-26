"""Tests for the bullpen-report landing page + team-transparent view gate."""
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
        lambda start=None, end=None: pd.DataFrame(
            [{"pitcher_id": 824645, "pitcher": "Geis, Jake",
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
    assert 'name="season"' in body   # season selector rendered


def test_bullpen_pdf_player_can_view_any(app_ctx):
    """Team-transparent: a player may download ANY pitcher's bullpen report
    (the view gate is open; write access to boards/notes stays coach-only)."""
    from unittest.mock import patch
    client = app_ctx.test_client()
    _login(client, "p@lmu.edu")
    with patch("app.reports.routes.build_bullpen_report", return_value=b"%PDF-mock"):
        resp = client.get("/reports/bullpen/999999/2025-02-06.pdf")
    assert resp.status_code == 200
    assert resp.data.startswith(b"%PDF-")


def test_bullpen_landing_player_sees_all(app_ctx, monkeypatch):
    """Team-transparent: a player sees the FULL pitcher list (everyone)."""
    monkeypatch.setattr(
        "app.data.bullpen.lmu_bullpen_pitchers",
        lambda start=None, end=None: pd.DataFrame([
            {"pitcher_id": 824645, "pitcher": "Geis, Jake", "sessions": 13,
             "last_date": "2025-02-06"},
            {"pitcher_id": 111111, "pitcher": "Other, Guy", "sessions": 5,
             "last_date": "2025-01-01"}]))
    monkeypatch.setattr("app.data.bullpen.bullpen_data_max_date", lambda: "2025-04-14")
    client = app_ctx.test_client()
    _login(client, "p@lmu.edu")
    body = client.get("/reports/bullpen").get_data(as_text=True)
    assert "Geis, Jake" in body        # sees self
    assert "Other, Guy" in body        # AND every other pitcher


def test_bullpen_landing_scopes_pitcher_list_to_selected_season(app_ctx, monkeypatch):
    """The Season dropdown passes that season's date bounds to the pitcher query,
    and defaults to the current season."""
    from app.data import seasons
    calls = []

    def fake(start=None, end=None):
        calls.append((start, end))
        return pd.DataFrame([{"pitcher_id": 824645, "pitcher": "Geis, Jake",
                              "sessions": 13, "last_date": "2025-02-06"}])

    monkeypatch.setattr("app.data.bullpen.lmu_bullpen_pitchers", fake)
    monkeypatch.setattr("app.data.bullpen.bullpen_data_max_date", lambda: "2025-04-14")
    client = app_ctx.test_client()
    _login(client, "c@lmu.edu")
    with app_ctx.app_context():
        cur = seasons.current_season()
        cur_bounds = seasons.season_bounds(cur)
        others = [s for s in seasons.available_seasons() if s < cur]

    # Default (no season param) -> current season's bounds.
    resp = client.get("/reports/bullpen")
    assert resp.status_code == 200
    assert cur_bounds in calls
    body = resp.get_data(as_text=True)
    assert f'value="{cur}" selected' in body or (f'value="{cur}"' in body and "selected" in body)

    # Explicit season param -> that season's bounds.
    if others:
        other = others[0]
        with app_ctx.app_context():
            other_bounds = seasons.season_bounds(other)
        calls.clear()
        r2 = client.get(f"/reports/bullpen?season={other}")
        assert r2.status_code == 200
        assert other_bounds in calls
