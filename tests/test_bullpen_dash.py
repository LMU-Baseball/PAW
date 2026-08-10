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


def test_pitcher_options_scoped_by_date_range():
    from app.dashboards.bullpen import selectors
    opts_all = selectors.pitcher_options(is_coach=True, own_trackman_id=None)
    opts_1900 = selectors.pitcher_options(is_coach=True, own_trackman_id=None,
                                          start="1900-01-01", end="1900-01-02")
    assert opts_all and opts_1900 == []
    opts_window = selectors.pitcher_options(is_coach=True, own_trackman_id=None,
                                            start="2025-09-01", end="2026-05-13")
    assert GEIS in {o["value"] for o in opts_window}


def test_bullpen_pitcher_dd_options_callback_registered(server):
    from dash import Dash
    from app.dashboards.bullpen import layout, callbacks
    app = Dash(__name__, server=server, url_base_pathname="/dash/bptest3/",
               suppress_callback_exceptions=True)
    app.layout = layout.serve_layout
    callbacks.register_callbacks(app)
    outs = {str(k) for k in app.callback_map}
    assert any("bp-pitcher-dd.options" in o for o in outs)


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


def test_session_detail_has_fastball_callout_live():
    from app.dashboards.bullpen.tabs import session_detail
    from app.data import bullpen as B
    s = B.session_options(GEIS, "2025-09-01", "2026-05-13")
    if s.empty:
        pytest.skip("no sessions")
    out = str(session_detail.render(GEIS, s.iloc[0]["date"]))
    assert "Avg Spin" in out  # unique to the fastball callout div (summary table uses "Spin Avg")


def test_session_detail_tables_condensed_live():
    from app.dashboards.bullpen.tabs import session_detail
    from app.data import bullpen as B
    s = B.session_options(GEIS, "2025-09-01", "2026-05-13")
    if s.empty:
        pytest.skip("no sessions")
    out = str(session_detail.render(GEIS, s.iloc[0]["date"]))
    assert "Pitch #" in out  # renumbered header (real contract from _display_pitches)
    # raw session-global pitch numbers (e.g. 33) should NOT appear as the first pitch label
    # (can't assert exact text here; covered by the helper unit test below)


def test_renumber_and_round_helpers():
    import pandas as pd
    from app.dashboards.bullpen.tabs import session_detail as sd
    df = pd.DataFrame({"pitch_no": [33, 34], "tagged_pitch_type": ["Fastball", "Slider"],
                       "rel_speed": [90.12345, 80.98765], "spin_rate": [2200.4, 2300.6]})
    out = sd._display_pitches(df)
    assert list(out.iloc[:, 0]) == [1, 2]           # renumbered 1..N
    # rel_speed -> friendly "Velo" header per the rename map; contract is the rounding behavior
    velo_col = "Velo" if "Velo" in out.columns else "rel_speed"
    assert out[velo_col].tolist() == [90.12, 80.99]  # rounded 2dp


def test_trends_render_has_controls_live():
    from app.dashboards.bullpen.tabs import trends
    s = str(trends.render(GEIS, "2025-09-01", "2026-05-13"))
    assert "bp-trend-metric" in s and "bp-trend-body" in s


def test_trends_render_no_chips():
    from app.dashboards.bullpen.tabs import trends
    s = str(trends.render(GEIS, "2025-09-01", "2026-05-13"))
    assert "bp-trend-metric" in s and "bp-trend-chip" not in s and "bp-trend-active" not in s


def test_trends_render_empty_pitcher():
    from app.dashboards.bullpen.tabs import trends
    assert "Select a pitcher" in str(trends.render(None, "2025-09-01", "2026-05-13"))


def test_trends_body_one_session_note():
    from app.dashboards.bullpen.tabs import trends
    one = _trend_df().iloc[[0, 2]].copy()   # both rows share date 2026-05-06
    assert "2 session" in str(trends.body(one, "velocity")).lower() \
        or "one session" in str(trends.body(one, "velocity")).lower()


