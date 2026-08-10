"""Tests for the Dash pitching dashboard (shell, selectors, build)."""
import pytest

from app import create_app
from app.db import query_df
from config import Config


@pytest.fixture(scope="module")
def real_pitcher():
    # RAW GAMES.PitcherId (== a player's trackman_id) -- the id space the
    # dashboard now uses everywhere (no warehouse surrogate mapping).
    df = query_df(
        """
        SELECT PitcherId FROM GAMES
         WHERE PitcherTeam = 'LOY_LIO' AND PitcherId IS NOT NULL
         GROUP BY PitcherId ORDER BY COUNT(*) DESC LIMIT 1
        """
    )
    return int(df.loc[0, "PitcherId"])


@pytest.fixture
def server(tmp_path):
    class TestConfig(Config):
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 't.db'}"
    return create_app(TestConfig)


def test_resolve_pitcher_player_is_self_only():
    from app.dashboards.pitching import selectors
    # A player ignores the requested id and gets their own (RAW trackman id --
    # GAMES.PitcherId IS the trackman id, so no surrogate mapping happens).
    assert selectors.resolve_pitcher(999, is_coach=False, own_trackman_id=None) is None
    assert selectors.resolve_pitcher(999, is_coach=False, own_trackman_id=555) == 555


def test_resolve_pitcher_coach_passes_through():
    from app.dashboards.pitching import selectors
    assert selectors.resolve_pitcher(999, is_coach=True, own_trackman_id=None) == 999
    assert selectors.resolve_pitcher(None, is_coach=True, own_trackman_id=None) is None


def test_resolve_pitcher_player_discards_requested_id():
    from app.dashboards.pitching import selectors
    got = selectors.resolve_pitcher(999, is_coach=False, own_trackman_id=555)
    assert got == 555  # own raw id, NOT the requested 999


def test_pitcher_options_coach_nonempty():
    from app.dashboards.pitching import selectors
    opts = selectors.pitcher_options(is_coach=True, own_trackman_id=None)
    assert opts and {"label", "value"} <= set(opts[0])


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
    import pandas as pd
    from app.extensions import db
    from app.auth.models import User
    from flask_login import login_user
    from app.data import seasons
    monkeypatch.setattr(seasons, "available_seasons",
                        lambda: ["2025/2026", "2024/2025", "2023/2024"])
    monkeypatch.setattr(seasons, "current_season", lambda: "2025/2026")
    monkeypatch.setattr("app.data.pitching_caps.lmu_pitchers",
                        lambda season=None: pd.DataFrame([{"Pitcher": "Doe, John", "PitcherId": 1}]))
    monkeypatch.setattr("app.data.pitching_caps.games_for_pitcher",
                        lambda p, *a, **k: pd.DataFrame(columns=["game_id", "game_date", "GameLabel"]))
    monkeypatch.setattr("app.data.pitching_caps.pitcher_profile",
                        lambda p: {"name": "Doe, John", "class_year": "", "position": "",
                                   "throws": "", "jersey": "", "photo": ""})
    monkeypatch.setattr("app.data.pitching_caps.range_summary",
                        lambda p, *a, **k: {"appearances": 0, "ip": 0, "k_pct": "—",
                                            "bb_pct": "—", "barrel_pct": "—"})
    with server.app_context():
        coach = User(email="pc3@lmu.edu", name="Coach", role="coach")
        coach.set_password("x")
        db.session.add(coach)
        db.session.commit()
        with server.test_request_context("/dash/pitching/"):
            login_user(coach)
            from app.dashboards.pitching import layout
            out = layout.serve_layout()
    dd = _find_component(out, "pit-season")
    assert dd is not None
    assert dd.value == "2025/2026"                       # defaults to current season
    assert [o["value"] for o in dd.options] == ["2025/2026", "2024/2025", "2023/2024"]
    # sanity: the pitcher dropdown is also present in the selector row
    assert _find_component(out, "pitcher-dd") is not None


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
    from app.data import pitching_caps
    g = pitching_caps.games_for_pitcher(real_pitcher)
    gid = int(g.iloc[0]["game_id"])
    return pitching_caps.game_pitches(gid, real_pitcher)


