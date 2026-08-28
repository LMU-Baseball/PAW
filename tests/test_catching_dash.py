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


def test_resolve_catcher_player_can_view_others():
    from app.dashboards.catching import selectors
    # Team-transparent: a player may resolve ANY requested id; when nothing is
    # requested it falls back to the viewer's own id.
    assert selectors.resolve_catcher(999, is_coach=False, own_trackman_id=None) == 999
    assert selectors.resolve_catcher(None, is_coach=False, own_trackman_id=555) == 555


def test_resolve_catcher_coach_passes_through():
    from app.dashboards.catching import selectors
    assert selectors.resolve_catcher(999, is_coach=True, own_trackman_id=None) == 999
    assert selectors.resolve_catcher(None, is_coach=True, own_trackman_id=None) is None


def test_resolve_catcher_player_keeps_requested_id():
    from app.dashboards.catching import selectors
    got = selectors.resolve_catcher(999, is_coach=False, own_trackman_id=555)
    assert got == 999  # team-transparent: the requested id is honored, not own


def test_catcher_options_coach(monkeypatch):
    from app.dashboards.catching import selectors
    monkeypatch.setattr(
        "app.data.catching_caps.lmu_catchers",
        lambda season=None: pd.DataFrame([{"Catcher": "Doe, John", "CatcherId": 1},
                                          {"Catcher": "Roe, Jane", "CatcherId": 2}]),
    )
    opts = selectors.catcher_options(is_coach=True, own_trackman_id=None)
    assert {o["value"] for o in opts} == {1, 2}


def test_catcher_options_coach_scoped_by_date_range():
    from app.data import seasons
    from app.dashboards.catching import selectors
    season = seasons.current_season()
    s, e = seasons.season_bounds(season)
    opts_all = selectors.catcher_options(is_coach=True, own_trackman_id=None, season=season)
    opts_1900 = selectors.catcher_options(is_coach=True, own_trackman_id=None, season=season,
                                          start="1900-01-01", end="1900-01-02")
    assert opts_all and opts_1900 == []
    opts_window = selectors.catcher_options(is_coach=True, own_trackman_id=None, season=season,
                                            start=str(s), end=str(e))
    assert {o["value"] for o in opts_window} == {o["value"] for o in opts_all}


def test_catcher_options_player_lists_all_date_scoped(monkeypatch):
    """Team-transparent view: a player sees the full roster, date-scoped like a
    coach (a view filter that now applies to every account)."""
    from app.dashboards.catching import selectors
    seen = {}

    def fake(season=None, start=None, end=None):
        seen["start"], seen["end"] = start, end
        return pd.DataFrame([{"Catcher": "Doe, John", "CatcherId": 1}])

    monkeypatch.setattr("app.data.catching_caps.lmu_catchers", fake)
    opts = selectors.catcher_options(is_coach=False, own_trackman_id=555,
                                     start="1900-01-01", end="1900-01-02")
    assert [o["value"] for o in opts] == [1]
    assert seen == {"start": "1900-01-01", "end": "1900-01-02"}


def test_catcher_dd_options_callback_registered(server):
    """Task 5: date-range change must also refresh catcher-dd.options (a
    sibling callback to the game-dd refresh), narrowing the Catcher dropdown
    to players with data in the selected range."""
    from dash import Dash
    from app.dashboards.catching import layout, callbacks
    app = Dash(__name__, server=server, url_base_pathname="/dash/cattest3/",
               suppress_callback_exceptions=True)
    app.layout = layout.serve_layout
    callbacks.register_callbacks(app)
    outs = {str(k) for k in app.callback_map}
    assert any("catcher-dd.options" in o for o in outs)