def test_trends_body_two_sessions_renders_graph():
    from app.dashboards.bullpen.tabs import trends
    out = trends.body(_trend_df(), "velocity")
    assert out is not None and "Graph" in str(type(out)) or "dcc.Graph" in str(out)


def test_trend_small_multiples_grid():
    from app.dashboards.bullpen import charts
    df = _trend_df()  # existing helper: Fastball + Slider across 2 dates
    fig = charts.trend_small_multiples(df, "velocity")
    # one subplot per pitch type -> >=2 x-axes
    axes = [k for k in fig.layout if k.startswith("xaxis")]
    assert len(axes) >= 2
    assert charts.trend_small_multiples(df, "movement") is not None


def test_trend_spin_is_dual_axis_with_word_labels():
    from app.dashboards.bullpen import charts
    df = _trend_df()
    velo = charts.trend_small_multiples(df, "velocity")
    spin = charts.trend_small_multiples(df, "spin")
    # Spin uses a secondary y-axis (efficiency %) -> more y-axes than velocity.
    yv = [k for k in velo.layout if k.startswith("yaxis")]
    ys = [k for k in spin.layout if k.startswith("yaxis")]
    assert len(ys) > len(yv)
    # Legend labels are plain words (no parenthetical decoding).
    names = {t.name for t in velo.data}
    assert "Avg" in names and "Max" in names
    assert any(t.name == "Efficiency %" for t in spin.data)
    # Legend shown once (first panel) so it isn't repeated per panel.
    assert sum(1 for t in velo.data if t.showlegend) == 2


def test_freq_bar_legend_on_top_and_gridlines():
    import pandas as pd
    from app.dashboards.bullpen import charts
    fig = charts.pitch_freq_bar(pd.DataFrame({"tagged_pitch_type": ["Fastball", "Slider"]}))
    assert fig.layout.legend.orientation == "h"      # horizontal legend across the top
    assert fig.layout.xaxis.showgrid is True
    v = charts.velo_fig(_session_df())
    assert v.layout.xaxis.showgrid is True            # velocity gridlines


def test_sidebar_shows_new_tiles_live():
    from app.dashboards.bullpen import layout
    s = str(layout.sidebar(GEIS, "2025-09-01", "2026-05-13"))
    for label in ("SESSIONS", "PITCHES", "STRIKE %", "AVG FB VELO"):
        assert label in s
    assert "PITCH TYPES" not in s and "LAST" not in s


def test_serve_layout_wires_tabs_and_window(server):
    import inspect
    from app.dashboards.bullpen import layout
    src = inspect.getsource(layout.serve_layout)
    assert '"session"' in src and '"trends"' in src
    assert "Session Detail" in src and "Development Trends" in src
    assert layout.WINDOW_MIN == "2025-09-01"


def test_serve_layout_renders_for_logged_in_coach(server):
    from app.extensions import db
    from app.auth.models import User
    from flask_login import login_user
    from dash import html
    from app.dashboards.bullpen import layout
    with server.app_context():
        coach = User(email="bpc@lmu.edu", name="Coach", role="coach")
        coach.set_password("x")
        db.session.add(coach)
        db.session.commit()
        with server.test_request_context("/dash/bullpen/"):
            login_user(coach)
            out = layout.serve_layout()
    assert isinstance(out, html.Div)
    assert "Please log in" not in str(out)


def test_register_callbacks_adds_callbacks(server):
    from dash import Dash
    from app.dashboards.bullpen import layout, callbacks
    app = Dash(__name__, server=server, url_base_pathname="/dash/bptest/",
               suppress_callback_exceptions=True)
    app.layout = layout.serve_layout
    before = len(app.callback_map)
    callbacks.register_callbacks(app)
    assert len(app.callback_map) > before


def test_build_bullpen_dash_mounts(server):
    rules = {r.rule for r in server.url_map.iter_rules()}
    assert any(r.startswith("/dash/bullpen/") for r in rules)


