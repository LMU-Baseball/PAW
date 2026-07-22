"""Tests for the Dash pitching dashboard (shell, selectors, build)."""
import pandas as pd
import pytest

from app import create_app
from app.data import pitching as P
from app.db import query_df
from config import Config


@pytest.fixture(scope="module")
def real_pitcher():
    df = query_df(
        """
        SELECT pitcher_id FROM fact_tm_game_pitch
         WHERE pitcher_team = 'LOY_LIO' AND pitcher_id IS NOT NULL
         GROUP BY pitcher_id ORDER BY COUNT(*) DESC LIMIT 1
        """
    )
    return int(df.loc[0, "pitcher_id"])


@pytest.fixture
def server(tmp_path):
    class TestConfig(Config):
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 't.db'}"
    return create_app(TestConfig)


def test_resolve_pitcher_player_is_self_only():
    from app.dashboards.pitching import selectors
    # A player ignores the requested id and gets their own.
    assert selectors.resolve_pitcher(999, is_coach=False, own_trackman_id=None) is None
    assert selectors.resolve_pitcher(999, is_coach=True, own_trackman_id=None) == 999


def test_pitcher_options_coach_nonempty():
    from app.dashboards.pitching import selectors
    opts = selectors.pitcher_options(is_coach=True, own_trackman_id=None)
    assert opts and {"label", "value"} <= set(opts[0])


def test_outing_options_for_real_pitcher(real_pitcher):
    from app.dashboards.pitching import selectors
    opts = selectors.outing_options(real_pitcher)
    assert opts and {"label", "value"} <= set(opts[0])


def test_build_pitching_dash_mounts(server):
    # The dashboard registers at /dash/pitching/ during create_app.
    rules = {r.rule for r in server.url_map.iter_rules()}
    assert any(r.startswith("/dash/pitching/") for r in rules)