def test_layout_scopes_first_paint_catchers_to_season_default_range(server):
    """The Task 5 first-paint catcher options must be scoped to the season-
    default range (start_d, end_d), not every catcher in the season."""
    import inspect
    from app.dashboards.catching import layout
    src = inspect.getsource(layout.serve_layout)
    assert "start=start_d, end=end_d" in src


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
    """Live-DB fixture (unguarded when DB is up; skips if unreachable/empty).

    RAW GAMES.CatcherId (== a player's trackman_id) -- the id space the
    dashboard now uses everywhere (no warehouse surrogate mapping). Picks the
    catcher with the most numeric-GameID rows so the fixture lands on a
    well-tracked current-season catcher; games_for_catcher itself is now
    GameID-agnostic (opaque-string contract) and returns that catcher's full
    history, current and legacy alike.
    """
    from sqlalchemy.exc import OperationalError
    from app.db import query_df
    try:
        df = query_df(
            """
            SELECT CatcherId FROM GAMES
             WHERE PitcherTeam = 'LOY_LIO' AND CatcherId IS NOT NULL
               AND GameID REGEXP '^[0-9]+$'
             GROUP BY CatcherId ORDER BY COUNT(*) DESC LIMIT 1
            """
        )
    except OperationalError as e:
        pytest.skip(f"Analytics DB unreachable: {e}")
    if df.empty:
        pytest.skip("No LMU catcher rows in GAMES")
    return int(df.loc[0, "CatcherId"])


def test_catcher_options_coach_live(real_catcher):
    from app.dashboards.catching import selectors
    # Pinned to the actual latest season with real GAMES data: current_season()
    # now always resolves to today's calendar season ("2026/2027" as of this
    # writing), which has zero real Trackman rows yet (only roster
    # placeholders) -- see tests/test_pitching_caps.py's identical "2025/2026"
    # pin for the same reason.
    opts = selectors.catcher_options(is_coach=True, own_trackman_id=None,
                                      season="2025/2026")
    assert opts and {"label", "value"} <= set(opts[0])
    assert real_catcher in {o["value"] for o in opts}


def test_game_options_for_real_catcher(real_catcher):
    from app.dashboards.catching import selectors
    opts = selectors.game_options(real_catcher)
    assert opts and {"label", "value"} <= set(opts[0])


def test_all_tabs_render_live(real_catcher):
    from app.data import catching_caps
    from app.dashboards.catching.tabs import framing, static_framing, caught_stealing
    games = catching_caps.games_for_catcher(real_catcher)
    if games.empty:
        pytest.skip("No games found for live catcher")
    # game_id is an opaque string (numeric surrogate or composite), never int()'d.
    gid = str(games.iloc[0]["game_id"])
    df = catching_caps.game_pitches_for(gid, real_catcher)
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
    from app.data import catching_caps
    from app.dashboards.catching.tabs import framing, static_framing, caught_stealing
    g = catching_caps.games_for_catcher(real_catcher)
    if g.empty:
        import pytest; pytest.skip("no games")
    lo, hi = str(g["game_date"].min()), str(g["game_date"].max())
    pooled = catching_caps.range_pitches_for(real_catcher, lo, hi)
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


def test_framing_body_feeds_heat_map_the_filtered_frame():
    """Finding 3 fix: slaa_location_figure must receive the tab's filtered
    frame (post apply_framing_filters), not the raw unfiltered df -- else the
    heat map (captioned "...this selection") doesn't move when a coach
    changes the Batter Hand / Pitcher Throws / etc dropdowns, even though the
    scatter and summary table above it do."""
    import re
    from app.dashboards.catching.tabs import framing
    from app.data import catching as C
    from app.data import catching_caps
    from dash import dcc

    df = pd.DataFrame([
        {"plate_loc_side": 0.0, "plate_loc_height": 2.5, "pitch_call": "StrikeCalled",
         "batter_side": "Right", "pitcher_throws": "Right", "tagged_pitch_type": "Fastball"},
        {"plate_loc_side": 0.0, "plate_loc_height": 2.5, "pitch_call": "BallCalled",
         "batter_side": "Left", "pitcher_throws": "Right", "tagged_pitch_type": "Fastball"},
    ])
    right_only = framing.body(df, bat_side="Right", pitcher_throws="All",
                              pitch_speed="All", zone="All")

    def _graphs(comp):
        out = []
        def walk(x):
            if isinstance(x, dcc.Graph):
                out.append(x)
            ch = getattr(x, "children", None)
            if ch and not isinstance(ch, str):
                for k in (ch if isinstance(ch, (list, tuple)) else [ch]):
                    walk(k)
        walk(comp)
        return out

    heat_graph = _graphs(right_only)[-1]  # heat map is the last Graph in body()
    caption = heat_graph.figure.layout.title.subtitle.text
    m = re.search(r"over (\d+) taken pitches", caption)
    assert m is not None, caption
    rendered_taken = int(m.group(1))

    filtered = C.apply_framing_filters(C.add_framing_cols(df), bat_side="Right")
    expected = catching_caps.slaa_summary(filtered)
    assert expected["taken"] == 1, "filtering to Right batters must drop the Left-batter pitch"
    assert rendered_taken == expected["taken"], (
        f"heat map caption shows {rendered_taken} taken pitches but the "
        f"Batter Hand=Right filtered frame has {expected['taken']} -- the "
        "heat map is still reading the tab's raw, unfiltered df")


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


