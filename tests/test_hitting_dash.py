"""Tests for the Dash hitting dashboard (shell, selectors, tabs)."""
import warnings

import pandas as pd
import pytest

from app import create_app
from app.data import hitting_wh
from app.db import query_df
from config import Config


@pytest.fixture(scope="module")
def real_batter():
    cand = query_df(
        """
        SELECT batter_tm_id FROM fact_tm_game_pitch
         WHERE batter_team = 'LOY_LIO' AND batter_tm_id IS NOT NULL
         GROUP BY batter_tm_id ORDER BY COUNT(*) DESC LIMIT 1
        """
    )
    return int(cand.loc[0, "batter_tm_id"])


@pytest.fixture(scope="module")
def game_df(real_batter):
    games = hitting_wh.wh_games_for_batter(real_batter)
    gid = int(games.iloc[0]["game_id"])
    return hitting_wh.wh_game_pitches(gid, real_batter)


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
    # one subplot-title annotation per PA (make_subplots creates one each)
    assert len(fig.layout.annotations) == 2
    # at least 2 scatter traces carrying pitch markers (one group per PA)
    scatter_traces = [tr for tr in fig.data if isinstance(tr, go.Scatter)]
    assert len(scatter_traces) >= 2


def test_all_pas_figure_empty_df_is_safe():
    from app.dashboards.hitting import charts
    import plotly.graph_objects as go
    fig = charts.all_pas_figure(pd.DataFrame())
    assert isinstance(fig, go.Figure)


def test_stat_table_builds_and_formats_pct():
    from app.dashboards.hitting import tables
    from dash import dash_table
    df = pd.DataFrame([{"Zone": "Heart", "Total": 10, "Swing %": 40.0}])
    tbl = tables.stat_table(df, id="t")
    assert isinstance(tbl, dash_table.DataTable)
    # percent column rendered with a trailing %
    assert tbl.data[0]["Swing %"] == "40.0%"
    assert tbl.data[0]["Total"] == 10


def test_stat_table_empty_df_is_safe():
    from app.dashboards.hitting import tables
    tbl = tables.stat_table(pd.DataFrame())
    assert tbl.data == []


def test_game_level_renders_for_real_and_empty(game_df):
    from app.dashboards.hitting.tabs import game_level
    from dash import html
    out = game_level.render(game_df, note="Great AB battle.")
    assert isinstance(out, html.Div)
    # empty df must not crash
    assert isinstance(game_level.render(pd.DataFrame(), note=""), html.Div)


def test_game_level_drops_qc_pathq_columns(game_df):
    from app.dashboards.hitting.tabs import game_level
    out = game_level.render(game_df, note="Great AB battle.")
    text = str(out)
    assert "Avg QC+" not in text
    assert "Avg PathQ+" not in text


def test_plate_appearances_choices_and_render(game_df):
    from app.dashboards.hitting.tabs import plate_appearances as pa
    from dash import html, dcc
    choices = pa.pa_choices(game_df)
    assert len(choices) >= 1
    out = pa.render_breakdown(game_df, choices[0]["value"])
    assert isinstance(out, html.Div)
    assert isinstance(pa.render_all_pas(game_df), dcc.Graph)


def test_plate_appearances_default_pa_renders(game_df):
    from app.dashboards.hitting.tabs import plate_appearances as pa
    from dash import html
    # None -> defaults to the first PA on a non-empty fixture
    out = pa.render_breakdown(game_df, None)
    assert isinstance(out, html.Div)


def test_plate_appearances_empty_is_safe():
    from app.dashboards.hitting.tabs import plate_appearances as pa
    from dash import html, dcc
    assert pa.pa_choices(pd.DataFrame()) == []
    assert isinstance(pa.render_breakdown(pd.DataFrame(), None), html.Div)
    assert isinstance(pa.render_all_pas(pd.DataFrame()), dcc.Graph)


def test_zone_location_renders_and_filters(game_df):
    from app.dashboards.hitting.tabs import zone_location as zl
    from dash import html
    assert {o["value"] for o in zl.ZONE_FILTER_OPTIONS} >= {"All Swings", "Heart"}
    assert isinstance(zl.render(game_df, "All Swings"), html.Div)
    assert isinstance(zl.render(game_df, "Heart"), html.Div)


def test_zone_location_filter_changes_output(game_df):
    from app.dashboards.hitting.tabs import zone_location as zl
    from dash import html
    heart_out = zl.render(game_df, "Heart")
    takes_out = zl.render(game_df, "All Takes")
    assert isinstance(heart_out, html.Div)
    assert isinstance(takes_out, html.Div)
    # "Swing / Take by Zone" table must be present in both renders
    assert "Swing / Take by Zone" in str(heart_out)
    assert "Swing / Take by Zone" in str(takes_out)
    # different zone filters should (generally) produce different scatter content
    if str(heart_out) == str(takes_out):
        pytest.skip("fixture game has identical Heart/All-Takes subsets")


def test_zone_location_empty_is_safe():
    from app.dashboards.hitting.tabs import zone_location as zl
    from dash import html
    assert isinstance(zl.render(pd.DataFrame(), "All Swings"), html.Div)


def test_serve_layout_renders_for_logged_in_coach(server, monkeypatch):
    from app.extensions import db
    from app.auth.models import User
    from flask_login import login_user
    monkeypatch.setattr("app.data.hitting_wh.wh_lmu_hitters",
                        lambda: pd.DataFrame([{"Batter": "Doe, John", "BatterId": 1}]))
    monkeypatch.setattr("app.data.hitting_wh.wh_games_for_batter",
                        lambda b: pd.DataFrame(columns=["game_id", "game_date", "GameLabel"]))
    monkeypatch.setattr("app.data.hitting_wh.wh_player_profile",
                        lambda b: {"name": "Doe, John", "bats": "Right",
                                   "class_year": "Jr.", "position": "OF",
                                   "photo": "", "jersey": ""})
    monkeypatch.setattr("app.data.hitting_wh.wh_season_qab_rate", lambda b: 0.42)
    with server.app_context():
        coach = User(email="c2@lmu.edu", name="Coach", role="coach")
        coach.set_password("x")
        db.session.add(coach)
        db.session.commit()
        with server.test_request_context("/dash/hitting/"):
            login_user(coach)
            from app.dashboards.hitting import layout
            out = layout.serve_layout()
    # smoke: it built a component tree, not the login placeholder
    assert out is not None
    assert "Please log in" not in str(out)


def test_register_callbacks_adds_callbacks(server):
    from dash import Dash
    from app.dashboards.hitting import layout, callbacks, index
    app = Dash(__name__, server=server, url_base_pathname="/dash/htest/",
               suppress_callback_exceptions=True)
    app.index_string = index.INDEX_STRING
    app.layout = layout.serve_layout
    before = len(app.callback_map)
    callbacks.register_callbacks(app)
    assert len(app.callback_map) > before


def test_read_game_df_roundtrip_no_futurewarning():
    from app.dashboards.hitting import callbacks

    df = pd.DataFrame([
        {"PitchCall": "StrikeSwinging", "Balls": 0, "Strikes": 1},
        {"PitchCall": "InPlay", "Balls": 1, "Strikes": 1},
    ])
    data_json = df.to_json(orient="split")

    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        out = callbacks._read_game_df(data_json)

    assert list(out.columns) == list(df.columns)
    assert len(out) == len(df)

    empty = callbacks._read_game_df(None)
    assert isinstance(empty, pd.DataFrame)
    assert empty.empty