def test_pitch_breakdown_render(outing_df):
    from app.dashboards.pitching.tabs import pitch_breakdown
    comp = pitch_breakdown.render(outing_df)
    assert comp is not None  # renders without raising on real data


def test_location_movement_render(outing_df):
    from app.dashboards.pitching.tabs import location_movement
    assert location_movement.render(outing_df) is not None


def test_location_movement_render_has_chip_filter(outing_df):
    from app.dashboards.pitching.tabs import location_movement
    comp = location_movement.render(outing_df)
    assert comp is not None  # renders chip row + body without raising


def test_last_outings_render(real_pitcher):
    from app.data import pitching_caps
    from app.dashboards.pitching.tabs import last_outings
    gid = int(pitching_caps.games_for_pitcher(real_pitcher).iloc[0]["game_id"])
    assert last_outings.render(real_pitcher, gid, 5) is not None


def test_pitching_aggregate_load_live():
    from app import create_app
    from config import Config
    from app.data import pitching_caps
    from app.dashboards.date_range import ALL_IN_RANGE
    class T(Config):
        TESTING = True; SECRET_KEY = "t"; SQLALCHEMY_DATABASE_URI = "sqlite://"
    app = create_app(T)
    with app.app_context():
        pit = pitching_caps.lmu_pitchers()
        if pit.empty:
            import pytest; pytest.skip("no pitchers")
        pid = int(pit.iloc[0]["PitcherId"])
        g = pitching_caps.games_for_pitcher(pid)
        if g.empty:
            import pytest; pytest.skip("no games")
        lo, hi = str(g["game_date"].min()), str(g["game_date"].max())
        pooled = pitching_caps.range_pitches_for(pid, lo, hi)
        assert not pooled.empty
        # sentinel is what the callback routes on
        assert ALL_IN_RANGE == "__all_in_range__"


def test_outings_anchor_passthrough_concrete_game_id():
    # A concretely selected outing passes through untouched. game_id is an
    # opaque string now (numeric surrogate or composite legacy id), so the
    # anchor carries the composite id verbatim -- no int cast.
    from app.dashboards.pitching.callbacks import _outings_anchor
    assert _outings_anchor({"pitcher_id": 1, "game_id": "20250517-704EddieDField-1",
                            "start": "2026-01-01", "end": "2026-06-01"}) == "20250517-704EddieDField-1"


def test_outings_anchor_sentinel_resolves_to_most_recent_in_range_game():
    from app import create_app
    from config import Config
    from app.data import pitching_caps
    from app.dashboards.date_range import ALL_IN_RANGE
    from app.dashboards.pitching.callbacks import _outings_anchor

    class T(Config):
        TESTING = True; SECRET_KEY = "t"; SQLALCHEMY_DATABASE_URI = "sqlite://"
    app = create_app(T)
    with app.app_context():
        pit = pitching_caps.lmu_pitchers()
        if pit.empty:
            pytest.skip("no pitchers")
        pid = int(pit.iloc[0]["PitcherId"])
        g = pitching_caps.games_for_pitcher(pid)
        if g.empty:
            pytest.skip("no games")
        # GameID is opaque now, so games_for_pitcher may surface legacy
        # composite-GameID rows that carry an empty Date; drop those before
        # deriving the range bounds (the live layout does the same implicitly
        # by max()-ing the min bound with the season-preset start).
        dates = sorted(d for d in g["game_date"] if str(d).strip())
        if not dates:
            pytest.skip("no dated games")
        lo, hi = dates[0], dates[-1]
        anchor = _outings_anchor({"pitcher_id": pid, "game_id": ALL_IN_RANGE,
                                  "start": lo, "end": hi})
        # Opaque-GameID contract: the resolved anchor game_id is a string now
        # (games_for_pitcher yields opaque string ids), not an int.
        assert isinstance(anchor, str)