def test_framing_facets_hides_unused_trailing_cells():
    import pandas as pd
    from app.dashboards.catching import charts
    # three Zone values -> should be a 2x2 grid, but 4th cell must be hidden
    df = pd.DataFrame([
        {"plate_loc_side": s, "plate_loc_height": h,
         "pitch_call": "StrikeCalled", "batter_side": "Right",
         "pitcher_throws": "Right", "rel_speed": 90.0, "tagged_pitch_type": "Fastball"}
        for s, h in [(-1.5, 0.5), (-0.5, 2.0), (-1.0, 1.5)]
        # These map to: Chase, Heart, Shadow (3 unique zones)
    ])
    fig = charts.framing_facets(df, by="Zone", title="Zone Location")
    # 3 facets in 2x2 grid => xaxis1, xaxis2, xaxis3, xaxis4
    n_xaxes = len([k for k in fig.layout if k.startswith("xaxis")])
    assert n_xaxes == 4
    # The 4th cell (unused) must have its axes hidden
    assert fig.layout.xaxis4.visible is False
    assert fig.layout.yaxis4.visible is False


def test_framing_legends_are_off():
    import pandas as pd
    from app.dashboards.catching import charts
    df = pd.DataFrame([
        {"plate_loc_side": s, "plate_loc_height": h, "izt_zone": z,
         "pitch_call": "StrikeCalled", "batter_side": "Right",
         "pitcher_throws": "Right", "rel_speed": 90.0, "tagged_pitch_type": "Fastball"}
        for s, h, z in [(-0.5, 2.5, "1"), (0.5, 2.5, "Ball")]
    ])
    assert charts.framing_scatter(df).layout.showlegend is False
    assert charts.framing_facets(df, by="batter_side",
                                 title="Batter Side").layout.showlegend is False


def test_static_framing_has_call_chips_and_filters():
    import inspect
    import pandas as pd
    from app.dashboards.catching.tabs import static_framing
    src = inspect.getsource(static_framing)
    assert "static-call-chip" in src and "static-call-active" in src
    df = pd.DataFrame([
        {"plate_loc_side": s, "plate_loc_height": h, "izt_zone": z,
         "pitch_call": pc, "batter_side": "Right", "pitcher_throws": "Right",
         "rel_speed": 90.0, "tagged_pitch_type": "Fastball"}
        for s, h, z, pc in [(-0.5, 2.5, "1", "StrikeCalled"),
                            (0.6, 2.6, "Ball", "StrikeCalled")]
    ])
    # body accepts an active_calls filter and still renders
    assert static_framing.body(df, active_calls=["Stolen Strike"]) is not None
    assert static_framing.body(df, active_calls=None) is not None


def test_catching_callbacks_have_static_call():
    import inspect
    from app.dashboards.catching import callbacks
    src = inspect.getsource(callbacks)
    assert "static-call-active" in src and "static-body" in src


def test_catching_tabs_include_pitch_level():
    import inspect
    from app.dashboards.catching import layout
    src = inspect.getsource(layout.serve_layout)
    assert '"pitchlevel"' in src and "Outing Video" in src


