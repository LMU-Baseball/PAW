"""Tests for the Dash catching dashboard (shell, selectors, tab renders)."""
import math
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


def test_catching_range_pooled_render_live(real_catcher):
    from app.data import catching as C
    from app.dashboards.catching.tabs import framing, static_framing, caught_stealing
    g = C.games_for_catcher(real_catcher)
    if g.empty:
        import pytest; pytest.skip("no games")
    lo, hi = str(g["game_date"].min()), str(g["game_date"].max())
    pooled = C.range_pitches_for(real_catcher, lo, hi)
    if pooled.empty:
        import pytest; pytest.skip("no pooled pitches")
    assert framing.render(pooled) is not None
    assert static_framing.render(pooled) is not None
    assert caught_stealing.render(pooled) is not None


def test_framing_scatter_is_aspect_locked():
    from app.dashboards.catching import charts
    fig = charts.framing_scatter(_sample_df())
    assert fig.layout.yaxis.scaleanchor == "x"
    assert fig.layout.yaxis.scaleratio == 1


def test_framing_facets_is_aspect_locked():
    from app.dashboards.catching import charts
    fig = charts.framing_facets(_sample_df(), by="batter_side", title="Batter Side")
    # first facet's y-axis is locked to its x-axis
    assert fig.layout.yaxis.scaleanchor == "x"


def test_caught_stealing_trend_fig_builds():
    import pandas as pd
    from app.dashboards.catching import charts
    empty = charts.caught_stealing_trend_fig(pd.DataFrame(
        columns=["game_date", "attempts", "caught", "cs_pct", "avg_pop"]))
    assert empty is not None
    one = charts.caught_stealing_trend_fig(pd.DataFrame([
        {"game_date": "2026-04-01", "attempts": 2, "caught": 1,
         "cs_pct": 50.0, "avg_pop": 2.0}]))
    assert one is not None
    multi = charts.caught_stealing_trend_fig(pd.DataFrame([
        {"game_date": "2026-04-01", "attempts": 2, "caught": 1, "cs_pct": 50.0, "avg_pop": 2.0},
        {"game_date": "2026-04-08", "attempts": 1, "caught": 0, "cs_pct": 0.0, "avg_pop": None}]))
    assert len(multi.data) >= 1


def _has_graph(component):
    """True if a dcc.Graph appears anywhere in the component tree."""
    from dash import dcc
    if isinstance(component, dcc.Graph):
        return True
    ch = getattr(component, "children", None)
    if ch is None or isinstance(ch, str):
        return False
    kids = ch if isinstance(ch, (list, tuple)) else [ch]
    return any(_has_graph(k) for k in kids)


def test_caught_stealing_tab_has_trend_graph():
    from app.dashboards.catching.tabs import caught_stealing
    assert _has_graph(caught_stealing.render(_sample_df()))


def test_framing_render_has_call_chips():
    from app.dashboards.catching.tabs import framing
    comp = framing.render(_sample_df())
    ids = _collect_ids(comp)  # helper already in this test file
    assert "call-active" in ids


def test_framing_body_call_filter_scatter_only():
    from app.dashboards.catching.tabs import framing
    from app.data import catching as C
    df = _sample_df()
    # Full body vs body filtered to a single call type
    full = framing.body(df, bat_side="All", pitcher_throws="All",
                        pitch_speed="All", zone="All")
    filtered = framing.body(df, bat_side="All", pitcher_throws="All",
                            pitch_speed="All", zone="All",
                            active_calls=["Stolen Strike"])
    # The summary table (fr-summary) is identical regardless of active_calls
    # (table uses all calls). Locate the DataTable data in each tree.
    def find_table(c):
        from dash import dash_table
        out = []
        def walk(x):
            if isinstance(x, dash_table.DataTable):
                out.append(x)
            ch = getattr(x, "children", None)
            if ch and not isinstance(ch, str):
                for k in (ch if isinstance(ch, (list, tuple)) else [ch]):
                    walk(k)
        walk(c)
        return out
    assert find_table(full)[0].data == find_table(filtered)[0].data


def test_caught_stealing_no_note_when_multi_game():
    """Verify the 'widen the date range' note is absent when df spans multiple games."""
    from app.dashboards.catching.tabs import caught_stealing
    df = pd.DataFrame([
        {"play_result": "CaughtStealing", "game_date": "2026-04-01", "pop_time": 1.9,
         "exchange_time": 0.7, "throw_speed": 80.0, "inning": 1, "pitcher_name": "A, B"},
        {"play_result": "StolenBase", "game_date": "2026-04-08", "pop_time": 2.0,
         "exchange_time": 0.72, "throw_speed": 78.0, "inning": 3, "pitcher_name": "A, B"},
    ])
    comp = caught_stealing.render(df)

    def _text(c):
        """Recursively collect all text strings from component tree."""
        out = []
        def walk(x):
            if isinstance(x, str):
                out.append(x)
                return
            ch = getattr(x, "children", None)
            if ch is None:
                return
            for k in (ch if isinstance(ch, (list, tuple)) else [ch]):
                walk(k)
        walk(c)
        return " ".join(out)

    text = _text(comp)
    assert "widen the date range" not in text


def test_framing_facets_wraps_to_two_columns():
    import pandas as pd
    from app.dashboards.catching import charts
    # four Zone values -> should be a 2x2 grid (2 rows), not 1x4
    df = pd.DataFrame([
        {"plate_loc_side": s, "plate_loc_height": h,
         "pitch_call": "StrikeCalled", "batter_side": "Right",
         "pitcher_throws": "Right", "rel_speed": 90.0, "tagged_pitch_type": "Fastball"}
        for s, h in [(-1.5, 0.5), (-0.5, 2.0), (-1.0, 1.5), (-2.0, 0.5)]
        # These map to: Chase, Heart, Shadow, Waste (4 unique zones)
    ])
    fig = charts.framing_facets(df, by="Zone", title="Zone Location")
    # 4 subplots across 2 columns => 2 rows => 4 xaxis objects, y range spans 2 rows
    n_xaxes = len([k for k in fig.layout if k.startswith("xaxis")])
    assert n_xaxes == 4
    # rows=2 => the grid height grows beyond a single-row figure
    assert fig.layout.height and fig.layout.height >= 700
