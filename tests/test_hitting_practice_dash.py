"""Tests for HitTrax practice Dash module."""
import pandas as pd
import pytest

from app import create_app
from config import Config


@pytest.fixture
def server(tmp_path):
    class TestConfig(Config):
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 't.db'}"
    return create_app(TestConfig)


def _sample():
    return pd.DataFrame([
        {"player_name": "Doe, John", "session_id": 1, "result": 1,
         "px": 0.0, "py": 2.5, "exit_velocity": 90.0, "distance_feet": 250.0,
         "zone_section": 5, "play_timestamp": "2026-04-01 10:00:05",
         "play_date": "2026-04-01", "is_contact": True},
        {"player_name": "Doe, John", "session_id": 1, "result": -4,
         "px": 1.0, "py": 3.6, "exit_velocity": None, "distance_feet": None,
         "zone_section": 11, "play_timestamp": "2026-04-01 10:00:10",
         "play_date": "2026-04-01", "is_contact": False},
    ])


def test_build_hitting_practice_dash_mounts(server):
    rules = {r.rule for r in server.url_map.iter_rules()}
    assert any(r.startswith("/dash/hitting-practice/") for r in rules)


def test_pitch_zones_render():
    from app.dashboards.hitting_practice.tabs import pitch_zones
    assert pitch_zones.render(_sample()) is not None
    assert pitch_zones.render(pd.DataFrame()) is not None


def test_swing_frequency_render():
    from app.dashboards.hitting_practice.tabs import swing_frequency
    assert swing_frequency.render(_sample()) is not None


def test_contact_overview_render():
    from app.dashboards.hitting_practice.tabs import contact_overview
    stats = pd.DataFrame([{
        "player_name": "Doe, John", "total_plays": 10, "total_sessions": 2,
        "avg_exit_velocity": 88.0, "max_exit_velocity": 95.0,
        "avg_distance": 200.0, "hard_hit_rate": 0.3,
    }])
    plays = pd.DataFrame({"hit_type": [1, 2, 3], "session_id": [1, 1, 1],
                          "player_name": ["Doe, John"] * 3})
    assert contact_overview.render(plays, stats, player="All Players") is not None


def test_session_tables_render():
    from app.dashboards.hitting_practice.tabs import session_tables
    stats = pd.DataFrame([{
        "player_name": "Doe, John", "total_plays": 10, "total_sessions": 2,
        "avg_exit_velocity": 88.0, "max_exit_velocity": 95.0,
        "avg_distance": 200.0, "hard_hit_rate": 0.3,
        "line_drive_rate": 0.2, "fly_ball_rate": 0.25,
        "last_practice_date": "2026-04-01",
    }])
    sessions = pd.DataFrame([{
        "session_date": "2026-04-01", "player_name": "Doe, John",
        "total_plays": 10, "avg_exit_velocity": 88.0, "max_exit_velocity": 95.0,
        "avg_distance": 200.0, "batting_avg": 0.3, "hard_hit_count": 2,
        "ground_ball_pct": 40.0, "line_drive_pct": 30.0, "fly_ball_pct": 30.0,
    }])
    assert session_tables.render(stats, sessions, player="All Players") is not None


def test_player_options_coach():
    from app.dashboards.hitting_practice import selectors
    pitch = pd.DataFrame({"player_name": ["Alpha", "Beta"]})
    opts = selectors.player_options(pitch, is_coach=True, own_name=None)
    assert opts[0]["value"] == "All Players"
    assert {o["value"] for o in opts} >= {"Alpha", "Beta"}