def test_catching_uses_preset_control():
    import inspect
    from app.dashboards.catching import layout
    src = inspect.getsource(layout.serve_layout)
    assert "date_control" in src and "date_picker(" not in src


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
    monkeypatch.setattr("app.data.catching_caps.lmu_catchers",
                        lambda season=None, start=None, end=None: pd.DataFrame(
                            [{"Catcher": "Doe, John", "CatcherId": 1}]))
    monkeypatch.setattr("app.data.catching_caps.games_for_catcher",
                        lambda c, *a, **k: pd.DataFrame(columns=["game_id", "game_date", "GameLabel"]))
    monkeypatch.setattr("app.data.catching_caps.catcher_profile",
                        lambda c: {"name": "Doe, John", "class_year": "",
                                   "position": "", "photo": "", "jersey": ""})
    monkeypatch.setattr("app.data.catching_caps.framing_season_tiles",
                        lambda c, *a, **k: {"games": 0, "strikes": 0,
                                            "strikes_lost": 0, "cs_pct": "—"})
    with server.app_context():
        coach = User(email="cat-season@lmu.edu", name="Coach", role="coach")
        coach.set_password("x")
        db.session.add(coach)
        db.session.commit()
        with server.test_request_context("/dash/catching/"):
            login_user(coach)
            from app.dashboards.catching import layout
            out = layout.serve_layout()
    dd = _find_component(out, "cat-season")
    assert dd is not None
    assert dd.value == "2025/2026"                       # defaults to current season
    assert [o["value"] for o in dd.options] == ["2025/2026", "2024/2025", "2023/2024"]
    # sanity: the catcher dropdown is also present in the selector row
    assert _find_component(out, "catcher-dd") is not None


def test_catching_preset_callback_writes_range(server):
    from dash import Dash
    from app.dashboards.catching import layout, callbacks
    app = Dash(__name__, server=server, url_base_pathname="/dash/cattest2/",
               suppress_callback_exceptions=True)
    app.layout = layout.serve_layout
    callbacks.register_callbacks(app)
    assert any("cat-daterange" in str(k) for k in app.callback_map)
    assert any("cat-date-preset" in str(v) for v in app.callback_map.values())


def test_sidebar_shows_slaa_and_sl_plus_tiles(monkeypatch):
    """The two new tiles render alongside the existing STRIKES tiles, which
    must survive unchanged."""
    from app.dashboards.catching import layout as cl
    from app.data import catching_caps

    monkeypatch.setattr(catching_caps, "catcher_profile", lambda cid: {
        "photo": None, "jersey": "12", "name": "Test Catcher",
        "class_year": "SR", "position": "C"})
    monkeypatch.setattr(catching_caps, "framing_season_tiles",
                        lambda *a, **k: {"games": "10", "strikes": "40",
                                         "strikes_lost": "12", "cs_pct": "30%"})
    monkeypatch.setattr(catching_caps, "slaa_season_tiles",
                        lambda *a, **k: {"slaa": "+8.4", "sl_plus": "112",
                                         "taken": "640"})
    tree = str(cl.sidebar(1, None, None, None))
    assert "SLAA" in tree
    assert "+8.4" in tree
    assert "SL+" in tree
    assert "112" in tree
    # the pre-existing tiles are untouched
    assert "STRIKES" in tree and "40" in tree


def test_sidebar_shows_taken_pitch_count_caption(monkeypatch):
    """Finding 2 fix: spec Sec.5 requires the taken-pitch count be surfaced
    alongside SLAA/SL+ so a coach can judge the metric's weight. It must NOT
    be added as a 7th tile (that was explicitly rejected) -- it's a caption
    line, matching the file's existing "Stats reflect..." caption style."""
    from app.dashboards.catching import layout as cl
    from app.data import catching_caps

    monkeypatch.setattr(catching_caps, "catcher_profile", lambda cid: {
        "photo": None, "jersey": "12", "name": "Test Catcher",
        "class_year": "SR", "position": "C"})
    monkeypatch.setattr(catching_caps, "framing_season_tiles",
                        lambda *a, **k: {"games": "10", "strikes": "40",
                                         "strikes_lost": "12", "cs_pct": "30%"})
    monkeypatch.setattr(catching_caps, "slaa_season_tiles",
                        lambda *a, **k: {"slaa": "+8.4", "sl_plus": "112",
                                         "taken": "640"})
    tree = str(cl.sidebar(1, None, None, None))
    assert "640" in tree and "taken pitches" in tree
    # still exactly 6 tiles in the grid (no 7th tile added for the count)
    from dash import html
    grid = None
    def walk(c):
        nonlocal grid
        if grid is not None:
            return
        if isinstance(c, html.Div) and isinstance(c.style, dict) and \
                c.style.get("display") == "grid":
            grid = c
            return
        ch = getattr(c, "children", None)
        if ch is None:
            return
        for k in (ch if isinstance(ch, (list, tuple)) else [ch]):
            walk(k)
    walk(cl.sidebar(1, None, None, None))
    assert grid is not None
    assert len(grid.children) == 6