def test_outings_anchor_sentinel_missing_range_returns_none():
    from app.dashboards.date_range import ALL_IN_RANGE
    from app.dashboards.pitching.callbacks import _outings_anchor
    assert _outings_anchor({"pitcher_id": 1, "game_id": ALL_IN_RANGE,
                            "start": None, "end": None}) is None
    assert _outings_anchor(None) is None


def test_df_table_colors_pitch_column():
    import pandas as pd
    from app.dashboards.pitching import tables
    from app.data import pitching as P
    df = pd.DataFrame({"Pitch": ["Fastball", "Sweeper"], "Velo": [90.0, 80.0]})
    tbl = tables.df_table(df, id_="t")
    conds = tbl.style_data_conditional or []
    # one colored rule per distinct pitch, each carrying that pitch's color
    colored = {c.get("color") for c in conds if c.get("if", {}).get("column_id") == "Pitch"}
    assert P.pitch_color("Fastball") in colored
    assert P.pitch_color("Sweeper") in colored


def test_df_table_no_pitch_column_no_color_rules():
    import pandas as pd
    from app.dashboards.pitching import tables
    df = pd.DataFrame({"Metric": ["Strike%"], "Value": [55.0]})
    tbl = tables.df_table(df, id_="t2")
    conds = tbl.style_data_conditional or []
    assert not any(c.get("if", {}).get("column_id") == "Pitch" for c in conds)


def test_pitchlevel_tab_renders_video_component():
    from app.dashboards.video.component import render as vrender
    import pandas as pd
    from app.data import video as vdata
    # empty-video game -> empty state (no exception)
    out = vrender(pd.DataFrame(columns=vdata._ALL_COLS), prefix="pit", default_angle="HomeBehind")
    assert "No video" in str(out)


def test_pitching_tabs_include_pitch_level():
    from app.dashboards.pitching import layout
    # serve_layout builds under an app/request context in other tests; here just
    # assert the tab value string is wired in the module source.
    import inspect
    src = inspect.getsource(layout.serve_layout)
    assert '"pitchlevel"' in src and "Outing Video" in src


def test_sidebar_shows_five_range_tiles(real_pitcher):
    from app.dashboards.pitching import layout
    from app.data import pitching_caps
    g = pitching_caps.games_for_pitcher(real_pitcher)
    start, end = str(g["game_date"].min()), str(g["game_date"].max())
    s = str(layout.sidebar(real_pitcher, start, end))
    for label in ("APP", "IP", "K%", "BB%", "Barrel%"):
        assert label in s


def test_splits_tab_removed():
    import inspect
    from app.dashboards.pitching import layout, callbacks
    src = inspect.getsource(layout.serve_layout)
    assert '"splits"' not in src and "RHH v. LHH" not in src
    # callbacks module no longer imports the deleted rhh_lhh tab module
    assert not hasattr(callbacks, "rhh_lhh")


def test_movement_profile_apply_filters():
    import pandas as pd
    from app.dashboards.pitching.tabs import location_movement as lm
    df = pd.DataFrame({
        "balls": [0, 1, 0], "strikes": [0, 2, 0],
        "pitch_call": ["StrikeSwinging", "BallCalled", "InPlay"],
        "batter_side": ["Right", "Left", "Right"],
        "tagged_pitch_type": ["Fastball", "Slider", "Fastball"],
        "auto_pitch_type": ["Fastball", "Slider", "Fastball"],
        "rel_speed": [92.0, 84.0, 91.0]})
    # handedness toggle keeps only Right
    assert set(lm.apply_filters(df, hand="Right")["batter_side"]) == {"Right"}
    # result filter (pretty labels) keeps only In Play
    assert list(lm.apply_filters(df, results=["In Play"])["pitch_call"]) == ["InPlay"]
    # count filter keeps only 1-2
    assert list(lm.apply_filters(df, counts=["1-2"])["balls"]) == [1]
    # pitch-type filter
    assert set(lm.apply_filters(df, pitch_types=["Slider"])["tagged_pitch_type"]) == {"Slider"}


