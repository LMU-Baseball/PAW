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


def _collect_ids(component):
    """Recursively gather all component ids in a Dash layout tree."""
    ids = set()

    def walk(c):
        if c is None or isinstance(c, str):
            return
        if isinstance(c, (list, tuple)):
            for x in c:
                walk(x)
            return
        cid = getattr(c, "id", None)
        if isinstance(cid, str):
            ids.add(cid)
        walk(getattr(c, "children", None))

    walk(component)
    return ids


def _sample_df():
    return pd.DataFrame([
        {"pitch_call": "StrikeCalled", "play_result": "Undefined",
         "plate_loc_side": 1.5, "plate_loc_height": 2.5, "batter_side": "Right",
         "pitcher_throws": "Left", "tagged_pitch_type": "Fastball",
         "inning": 1, "pitcher_name": "A, B", "pop_time": None},
        {"pitch_call": "BallCalled", "play_result": "Undefined",
         "plate_loc_side": 0.0, "plate_loc_height": 2.5, "batter_side": "Left",
         "pitcher_throws": "Right", "tagged_pitch_type": "Slider",
         "inning": 3, "pitcher_name": "A, B", "pop_time": None},
        {"pitch_call": "InPlay", "play_result": "CaughtStealing",
         "plate_loc_side": -0.2, "plate_loc_height": 2.1, "batter_side": "Right",
         "pitcher_throws": "Right", "tagged_pitch_type": "ChangeUp",
         "inning": 6, "pitcher_name": "A, B", "pop_time": 1.9},
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
    assert "/dash/catching/" in rules


def test_all_tabs_render(server):
    from app.dashboards.catching.tabs import framing, static_framing, caught_stealing
    df = _sample_df()
    assert framing.render(df) is not None
    assert static_framing.render(df) is not None
    assert caught_stealing.render(df) is not None


def test_framing_tab_render():
    from app.dashboards.catching.tabs import framing
    assert framing.render(_sample_df()) is not None
    assert framing.render(pd.DataFrame()) is not None


def test_framing_tab_has_filter_ids():
    from app.dashboards.catching.tabs import framing
    comp = framing.render(_sample_df())
    ids = _collect_ids(comp)
    assert {"fr-bat", "fr-throws", "fr-speed", "fr-zone", "fr-body"} <= ids


def test_framing_body_builds():
    from app.dashboards.catching.tabs import framing
    comp = framing.body(_sample_df(), bat_side="All", pitcher_throws="All",
                        pitch_speed="All", zone="All")
    assert comp is not None


def test_framing_scatter_returns_figure():
    from app.dashboards.catching import charts
    fig = charts.framing_scatter(_sample_df())
    assert fig is not None


def test_framing_scatter_has_calltype_traces():
    from app.dashboards.catching import charts
    fig = charts.framing_scatter(_sample_df())
    names = {t.name for t in fig.data}
    # at least one CallType series present; figure builds without error
    assert names & {"Stolen Strike", "Lost Strike", "Correct Call"}


def test_framing_facets_builds():
    from app.dashboards.catching import charts
    fig = charts.framing_facets(_sample_df(), by="batter_side", title="Batter Side")
    assert fig is not None


def test_framing_facets_legend_covers_all_calltypes():
    from app.dashboards.catching import charts
    fig = charts.framing_facets(_sample_df(), by="batter_side", title="Batter Side")
    present = {t.name for t in fig.data if t.name}
    legended = {t.name for t in fig.data if t.name and t.showlegend}
    # every CallType actually plotted somewhere in the figure has exactly-once
    # legend coverage across facets (not gated on the first facet only)
    assert present == legended


def test_framing_scatter_empty_df():
    from app.dashboards.catching import charts
    fig = charts.framing_scatter(pd.DataFrame())
    assert fig is not None


def test_framing_facets_empty_df():
    from app.dashboards.catching import charts
    fig = charts.framing_facets(pd.DataFrame(), by="batter_side", title="X")
    assert fig is not None


@pytest.fixture(scope="module")
def real_catcher():
    """Live-DB fixture (unguarded when DB is up; skips if unreachable/empty)."""
    from sqlalchemy.exc import OperationalError
    from app.db import query_df
    try:
        df = query_df(
            """
            SELECT catcher_id FROM fact_tm_game_pitch
             WHERE pitcher_team = 'LOY_LIO' AND catcher_id IS NOT NULL
             GROUP BY catcher_id ORDER BY COUNT(*) DESC LIMIT 1
            """
        )
    except OperationalError as e:
        pytest.skip(f"Analytics DB unreachable: {e}")
    if df.empty:
        pytest.skip("No LMU catcher rows in warehouse")
    return int(df.loc[0, "catcher_id"])


def test_catcher_options_coach_live(real_catcher):
    from app.dashboards.catching import selectors
    opts = selectors.catcher_options(is_coach=True, own_trackman_id=None)
    assert opts and {"label", "value"} <= set(opts[0])
    assert real_catcher in {o["value"] for o in opts}


def test_game_options_for_real_catcher(real_catcher):
    from app.dashboards.catching import selectors
    opts = selectors.game_options(real_catcher)
    assert opts and {"label", "value"} <= set(opts[0])


def test_all_tabs_render_live(real_catcher):
    from app.data import catching as C
    from app.dashboards.catching.tabs import framing, static_framing, caught_stealing
    games = C.games_for_catcher(real_catcher)
    if games.empty:
        pytest.skip("No games found for live catcher")
    gid = int(games.iloc[0]["game_id"])
    df = C.game_pitches_for(gid, real_catcher)
    if df.empty:
        pytest.skip("No pitch rows for live catcher's game")
    assert framing.render(df) is not None
    assert framing.body(df, bat_side="All", pitcher_throws="All",
                         pitch_speed="All", zone="All") is not None
    assert static_framing.render(df) is not None
    assert caught_stealing.render(df) is not None


def test_static_framing_render():
    from app.dashboards.catching.tabs import static_framing
    comp = static_framing.render(_sample_df())
    assert comp is not None


def test_caught_stealing_render_with_attempt():
    from app.dashboards.catching.tabs import caught_stealing
    comp = caught_stealing.render(_sample_df())  # sample has 1 CaughtStealing
    assert comp is not None


def test_caught_stealing_render_empty():
    import pandas as pd
    from app.dashboards.catching.tabs import caught_stealing
    comp = caught_stealing.render(pd.DataFrame([
        {"play_result": "Single", "pitch_call": "InPlay",
         "plate_loc_side": 0.0, "plate_loc_height": 2.5}]))
    assert comp is not None