def test_catching_sidebar_callback_lists_daterange_inputs(server):
    """The sidebar callback must rescope on the date range, not just catcher/
    season -- mirrors the hitting/pitching sidebars (hit-daterange/
    pit-daterange). Otherwise the sidebar tiles never update when the coach
    narrows the calendar/preset."""
    from dash import Dash
    from app.dashboards.catching import layout, callbacks
    app = Dash(__name__, server=server, url_base_pathname="/dash/cattest3/",
               suppress_callback_exceptions=True)
    app.layout = layout.serve_layout
    callbacks.register_callbacks(app)
    key = next(k for k in app.callback_map if "sidebar.children" in k)
    inputs = {i["id"] + "." + i["property"] for i in app.callback_map[key]["inputs"]}
    assert "cat-daterange.start_date" in inputs
    assert "cat-daterange.end_date" in inputs


def test_slaa_location_figure_totals_reconcile_with_slaa():
    """Every taken pitch must land in exactly one display cell, so the grid
    sums to the same number the SLAA tile shows."""
    import pandas as pd
    from app.dashboards.catching import charts
    from app.data import called_strike as cs
    from app.data import catching_caps

    rows = [(0.0, 2.5, "StrikeCalled")] * 60 + [(0.0, 2.5, "BallCalled")] * 60
    rows += [(9.0, 9.0, "BallCalled")] * 10          # far outside, must still count
    df = pd.DataFrame(rows, columns=["plate_loc_side", "plate_loc_height", "pitch_call"])
    lk = cs._build_lookup_from_df(df)

    fig = charts.slaa_location_figure(df, lookup=lk)
    grid_total = float(pd.DataFrame(fig.data[0].z).fillna(0).values.sum())
    slaa = catching_caps.slaa_summary(df, lookup=lk)["slaa"]
    assert abs(grid_total - slaa) < 0.05, (
        f"grid sums to {grid_total} but SLAA is {slaa} -- pitches are being "
        "dropped or double-counted")


def test_display_cell_side_orientation_matches_scatter_catcher_view():
    """Finding 1 (CRITICAL) regression guard: `_display_cell` must match the
    framing scatter's catcher-view convention (`catching.add_framing_cols`'s
    `_x = plate_loc_side * -12`), where a positive plate_loc_side draws on
    the LEFT (negative _x), not the right. Before the fix, `_display_cell`
    binned the raw, unnegated side, so the heat map was left-right mirrored
    relative to the scatter directly above it on the same tab despite both
    being titled "Catcher's View" / "Catcher View"."""
    from app.dashboards.catching import charts
    positive_side_col, _ = charts._display_cell(0.7, 2.5)
    negative_side_col, _ = charts._display_cell(-0.7, 2.5)
    # Scatter: _x = side * -12, so positive side -> negative _x -> LEFT (a
    # LOWER column index in the heat map's left-to-right z-matrix layout).
    assert positive_side_col < negative_side_col, (
        "a positive plate_loc_side must map to a LOWER column (further "
        "left, matching the scatter's negated _x) than a negative one -- "
        f"got positive={positive_side_col}, negative={negative_side_col}")
    # Pin the exact columns too, not just the relative ordering (catches a
    # future change to the binning math that preserves ordering but not
    # magnitude).
    assert (positive_side_col, negative_side_col) == (1, 5)


