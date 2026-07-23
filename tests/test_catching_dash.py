"""Tests for the Dash catching dashboard (shell, selectors, tab renders)."""
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


def _sample_df():
    return pd.DataFrame([
        {"pitch_call": "StrikeCalled", "play_result": "Undefined",
         "plate_loc_side": 0.0, "plate_loc_height": 2.5,
         "inning": 1, "balls": 0, "strikes": 0, "pitcher_name": "A, B",
         "pop_time": None, "exchange_time": None, "throw_speed": None},
        {"pitch_call": "BallinDirt", "play_result": "Undefined",
         "plate_loc_side": 0.1, "plate_loc_height": 0.8,
         "inning": 3, "balls": 0, "strikes": 2, "pitcher_name": "A, B",
         "pop_time": None, "exchange_time": None, "throw_speed": None},
        {"pitch_call": "InPlay", "play_result": "CaughtStealing",
         "plate_loc_side": -0.2, "plate_loc_height": 2.1,
         "inning": 6, "balls": 1, "strikes": 1, "pitcher_name": "A, B",
         "pop_time": 1.88, "exchange_time": 0.68, "throw_speed": 80.0},
    ])


def test_resolve_catcher_player_is_self_only():
    from app.dashboards.catching import selectors
    assert selectors.resolve_catcher(999, is_coach=False, own_trackman_id=None) is None
    assert selectors.resolve_catcher(999, is_coach=True, own_trackman_id=None) == 999


def test_resolve_catcher_player_discards_requested_id(monkeypatch):
    from app.dashboards.catching import selectors
    monkeypatch.setattr(selectors, "_catcher_id_for_tm", lambda tm: 4242)
    got = selectors.resolve_catcher(999, is_coach=False, own_trackman_id=555)
    assert got == 4242


def test_catcher_options_coach(monkeypatch):
    from app.dashboards.catching import selectors
    monkeypatch.setattr(
        "app.data.catching.wh_lmu_catchers",
        lambda: pd.DataFrame([{"Catcher": "Doe, John", "CatcherId": 1},
                              {"Catcher": "Roe, Jane", "CatcherId": 2}]),
    )
    opts = selectors.catcher_options(is_coach=True, own_trackman_id=None)
    assert {o["value"] for o in opts} == {1, 2}


def test_build_catching_dash_mounts(server):
    rules = {r.rule for r in server.url_map.iter_rules()}
    assert any(r.startswith("/dash/catching/") for r in rules)


def test_framing_tab_render():
    from app.dashboards.catching.tabs import framing
    assert framing.render(_sample_df()) is not None
    assert framing.render(pd.DataFrame()) is not None


def test_blocking_tab_render():
    from app.dashboards.catching.tabs import blocking
    assert blocking.render(_sample_df()) is not None
    assert blocking.render(pd.DataFrame()) is not None


def test_throws_tab_render():
    from app.dashboards.catching.tabs import throws
    assert throws.render(_sample_df()) is not None
    assert throws.render(pd.DataFrame()) is not None


def test_framing_scatter_returns_figure():
    from app.dashboards.catching import charts
    fig = charts.framing_scatter(_sample_df())
    assert fig is not None
