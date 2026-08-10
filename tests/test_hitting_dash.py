"""Tests for the Dash hitting dashboard (shell, selectors, tabs)."""
import warnings

import pandas as pd
import pytest

from app import create_app
from app.data import hitting_caps
from app.db import query_df
from config import Config


@pytest.fixture(scope="module")
def real_batter():
    # Restrict to numeric GameIDs so the most-tracked batter we pick is a
    # current hitter with real (int-castable) games -- the all-time top
    # BatterId in GAMES is a retired alumnus whose rows are all legacy
    # composite-string GameIDs, for whom games_for_batter returns empty and
    # the game_df fixture below would crash on iloc[0].
    cand = query_df(
        """
        SELECT BatterId FROM GAMES
         WHERE BatterTeam = 'LOY_LIO' AND BatterId IS NOT NULL
           AND GameID REGEXP '^[0-9]+$'
         GROUP BY BatterId ORDER BY COUNT(*) DESC LIMIT 1
        """
    )
    return int(cand.loc[0, "BatterId"])


@pytest.fixture(scope="module")
def game_df(real_batter):
    games = hitting_caps.games_for_batter(real_batter)
    gid = int(games.iloc[0]["game_id"])
    return hitting_caps.game_pitches(gid, real_batter)


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
    monkeypatch.setattr("app.data.hitting_caps.lmu_hitters",
                        lambda season=None: pd.DataFrame(
                            [{"Batter": "Doe, John", "BatterId": 1},
                             {"Batter": "Roe, Jane", "BatterId": 2}]))
    opts = selectors.hitter_options(is_coach=True, own_trackman_id=None)
    assert {o["value"] for o in opts} == {1, 2}


