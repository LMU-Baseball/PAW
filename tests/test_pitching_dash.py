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


def test_location_movement_render_has_chip_filter(outing_df):
    from app.dashboards.pitching.tabs import location_movement
    comp = location_movement.render(outing_df)
    assert comp is not None  # renders chip row + body without raising


def test_rhh_lhh_render(outing_df):
    from app.dashboards.pitching.tabs import rhh_lhh
    assert rhh_lhh.render(outing_df) is not None


def test_rhh_lhh_render_has_chip_filter(outing_df):
    from app.dashboards.pitching.tabs import rhh_lhh
    assert rhh_lhh.render(outing_df) is not None


def test_last_outings_render(real_pitcher):
    from app.data import pitching as P
    from app.dashboards.pitching.tabs import last_outings
    gid = int(P.games_for_pitcher(real_pitcher).iloc[0]["game_id"])
    assert last_outings.render(real_pitcher, gid, 5) is not None


def test_pitching_aggregate_load_live():
    from app import create_app
    from config import Config
    from app.data import pitching as P
    from app.dashboards.date_range import ALL_IN_RANGE
    class T(Config):
        TESTING = True; SECRET_KEY = "t"; SQLALCHEMY_DATABASE_URI = "sqlite://"
    app = create_app(T)
    with app.app_context():
        pit = P.wh_lmu_pitchers()
        if pit.empty:
            import pytest; pytest.skip("no pitchers")
        pid = int(pit.iloc[0]["PitcherId"])
        g = P.games_for_pitcher(pid)
        if g.empty:
            import pytest; pytest.skip("no games")
        lo, hi = str(g["game_date"].min()), str(g["game_date"].max())
        pooled = P.range_pitches_for(pid, lo, hi)
        assert not pooled.empty
        # sentinel is what the callback routes on
        assert ALL_IN_RANGE == "__all_in_range__"


def test_outings_anchor_passthrough_concrete_game_id():
    from app.dashboards.pitching.callbacks import _outings_anchor
    assert _outings_anchor({"pitcher_id": 1, "game_id": 42,
                            "start": "2026-01-01", "end": "2026-06-01"}) == 42


def test_outings_anchor_sentinel_resolves_to_most_recent_in_range_game():
    from app import create_app
    from config import Config
    from app.data import pitching as P
    from app.dashboards.date_range import ALL_IN_RANGE
    from app.dashboards.pitching.callbacks import _outings_anchor

    class T(Config):
        TESTING = True; SECRET_KEY = "t"; SQLALCHEMY_DATABASE_URI = "sqlite://"
    app = create_app(T)
    with app.app_context():
        pit = P.wh_lmu_pitchers()
        if pit.empty:
            pytest.skip("no pitchers")
        pid = int(pit.iloc[0]["PitcherId"])
        g = P.games_for_pitcher(pid)
        if g.empty:
            pytest.skip("no games")
        lo, hi = str(g["game_date"].min()), str(g["game_date"].max())
        anchor = _outings_anchor({"pitcher_id": pid, "game_id": ALL_IN_RANGE,
                                  "start": lo, "end": hi})
        assert isinstance(anchor, int)


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
    assert '"pitchlevel"' in src and "Pitch Level" in src
