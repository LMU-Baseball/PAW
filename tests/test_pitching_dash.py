"""Tests for the Dash pitching dashboard (shell, selectors, build)."""
import pytest

from app import create_app
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


def test_resolve_pitcher_player_discards_requested_id(monkeypatch):
    from app.dashboards.pitching import selectors
    monkeypatch.setattr(selectors, "_pitcher_id_for_tm", lambda tm: 4242)
    got = selectors.resolve_pitcher(999, is_coach=False, own_trackman_id=555)
    assert got == 4242  # own id, NOT the requested 999


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


@pytest.fixture(scope="module")
def outing_df(real_pitcher):
    from app.data import pitching as P
    g = P.games_for_pitcher(real_pitcher)
    gid = int(g.iloc[0]["game_id"])
    return P.game_pitches(gid, real_pitcher)


def test_pitch_breakdown_render(outing_df):
    from app.dashboards.pitching.tabs import pitch_breakdown
    comp = pitch_breakdown.render(outing_df)
    assert comp is not None  # renders without raising on real data


def test_location_movement_render(outing_df):
    from app.dashboards.pitching.tabs import location_movement
    assert location_movement.render(outing_df) is not None


def test_rhh_lhh_render(outing_df):
    from app.dashboards.pitching.tabs import rhh_lhh
    assert rhh_lhh.render(outing_df) is not None


def test_last_outings_render(real_pitcher):
    from app.data import pitching as P
    from app.dashboards.pitching.tabs import last_outings
    gid = int(P.games_for_pitcher(real_pitcher).iloc[0]["game_id"])
    assert last_outings.render(real_pitcher, gid, 5) is not None