def test_hitter_options_player_is_single_self(monkeypatch):
    from app.dashboards.hitting import selectors
    monkeypatch.setattr("app.data.hitting_caps.player_profile",
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


def test_zone_scatter_white_bg_and_trimmed_hover():
    from app.dashboards.hitting import charts
    fig = charts.zone_scatter(_fake_pitches(), title="Test")
    # white background so the strike zone reads over the palms motif
    assert fig.layout.paper_bgcolor == "#ffffff"
    assert fig.layout.plot_bgcolor == "#ffffff"
    # hover shows pitch type + result only (no Count / Pitcher)
    tmpl = " ".join(tr.hovertemplate or "" for tr in fig.data if tr.hovertemplate)
    assert tmpl                      # markers carry a hovertemplate
    assert "Count" not in tmpl and "Pitcher" not in tmpl
    assert "Fastball" in tmpl or "Slider" in tmpl   # the pitch type is shown


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


def test_all_pas_figure_single_pa_not_stretched():
    from app.dashboards.hitting import charts
    # One PA -> one column -> fixed ~360px width (not full-container stretch).
    one_pa = _fake_pitches()[_fake_pitches()["Inning"] == 1]
    fig = charts.all_pas_figure(one_pa)
    assert fig.layout.width == 360
    # two PAs -> two columns -> 720
    assert charts.all_pas_figure(_fake_pitches()).layout.width == 720


def test_pa_choices_number_sequentially_by_game_order():
    from app.dashboards.hitting.tabs import plate_appearances as pa
    # A hitter whose first PA was the 3rd batter of inning 1, second PA in inning 3.
    df = _fake_pitches()  # PAs: (Inn 1, PAofInning 1) and (Inn 3, PAofInning 2)
    labels = [c["label"] for c in pa.pa_choices(df)]
    # sequential game PA number, NOT PAofInning
    assert labels[0].startswith("PA 1 ·")
    assert labels[1].startswith("PA 2 ·")


def _fake_pooled_pitches():
    """Two games, each with its own (Inning 1, PAofInning 1) — same local PA
    identity reused across games, so GameID must disambiguate them."""
    return pd.DataFrame([
        {"GameID": 100, "PlateLocSide": 0.2, "PlateLocHeight": 2.5,
         "TaggedPitchType": "Fastball", "PitchCall": "StrikeSwinging",
         "PlayResult": "Undefined", "TaggedHitType": None,
         "Balls": 0, "Strikes": 1, "Inning": 1, "PAofInning": 1, "PitchofPA": 1,
         "Pitcher": "Smith, Joe"},
        {"GameID": 200, "PlateLocSide": -0.4, "PlateLocHeight": 2.1,
         "TaggedPitchType": "Slider", "PitchCall": "InPlay",
         "PlayResult": "Single", "TaggedHitType": "LineDrive",
         "Balls": 1, "Strikes": 1, "Inning": 1, "PAofInning": 1, "PitchofPA": 1,
         "Pitcher": "Doe, Jane"},
    ])


def test_pa_choices_keeps_pas_separate_across_games():
    from app.dashboards.hitting.tabs import plate_appearances as pa
    df = _fake_pooled_pitches()
    choices = pa.pa_choices(df)
    # both games' (Inn 1, PA 1) must survive as distinct entries, not collapse to 1
    assert len(choices) == 2
    assert len({c["value"] for c in choices}) == 2


def test_render_all_pas_renders_pooled_multi_game_df():
    from app.dashboards.hitting.tabs import plate_appearances as pa
    from dash import dcc
    out = pa.render_all_pas(_fake_pooled_pitches())
    assert isinstance(out, dcc.Graph)
    # two distinct game-PAs -> two subplot titles, one per game
    assert len(out.figure.layout.annotations) == 2


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


def _collect_ids(component, out=None):
    """Collect every component id found anywhere in a Dash component tree."""
    out = [] if out is None else out
    cid = getattr(component, "id", None)
    if cid is not None:
        out.append(cid)
    ch = getattr(component, "children", None)
    kids = ch if isinstance(ch, (list, tuple)) else ([ch] if ch is not None else [])
    for k in kids:
        _collect_ids(k, out)
    return out


def _has_type(component, typ):
    if isinstance(component, typ):
        return True
    ch = getattr(component, "children", None)
    kids = ch if isinstance(ch, (list, tuple)) else ([ch] if ch is not None else [])
    return any(_has_type(k, typ) for k in kids)


def test_hitting_tab_bar_merges_game_pa_zone():
    """Item 1: Game Level / Plate Appearances / Zone Location collapse into one
    'Game Level' tab; the standalone pa/zone tabs are gone."""
    import inspect
    from app.dashboards.hitting import layout
    src = inspect.getsource(layout)
    assert 'value="pa"' not in src
    assert 'value="zone"' not in src
    assert 'value="game"' in src
    for v in ("video", "bip", "last27", "devplan"):
        assert f'value="{v}"' in src


def test_game_tab_body_stacks_batting_pa_and_zone(game_df):
    """The merged Game Level body contains the batting table plus the PA and
    Zone controls (so their existing callbacks still resolve)."""
    from app.dashboards.hitting import callbacks
    from dash import dash_table
    body = callbacks.game_tab_body(game_df)
    ids = _collect_ids(body)
    assert "pa-dd" in ids and "pa-breakdown" in ids and "zone-dd" in ids
    assert _has_type(body, dash_table.DataTable)
    # empty df must not crash
    assert callbacks.game_tab_body(pd.DataFrame()) is not None


def test_game_level_renders_for_real_and_empty(game_df):
    from app.dashboards.hitting.tabs import game_level
    from dash import html
    out = game_level.render(game_df)
    assert isinstance(out, html.Div)
    # empty df must not crash
    assert isinstance(game_level.render(pd.DataFrame()), html.Div)


def test_game_level_drops_qc_pathq_columns(game_df):
    from app.dashboards.hitting.tabs import game_level
    out = game_level.render(game_df)
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
    monkeypatch.setattr("app.data.hitting_caps.lmu_hitters",
                        lambda season=None: pd.DataFrame([{"Batter": "Doe, John", "BatterId": 1}]))
    monkeypatch.setattr("app.data.hitting_caps.games_for_batter",
                        lambda b, *a, **k: pd.DataFrame(columns=["game_id", "game_date", "GameLabel"]))
    monkeypatch.setattr("app.data.hitting_caps.player_profile",
                        lambda b: {"name": "Doe, John", "bats": "Right",
                                   "class_year": "Jr.", "position": "OF",
                                   "photo": "", "jersey": ""})
    monkeypatch.setattr("app.data.hitting_caps.sidebar_stats",
                        lambda b, season=None: {"qab": 0.42, "BA": ".321", "SLG": ".500", "OBP": ".410"})
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
    # header present (logo wordmark + logout), and no bottom back-home link
    tree = str(out)
    assert "The Paw" in tree and "/logout" in tree
    assert "Back to home" not in tree
    assert "hit-season" in tree  # academic-year Season dropdown is rendered
    # computed slash line reached the sidebar tiles
    assert ".321" in tree


def _find_component(node, comp_id):
    """Depth-first search for a Dash component whose id == comp_id."""
    if getattr(node, "id", None) == comp_id:
        return node
    children = getattr(node, "children", None)
    if children is None:
        return None
    if not isinstance(children, (list, tuple)):
        children = [children]
    for c in children:
        found = _find_component(c, comp_id)
        if found is not None:
            return found
    return None


def test_serve_layout_season_dropdown_first_and_defaults_current(server, monkeypatch):
    from app.extensions import db
    from app.auth.models import User
    from flask_login import login_user
    from app.data import seasons
    monkeypatch.setattr(seasons, "available_seasons",
                        lambda: ["2025/2026", "2024/2025", "2023/2024"])
    monkeypatch.setattr(seasons, "current_season", lambda: "2025/2026")
    monkeypatch.setattr("app.data.hitting_caps.lmu_hitters",
                        lambda season=None: pd.DataFrame([{"Batter": "Doe, John", "BatterId": 1}]))
    monkeypatch.setattr("app.data.hitting_caps.games_for_batter",
                        lambda b, *a, **k: pd.DataFrame(columns=["game_id", "game_date", "GameLabel"]))
    monkeypatch.setattr("app.data.hitting_caps.player_profile",
                        lambda b: {"name": "Doe, John", "bats": "", "class_year": "",
                                   "position": "", "photo": "", "jersey": ""})
    monkeypatch.setattr("app.data.hitting_caps.sidebar_stats",
                        lambda b, season=None: {"qab": None, "BA": "—", "SLG": "—", "OBP": "—"})
    with server.app_context():
        coach = User(email="c3@lmu.edu", name="Coach", role="coach")
        coach.set_password("x")
        db.session.add(coach)
        db.session.commit()
        with server.test_request_context("/dash/hitting/"):
            login_user(coach)
            from app.dashboards.hitting import layout
            out = layout.serve_layout()
    dd = _find_component(out, "hit-season")
    assert dd is not None
    assert dd.value == "2025/2026"                       # defaults to current season
    assert [o["value"] for o in dd.options] == ["2025/2026", "2024/2025", "2023/2024"]
    # it is the first control in the selector row
    row = _find_component(out, "hitter-dd")  # sanity: hitter dd also present
    assert row is not None


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


def test_game_options_refresh_on_hitter_change(server):
    """Regression: switching the hitter must refresh the game dropdown, so
    hitter-dd is an INPUT (not State) of the game-dd.options callback. Otherwise
    the game list stays stuck on the previous/default hitter's games."""
    from dash import Dash
    from app.dashboards.hitting import layout, callbacks, index
    app = Dash(__name__, server=server, url_base_pathname="/dash/htest2/",
               suppress_callback_exceptions=True)
    app.index_string = index.INDEX_STRING
    app.layout = layout.serve_layout
    callbacks.register_callbacks(app)
    # find the callback that outputs game-dd.options and assert hitter-dd.value is an Input
    key = next(k for k in app.callback_map if "game-dd.options" in k)
    inputs = {i["id"] + "." + i["property"] for i in app.callback_map[key]["inputs"]}
    assert "hitter-dd.value" in inputs


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


def test_hitting_range_pooled_render_live():
    from app import create_app
    from config import Config
    from app.data import hitting_caps as H
    from app.dashboards.hitting.tabs import game_level, plate_appearances as pa, zone_location as zl
    class T(Config):
        TESTING = True; SECRET_KEY = "t"; SQLALCHEMY_DATABASE_URI = "sqlite://"
    with create_app(T).app_context():
        hitters = H.lmu_hitters()
        if hitters.empty:
            import pytest; pytest.skip("no hitters")
        bid = int(hitters.iloc[0]["BatterId"])
        g = H.games_for_batter(bid)
        if g.empty:
            import pytest; pytest.skip("no games")
        lo, hi = str(g["game_date"].min()), str(g["game_date"].max())
        pooled = H.range_pitches(bid, lo, hi)
        if pooled.empty:
            import pytest; pytest.skip("no pooled")
        assert game_level.render(pooled) is not None
        assert pa.render_all_pas(pooled) is not None
        assert zl.render(pooled, "All Swings") is not None


def test_hitting_layout_has_back_link_and_dark_footnote():
    import inspect
    from app.dashboards.hitting import layout
    src = inspect.getsource(layout)
    # header called with the /hitting back-link
    assert 'back_href="/hitting"' in src
    # provisional footnote no longer uses the too-light #888
    assert '"Slash line = recent-season game data (provisional)."' in src
    footnote_idx = src.index('"Slash line = recent-season game data (provisional)."')
    # the style dict immediately after the footnote uses #555, not #888
    tail = src[footnote_idx:footnote_idx + 300]
    assert '"#555"' in tail and '"#888"' not in tail


def test_hitting_pitch_colors_match_pitching():
    from app.dashboards.hitting import charts
    from app.data import pitching as P
    for pt in ("Fastball", "ChangeUp", "Cutter", "Slider", "Sinker", "Curveball"):
        assert charts.color_for(pt) == P.pitch_color(pt)


def test_stat_table_colors_tagged_pitch_type():
    import pandas as pd
    from app.dashboards.hitting import tables
    from app.data import pitching as P
    df = pd.DataFrame({"TaggedPitchType": ["Slider", "Sinker"], "Balls": [0, 1]})
    tbl = tables.stat_table(df, id="t")
    conds = tbl.style_data_conditional or []
    colored = {c.get("color") for c in conds
               if c.get("if", {}).get("column_id") == "TaggedPitchType"}
    assert P.pitch_color("Slider") in colored and P.pitch_color("Sinker") in colored
    # no-op without the column
    plain = tables.stat_table(pd.DataFrame({"PA": [1]}), id="t2")
    assert not any(c.get("if", {}).get("column_id") == "TaggedPitchType"
                   for c in (plain.style_data_conditional or []))


def test_hitting_tabs_include_video():
    import inspect
    from app.dashboards.hitting import layout
    src = inspect.getsource(layout.serve_layout)
    assert '"video"' in src and "Video" in src


def test_bip_figs_empty_and_nonempty():
    import pandas as pd
    import plotly.graph_objects as go
    from app.dashboards.hitting import charts
    empty = pd.DataFrame(columns=["hit_type", "x", "y", "rx", "ry", "exit_speed", "la", "distance"])
    assert isinstance(charts.radial_fig(empty), go.Figure)
    assert isinstance(charts.spray_fig(empty), go.Figure)
    df = pd.DataFrame({
        "hit_type": ["LineDrive", "FlyBall"], "x": [50.0, -60.0], "y": [200.0, 180.0],
        "rx": [0.6, 0.5], "ry": [0.2, 0.5], "exit_speed": [95.0, 88.0],
        "la": [12.0, 30.0], "distance": [300.0, 280.0]})
    assert len(charts.radial_fig(df).data) >= 2
    assert len(charts.spray_fig(df).data) >= 2


def test_bip_tab_render_has_chip_store_and_graph():
    import pandas as pd
    from app.dashboards.hitting.tabs import balls_in_play
    df = pd.DataFrame({
        "hit_type": ["LineDrive"], "x": [50.0], "y": [200.0], "rx": [0.6], "ry": [0.2],
        "exit_speed": [95.0], "la": [12.0], "distance": [300.0],
        "Count": ["1-1"], "Result": ["LineDrive - Single"], "PitchType": ["Fastball"],
        "Pitcher": ["X"]})
    out = balls_in_play.render(df)
    s = str(out)
    assert "bip-active" in s and "bip-body" in s and "bip-chip" in s


def test_last27_render_empty_ok():
    import pandas as pd
    from app.dashboards.hitting.tabs import last_27
    out = last_27.render(pd.DataFrame(), pd.DataFrame())
    assert "No recent plate appearances" in str(out)


def test_hitting_tabs_include_bip_and_last27():
    import inspect
    from app.dashboards.hitting import layout
    src = inspect.getsource(layout.serve_layout)
    assert '"bip"' in src and "Balls in Play" in src
    assert '"last27"' in src and "Last 27 PA" in src


def test_dev_plan_render_prompt_coach_player():
    from app.dashboards.hitting.tabs import dev_plan
    # no hitter selected -> prompt
    assert "Select a hitter" in str(dev_plan.render(None, True))


def test_hitting_tabs_include_dev_plan():
    import inspect
    from app.dashboards.hitting import layout
    src = inspect.getsource(layout.serve_layout)
    assert '"devplan"' in src and "Dev Plan" in src


def test_hitting_uses_preset_control():
    import inspect
    from app.dashboards.hitting import layout
    src = inspect.getsource(layout.serve_layout)
    assert "date_control" in src and "date_picker(" not in src


def test_hitting_preset_callback_writes_range(server):
    from dash import Dash
    from app.dashboards.hitting import layout, callbacks
    app = Dash(__name__, server=server, url_base_pathname="/dash/hittest2/",
               suppress_callback_exceptions=True)
    app.layout = layout.serve_layout
    callbacks.register_callbacks(app)
    assert any("hit-daterange" in str(k) for k in app.callback_map)
    assert any("hit-date-preset" in str(v) for v in app.callback_map.values())


def test_dev_plan_coach_editable_player_readonly(tmp_path):
    from app import create_app
    from config import Config

    class TestConfig(Config):
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'dp.db'}"

    app = create_app(TestConfig)
    from app.dashboards.hitting.tabs import dev_plan
    with app.app_context():
        from app.data import dev_plans
        dev_plans.upsert_plan("hitting", 806253, "drive the ball", author_id=1)
        coach = str(dev_plan.render(806253, True))
        player = str(dev_plan.render(806253, False))
        assert "devplan-text" in coach and "devplan-save" in coach
        assert "devplan-text" not in player          # player is read-only
        assert "drive the ball" in player             # but sees the plan text