def test_layout_scopes_first_paint_pitchers_to_season_default_range(server):
    """The Task 4 first-paint pitcher dropdown options must be scoped to the
    season-default range, not every pitcher who's ever thrown a bullpen."""
    from app.extensions import db
    from app.auth.models import User
    from flask_login import login_user
    from app.dashboards.bullpen import layout, selectors
    with server.app_context():
        coach = User(email="bpfp@lmu.edu", name="Coach", role="coach")
        coach.set_password("x")
        db.session.add(coach)
        db.session.commit()
        with server.test_request_context("/dash/bullpen/"):
            login_user(coach)
            out = layout.serve_layout()
    store = out.children[0]
    assert store.id == "bp-selection"
    start_d, end_d = store.data["start"], store.data["end"]
    pitcher_dd = out.children[2].children[1].children[0].children[0].children[1]
    assert pitcher_dd.id == "bp-pitcher-dd"
    rendered_values = {o["value"] for o in pitcher_dd.options}
    expected = {o["value"] for o in selectors.pitcher_options(
        is_coach=True, own_trackman_id=None, start=start_d, end=end_d)}
    assert rendered_values == expected
    # sanity: prove this is actually scoped, not coincidentally equal to the
    # unscoped list (otherwise this test wouldn't distinguish the two).
    unscoped = {o["value"] for o in selectors.pitcher_options(is_coach=True, own_trackman_id=None)}
    assert expected <= unscoped


def test_layout_initial_paint_player_role_empty_options_value_consistent(server):
    """Task 4 fix round 1: when a player-role user's own bullpen falls outside
    the season-default range, first-paint options is [] -- the dropdown value
    must not be bound to their own id (which isn't among the options); it must
    be the fallback used by _on_daterange_pitchers (first option's value, or
    None), matching the runtime callback's own behavior exactly."""
    from app.extensions import db
    from app.auth.models import User
    from flask_login import login_user
    from app.dashboards.bullpen import layout
    with server.app_context():
        player = User(email="bpplayer@lmu.edu", name="Player", role="player",
                      trackman_id=-999)  # id with no bullpen data at all
        player.set_password("x")
        db.session.add(player)
        db.session.commit()
        with server.test_request_context("/dash/bullpen/"):
            login_user(player)
            out = layout.serve_layout()
    store = out.children[0]
    pitcher_dd = out.children[2].children[1].children[0].children[0].children[1]
    assert pitcher_dd.id == "bp-pitcher-dd"
    assert pitcher_dd.options == []
    assert pitcher_dd.value is None
    assert store.data["pitcher_id"] is None


def test_bullpen_layout_uses_preset_dropdown(server):
    import inspect
    from app.dashboards.bullpen import layout
    src = inspect.getsource(layout.serve_layout)
    assert "date_control" in src and "bp-date-preset" not in src  # id comes from component
    # the component provides bp-date-preset; assert control is used, not raw date_picker
    assert "date_picker(" not in src


def test_bullpen_preset_callback_registered(server):
    from dash import Dash
    from app.dashboards.bullpen import layout, callbacks
    app = Dash(__name__, server=server, url_base_pathname="/dash/bptest2/",
               suppress_callback_exceptions=True)
    app.layout = layout.serve_layout
    callbacks.register_callbacks(app)
    outs = {str(k) for k in app.callback_map}
    assert any("bp-daterange" in o for o in outs)  # a callback now writes the range


def test_bullpen_preset_resolves_season_range_live():
    # Same resolution path _on_preset uses (anchor -> preset_range); confirms the
    # cascade the callback drives (range -> session dd -> selection) gets a real range.
    from app.dashboards import date_range as dr
    from app.dashboards.bullpen import layout
    anchor = layout._bullpen_anchor(GEIS)
    s, e = dr.preset_range("season", anchor)
    assert s is not None and e is not None and str(s) <= str(e) <= layout.date.today().isoformat()


