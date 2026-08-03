"""Tests for the Dash bullpen dashboard (selectors, layout, tabs, build)."""
import pandas as pd
import pytest

from app import create_app
from config import Config

GEIS = 824645


@pytest.fixture
def server(tmp_path):
    class T(Config):
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 't.db'}"
    return create_app(T)


def test_resolve_pitcher_player_is_self_only():
    from app.dashboards.bullpen import selectors
    assert selectors.resolve_pitcher(999, is_coach=False, own_trackman_id=None) is None
    assert selectors.resolve_pitcher(999, is_coach=False, own_trackman_id=555) == 555
    assert selectors.resolve_pitcher(999, is_coach=True, own_trackman_id=None) == 999


def test_pitcher_options_coach_nonempty():
    from app.dashboards.bullpen import selectors
    opts = selectors.pitcher_options(is_coach=True, own_trackman_id=None)
    assert opts and {"label", "value"} <= set(opts[0])


def test_session_dropdown_options_labels():
    from app.dashboards.bullpen import selectors
    df = pd.DataFrame({"date": ["2026-05-13", "2026-05-06"], "pitches": [18, 17]})
    opts = selectors.session_dropdown_options(df)
    assert opts[0] == {"label": "2026-05-13 (18)", "value": "2026-05-13"}
    assert selectors.session_dropdown_options(pd.DataFrame(columns=["date", "pitches"])) == []


def _session_df():
    return pd.DataFrame({
        "tagged_pitch_type": ["Fastball", "Fastball", "Slider"],
        "rel_speed": [90.1, 91.0, 82.4], "ind_vert_break": [15.0, 16.1, 2.0],
        "horz_break": [8.0, 9.2, -5.0], "rel_side": [1.9, 2.0, 1.8],
        "rel_height": [6.0, 6.1, 5.9], "plate_loc_side": [0.1, -0.2, 0.3],
        "plate_loc_height": [2.5, 3.0, 1.8]})


def _trend_df():
    return pd.DataFrame({
        "date": ["2026-05-06", "2026-05-13", "2026-05-06", "2026-05-13"],
        "tagged_pitch_type": ["Fastball", "Fastball", "Slider", "Slider"],
        "pitches": [10, 12, 6, 7], "velo_avg": [90.0, 91.0, 82.0, 83.0],
        "velo_max": [92.0, 93.0, 84.0, 85.0], "spin_avg": [2200.0, 2250.0, 2400.0, 2450.0],
        "eff_avg": [95.0, 96.0, 40.0, 42.0], "ivb_avg": [15.0, 16.0, 2.0, 1.0],
        "hb_avg": [8.0, 9.0, -5.0, -6.0], "loc_spread": [0.9, 0.7, 1.2, 1.0]})


def test_session_charts_render():
    from app.dashboards.bullpen import charts
    df = _session_df()
    for fn in (charts.velo_fig, charts.movement_fig, charts.release_fig, charts.location_fig):
        assert fn(df) is not None
        assert fn(pd.DataFrame(columns=df.columns)) is not None  # empty -> empty fig, no raise


def test_trend_fig_all_metrics_render():
    from app.dashboards.bullpen import charts
    df = _trend_df()
    for metric in ("velocity", "spin", "movement", "command"):
        fig = charts.trend_fig(df, metric, active_types=["Fastball", "Slider"])
        assert fig is not None and len(fig.data) >= 1
    # empty / one-type filter still returns a figure
    assert charts.trend_fig(df, "velocity", active_types=[]) is not None
    assert charts.trend_fig(pd.DataFrame(columns=df.columns), "velocity") is not None


def test_df_table_colors_named_column():
    from app.dashboards.bullpen import tables
    from app.reports.plots import color_for
    df = pd.DataFrame({"pitch": ["Fastball", "Slider"], "qty": [10, 5]})
    tbl = tables.df_table(df, id_="t", color_col="pitch")
    colored = {c.get("color") for c in (tbl.style_data_conditional or [])
               if c.get("if", {}).get("column_id") == "pitch"}
    assert color_for("Fastball") in colored and color_for("Slider") in colored


def test_session_detail_render_live():
    from app.dashboards.bullpen.tabs import session_detail
    from app.data import bullpen as B
    s = B.session_options(GEIS, "2025-09-01", "2026-05-13")
    # GEIS has bullpen data in-window; render must not raise and must include charts.
    if s.empty:
        pytest.skip("no in-window sessions for anchor pitcher")
    out = session_detail.render(GEIS, s.iloc[0]["date"])
    assert out is not None


def test_session_detail_empty_states():
    from app.dashboards.bullpen.tabs import session_detail
    assert "Select a pitcher" in str(session_detail.render(None, None))
    assert "session" in str(session_detail.render(GEIS, None)).lower()


def test_trends_render_has_controls_live():
    from app.dashboards.bullpen.tabs import trends
    s = str(trends.render(GEIS, "2025-09-01", "2026-05-13"))
    assert "bp-trend-metric" in s and "bp-trend-active" in s and "bp-trend-body" in s


def test_trends_render_empty_pitcher():
    from app.dashboards.bullpen.tabs import trends
    assert "Select a pitcher" in str(trends.render(None, "2025-09-01", "2026-05-13"))


def test_trends_body_one_session_note():
    from app.dashboards.bullpen.tabs import trends
    one = _trend_df().iloc[[0, 2]].copy()   # both rows share date 2026-05-06
    assert "2 session" in str(trends.body(one, "velocity", ["Fastball", "Slider"])).lower() \
        or "one session" in str(trends.body(one, "velocity", ["Fastball", "Slider"])).lower()


def test_trends_body_two_sessions_renders_graph():
    from app.dashboards.bullpen.tabs import trends
    out = trends.body(_trend_df(), "velocity", ["Fastball", "Slider"])
    assert out is not None and "Graph" in str(type(out)) or "dcc.Graph" in str(out)


def test_sidebar_shows_range_tiles_live():
    from app.dashboards.bullpen import layout
    s = str(layout.sidebar(GEIS, "2025-09-01", "2026-05-13"))
    for label in ("SESSIONS", "PITCHES", "PITCH TYPES", "LAST"):
        assert label in s


def test_serve_layout_wires_tabs_and_window(server):
    import inspect
    from app.dashboards.bullpen import layout
    src = inspect.getsource(layout.serve_layout)
    assert '"session"' in src and '"trends"' in src
    assert "Session Detail" in src and "Development Trends" in src
    assert layout.WINDOW_MIN == "2025-09-01"


def test_register_callbacks_adds_callbacks(server):
    from dash import Dash
    from app.dashboards.bullpen import layout, callbacks
    app = Dash(__name__, server=server, url_base_pathname="/dash/bptest/",
               suppress_callback_exceptions=True)
    app.layout = layout.serve_layout
    before = len(app.callback_map)
    callbacks.register_callbacks(app)
    assert len(app.callback_map) > before
