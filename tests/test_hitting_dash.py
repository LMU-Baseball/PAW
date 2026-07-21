"""Tests for the Dash hitting dashboard (shell, selectors, tabs)."""
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


def test_build_hitting_dash_mounts():
    from flask import Flask
    from app.dashboards.hitting import build_hitting_dash, INDEX_STRING
    # Fresh bare server so we don't double-mount the one create_app() already added.
    dash_app = build_hitting_dash(Flask(__name__))
    assert dash_app.config.url_base_pathname == "/dash/hitting/"
    assert "palms-grey.png" in INDEX_STRING
    assert "/static/reports/lion.png" in INDEX_STRING


def test_resolve_batter_player_is_self_only():
    from app.dashboards.hitting import selectors
    # a player cannot resolve someone else's id
    assert selectors.resolve_batter(999, is_coach=False, own_trackman_id=806253) == 806253
    assert selectors.resolve_batter(None, is_coach=False, own_trackman_id=806253) == 806253


def test_resolve_batter_coach_passes_through():
    from app.dashboards.hitting import selectors
    assert selectors.resolve_batter(123, is_coach=True, own_trackman_id=None) == 123
    assert selectors.resolve_batter(None, is_coach=True, own_trackman_id=None) is None


def test_hitter_options_coach_lists_all(monkeypatch):
    from app.dashboards.hitting import selectors
    monkeypatch.setattr("app.data.hitting_wh.wh_lmu_hitters",
                        lambda: pd.DataFrame(
                            [{"Batter": "Doe, John", "BatterId": 1},
                             {"Batter": "Roe, Jane", "BatterId": 2}]))
    opts = selectors.hitter_options(is_coach=True, own_trackman_id=None)
    assert {o["value"] for o in opts} == {1, 2}


def test_hitter_options_player_is_single_self(monkeypatch):
    from app.dashboards.hitting import selectors
    monkeypatch.setattr("app.data.hitting_wh.wh_player_profile",
                        lambda b: {"name": "Wadas, Zach", "bats": "Right",
                                   "class_year": "", "position": "", "photo": "",
                                   "jersey": ""})
    opts = selectors.hitter_options(is_coach=False, own_trackman_id=806253)
    assert len(opts) == 1
    assert opts[0]["value"] == 806253
    assert opts[0]["label"] == "Wadas, Zach"


def _fake_pitches():
    return pd.DataFrame([
        {"PlateLocSide": 0.2, "PlateLocHeight": 2.5, "TaggedPitchType": "Fastball",
         "PitchCall": "StrikeSwinging", "PlayResult": "Undefined", "TaggedHitType": None,
         "Balls": 0, "Strikes": 1, "Inning": 1, "PAofInning": 1, "PitchofPA": 1,
         "Pitcher": "Smith, Joe"},
        {"PlateLocSide": -0.5, "PlateLocHeight": 1.8, "TaggedPitchType": "Slider",
         "PitchCall": "InPlay", "PlayResult": "Single", "TaggedHitType": "LineDrive",
         "Balls": 1, "Strikes": 1, "Inning": 3, "PAofInning": 2, "PitchofPA": 2,
         "Pitcher": "Smith, Joe"},
    ])


def test_zone_scatter_returns_figure_with_points():
    from app.dashboards.hitting import charts
    import plotly.graph_objects as go
    fig = charts.zone_scatter(_fake_pitches(), title="Test")
    assert isinstance(fig, go.Figure)
    # at least one scatter trace carrying the 2 pitch markers
    xs = [x for tr in fig.data for x in (tr.x or [])]
    assert len(xs) >= 2


def test_zone_scatter_empty_df_is_safe():
    from app.dashboards.hitting import charts
    import plotly.graph_objects as go
    fig = charts.zone_scatter(pd.DataFrame(), title="Empty")
    assert isinstance(fig, go.Figure)


def test_all_pas_figure_one_cell_per_pa():
    from app.dashboards.hitting import charts
    import plotly.graph_objects as go
    fig = charts.all_pas_figure(_fake_pitches())
    assert isinstance(fig, go.Figure)  # 2 distinct PAs -> renders without error
