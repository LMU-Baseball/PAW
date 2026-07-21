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