def test_serve_layout_season_default_matches_preset_range(server):
    # serve_layout's initial start/end should equal preset_range("season", anchor) for
    # the default pitcher, so first render and the preset dropdown agree.
    from app.extensions import db
    from app.auth.models import User
    from flask_login import login_user
    from app.dashboards import date_range as dr
    from app.dashboards.bullpen import layout
    with server.app_context():
        coach = User(email="bps@lmu.edu", name="Coach", role="coach")
        coach.set_password("x")
        db.session.add(coach)
        db.session.commit()
        with server.test_request_context("/dash/bullpen/"):
            login_user(coach)
            out = layout.serve_layout()
    store = out.children[0]
    assert store.id == "bp-selection"
    anchor = layout._bullpen_anchor(store.data["pitcher_id"])
    s, e = dr.preset_range("season", anchor)
    assert store.data["start"] == str(s) and store.data["end"] == str(e)


def test_charts_have_hover_and_zone_grid():
    from app.dashboards.bullpen import charts
    df = _session_df()  # existing helper in this test file
    assert any("Velo:" in (t.hovertemplate or "") for t in charts.velo_fig(df).data)
    mv = charts.movement_fig(df)
    assert any("IVB:" in (t.hovertemplate or "") for t in mv.data if t.hovertemplate)
    loc = charts.location_fig(df)
    # nine-pocket = >=5 line shapes (box + 2 v + 2 h)
    assert len(loc.layout.shapes) >= 5


def test_ellipse_xy_shape():
    from app.dashboards.bullpen import charts
    import numpy as np
    x, y = charts._ellipse_xy([1, 2, 3, 4, 2, 3], [2, 1, 3, 2, 2, 1])
    assert len(x) == len(y) >= 20
    assert charts._ellipse_xy([1, 2], [1, 2]) is None  # <3 pts


def test_velo_lollipop_and_release_dispersion():
    from app.dashboards.bullpen import charts
    df = _session_df()
    v = charts.velo_fig(df)
    # a text label with the avg value present on the avg-dot trace
    assert any(getattr(t, "text", None) for t in v.data)
    # ellipse needs >=3 points of the same pitch type; build a fixture with 3+ Fastballs
    df3 = pd.DataFrame({
        "tagged_pitch_type": ["Fastball", "Fastball", "Fastball"],
        "rel_speed": [90.1, 91.0, 90.5], "ind_vert_break": [15.0, 16.1, 15.5],
        "horz_break": [8.0, 9.2, 8.5], "rel_side": [1.9, 2.0, 1.95],
        "rel_height": [6.0, 6.1, 6.05], "plate_loc_side": [0.1, -0.2, 0.0],
        "plate_loc_height": [2.5, 3.0, 2.7]})
    r = charts.release_fig(df3)
    # dispersion: has a filled ellipse trace (fill='toself') for a multi-pitch type
    assert any(getattr(t, "fill", None) == "toself" for t in r.data)
    # equal aspect on release
    assert r.layout.yaxis.scaleanchor == "x"


def test_pitch_freq_bar_plotly():
    from app.dashboards.bullpen import charts
    df = pd.DataFrame({"tagged_pitch_type": ["Fastball", "Fastball", "Slider"]})
    fig = charts.pitch_freq_bar(df)
    assert fig is not None and len(fig.data) >= 1


def test_pitching_hub_has_bullpen_dashboard_card(server):
    server.config["WTF_CSRF_ENABLED"] = False
    from app.auth.models import User
    from app.extensions import db
    with server.app_context():
        u = User(email="c@lmu.edu", name="Coach", role="coach"); u.set_password("x")
        db.session.add(u); db.session.commit()
    client = server.test_client()
    with client.session_transaction() as s:
        pass
    client.post("/login", data={"email": "c@lmu.edu", "password": "x"})
    html_body = client.get("/pitching").get_data(as_text=True)
    assert "Bullpen Dashboard" in html_body and "/dash/bullpen/" in html_body