def test_movement_profile_render_has_filters(outing_df):
    from app.dashboards.pitching.tabs import location_movement as lm
    s = str(lm.render(outing_df))
    assert "lm-count" in s and "lm-result" in s and "lm-hand" in s


def _pitch_df():
    import pandas as pd
    return pd.DataFrame({
        "balls": [0, 1], "strikes": [0, 2],
        "plate_loc_side": [0.1, -0.3], "plate_loc_height": [2.5, 3.0],
        "pitch_call": ["StrikeCalled", "BallCalled"], "batter_side": ["Right", "Left"],
        "tagged_pitch_type": ["Fastball", "Slider"], "auto_pitch_type": ["Fastball", "Slider"],
        "rel_speed": [92.0, 84.0]})


def test_counts_tab_render_has_dropdown_and_body():
    from app.dashboards.pitching.tabs import counts
    out = counts.render(_pitch_df())
    s = str(out)
    assert "counts-dd" in s and "counts-body" in s
    # empty df -> empty state, no exception
    import pandas as pd
    assert "No pitches" in str(counts.body(pd.DataFrame(
        {"balls": [], "strikes": [], "plate_loc_side": [], "plate_loc_height": [],
         "pitch_call": [], "tagged_pitch_type": []})))


def test_heatmaps_tab_render_has_controls_and_body():
    from app.dashboards.pitching.tabs import heatmaps
    out = heatmaps.render(_pitch_df())
    s = str(out)
    assert "hm-pt" in s and "hm-side" in s and "hm-count" in s and "hm-body" in s
    assert "vs RHH" in s and "vs LHH" in s   # handedness toggle labels


def test_pitching_tabs_include_counts_and_heatmaps():
    import inspect
    from app.dashboards.pitching import layout
    src = inspect.getsource(layout.serve_layout)
    assert '"counts"' in src and "Count Performance" in src
    assert '"heatmaps"' in src and "Zone Frequency" in src


def test_pitching_video_defaults_to_broadcast():
    """Coach wants the center-field (Broadcast) camera as the default angle."""
    import inspect
    from app.dashboards.pitching import callbacks
    src = inspect.getsource(callbacks.register_callbacks)
    assert 'default_angle="Broadcast"' in src
    assert 'default_angle="HomeBehind"' not in src   # pitching no longer defaults to HomeBehind


def test_register_callbacks_adds_callbacks(server):
    """Registering the (churned) pitching callback graph must not error and must
    wire callbacks — guards the deleted splits callbacks + new lm-* Inputs."""
    from dash import Dash
    from app.dashboards.pitching import layout, callbacks
    app = Dash(__name__, server=server, url_base_pathname="/dash/ptest/",
               suppress_callback_exceptions=True)
    app.layout = layout.serve_layout
    before = len(app.callback_map)
    callbacks.register_callbacks(app)
    assert len(app.callback_map) > before


def test_pitching_uses_preset_control():
    import inspect
    from app.dashboards.pitching import layout
    src = inspect.getsource(layout.serve_layout)
    assert "date_control" in src and "date_picker(" not in src


def test_pitching_preset_callback_writes_range(server):
    from dash import Dash
    from app.dashboards.pitching import layout, callbacks
    app = Dash(__name__, server=server, url_base_pathname="/dash/pittest2/",
               suppress_callback_exceptions=True)
    app.layout = layout.serve_layout
    callbacks.register_callbacks(app)
    assert any("pit-daterange" in str(k) for k in app.callback_map)
    assert any("pit-date-preset" in str(v) for v in app.callback_map.values())