def test_slaa_location_figure_orientation_matches_scatter():
    """Finding 1 (CRITICAL) regression guard, end to end: a block of strikes
    gained concentrated at a known, real plate_loc_side must land in the
    grid cell `_display_cell` itself computes for that side, and that cell
    must sit on the scatter-matching (left) half of the grid for a positive
    side. Fails against the pre-fix code because `_display_cell(0.7, 2.5)`
    used to compute column 5 (the right half), not column 1."""
    import pandas as pd
    from app.dashboards.catching import charts
    from app.data import called_strike as cs

    rows = [(0.7, 2.5, "StrikeCalled")] * 60          # concentrated signal
    rows += [(-0.9, 0.3, "BallCalled")] * 20           # sparse background
    df = pd.DataFrame(rows, columns=["plate_loc_side", "plate_loc_height", "pitch_call"])
    lk = cs._build_lookup_from_df(df)

    fig = charts.slaa_location_figure(df, lookup=lk)
    z = pd.DataFrame(fig.data[0].z).fillna(0).values
    expected_col, expected_row = charts._display_cell(0.7, 2.5)
    assert z[expected_row][expected_col] > 0, (
        "the strikes-gained signal at side=0.7 must land in the cell "
        "_display_cell computes for that same side")
    assert expected_col < charts._N // 2, (
        "a positive plate_loc_side must land in the LEFT half of the grid "
        "(low column), matching the scatter's negated _x convention")


def test_slaa_location_figure_on_empty_frame_does_not_raise():
    import pandas as pd
    from app.dashboards.catching import charts
    df = pd.DataFrame(columns=["plate_loc_side", "plate_loc_height", "pitch_call"])
    fig = charts.slaa_location_figure(df)
    assert fig is not None


def test_slaa_location_figure_caption_matches_local_slaa_summary():
    """Finding 2 fix: the heat map's own df (whatever scope the caller passed
    -- e.g. a single selected game) may not match the sidebar's season-wide
    SLAA tile, so the figure must caption itself with a LOCAL slaa_summary
    on the SAME df, never implying the (possibly different) sidebar number."""
    import pandas as pd
    from app.dashboards.catching import charts
    from app.data import called_strike as cs
    from app.data import catching_caps

    rows = [(0.0, 2.5, "StrikeCalled")] * 60 + [(0.0, 2.5, "BallCalled")] * 60
    rows += [(9.0, 9.0, "BallCalled")] * 10  # far outside, must still count
    rows += [(None, 2.5, "StrikeCalled")] * 5  # missing location, must NOT count
    df = pd.DataFrame(rows, columns=["plate_loc_side", "plate_loc_height", "pitch_call"])
    lk = cs._build_lookup_from_df(df)

    fig = charts.slaa_location_figure(df, lookup=lk)
    expected = catching_caps.slaa_summary(df, lookup=lk)

    caption = fig.layout.title.subtitle.text
    assert f"{expected['slaa']:+.1f}" in caption
    assert str(expected["taken"]) in caption
    assert expected["taken"] == 130, "the 5 missing-location rows must be excluded"


def test_slaa_location_figure_zone_outline_uses_real_feet_bounds():
    """The zone-outline shape must be drawn at the real strike-zone bounds
    (matching pitching.py's _SZ / bullpen's _ZONE: x0=-0.83,x1=0.83,
    y0=1.5,y1=3.5), not at arbitrary cell-index coordinates -- otherwise the
    box renders as a square regardless of the true (non-square) zone shape."""
    import pandas as pd
    from app.dashboards.catching import charts

    df = pd.DataFrame(columns=["plate_loc_side", "plate_loc_height", "pitch_call"])
    fig = charts.slaa_location_figure(df)
    rects = [s for s in fig.layout.shapes if s.type == "rect"]
    assert len(rects) == 1, "expected exactly one zone-outline rectangle"
    zone = rects[0]
    assert (zone.x0, zone.x1, zone.y0, zone.y1) == (-0.83, 0.83, 1.5, 3.5)


def test_slaa_location_figure_plots_on_real_feet_not_cell_indices():
    """The heatmap trace's x/y coordinates must be real feet (bin centers
    inside/around the +/-0.83 / 1.5-3.5 window), not the default 0..6 index
    positions Plotly would otherwise fall back to."""
    import pandas as pd
    from app.dashboards.catching import charts

    df = pd.DataFrame(columns=["plate_loc_side", "plate_loc_height", "pitch_call"])
    fig = charts.slaa_location_figure(df)
    xs = list(fig.data[0].x)
    ys = list(fig.data[0].y)
    assert max(xs) <= 1.3 and min(xs) >= -1.3, f"x coords look like indices, not feet: {xs}"
    assert max(ys) <= 4.0 and min(ys) >= 1.0, f"y coords look like indices, not feet: {ys}"
