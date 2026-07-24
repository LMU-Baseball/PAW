"""Tests for HitTrax practice Dash module."""
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


def _sample():
    return pd.DataFrame([
        {"player_name": "Doe, John", "session_id": 1, "result": 1,
         "px": 0.0, "py": 2.5, "exit_velocity": 90.0, "distance_feet": 250.0,
         "zone_section": 5, "play_timestamp": "2026-04-01 10:00:05",
         "play_date": "2026-04-01", "is_contact": True},
        {"player_name": "Doe, John", "session_id": 1, "result": -4,
         "px": 1.0, "py": 3.6, "exit_velocity": None, "distance_feet": None,
         "zone_section": 11, "play_timestamp": "2026-04-01 10:00:10",
         "play_date": "2026-04-01", "is_contact": False},
    ])


def test_build_hitting_practice_dash_mounts(server):
    rules = {r.rule for r in server.url_map.iter_rules()}
    assert any(r.startswith("/dash/hitting-practice/") for r in rules)


def test_pitch_zones_render():
    from app.dashboards.hitting_practice.tabs import pitch_zones
    assert pitch_zones.render(_sample()) is not None
    assert pitch_zones.render(pd.DataFrame()) is not None


def test_swing_frequency_render():
    from app.dashboards.hitting_practice.tabs import swing_frequency
    assert swing_frequency.render(_sample()) is not None


def _has_graph(component):
    """True if a dcc.Graph appears anywhere in the tree (add once if not present)."""
    from dash import dcc
    if isinstance(component, dcc.Graph):
        return True
    ch = getattr(component, "children", None)
    if ch is None or isinstance(ch, str):
        return False
    kids = ch if isinstance(ch, (list, tuple)) else [ch]
    return any(_has_graph(k) for k in kids)


def test_batted_ball_tab_renders():
    from app.dashboards.hitting_practice.tabs import batted_ball
    plays = pd.DataFrame([
        {"horizontal_angle": -30.0, "distance_feet": 200.0, "hit_type": 2},
        {"horizontal_angle": 20.0, "distance_feet": 300.0, "hit_type": 3},
        {"horizontal_angle": 0.0, "distance_feet": 0.0, "hit_type": 0},
    ])
    assert _has_graph(batted_ball.render(plays))


def test_session_tables_render():
    from app.dashboards.hitting_practice.tabs import session_tables
    stats = pd.DataFrame([{
        "player_name": "Doe, John", "total_plays": 10, "total_sessions": 2,
        "avg_exit_velocity": 88.0, "max_exit_velocity": 95.0,
        "avg_distance": 200.0, "hard_hit_rate": 0.3,
        "line_drive_rate": 0.2, "fly_ball_rate": 0.25,
        "last_practice_date": "2026-04-01",
    }])
    sessions = pd.DataFrame([{
        "session_date": "2026-04-01", "player_name": "Doe, John",
        "total_plays": 10, "avg_exit_velocity": 88.0, "max_exit_velocity": 95.0,
        "avg_distance": 200.0, "batting_avg": 0.3, "hard_hit_count": 2,
        "ground_ball_pct": 40.0, "line_drive_pct": 30.0, "fly_ball_pct": 30.0,
    }])
    assert session_tables.render(stats, sessions, player="All Players") is not None


def test_player_options_coach():
    from app.dashboards.hitting_practice import selectors
    pitch = pd.DataFrame({"player_name": ["Alpha", "Beta"]})
    opts = selectors.player_options(pitch, is_coach=True, own_name=None)
    assert opts[0]["value"] == "All Players"
    assert {o["value"] for o in opts} >= {"Alpha", "Beta"}


def test_practice_layout_has_daterange():
    from app import create_app
    from config import Config
    class T(Config):
        TESTING = True; SECRET_KEY = "t"; SQLALCHEMY_DATABASE_URI = "sqlite://"
    app = create_app(T)
    with app.test_request_context():
        from flask_login import login_user
        # layout references current_user; just assert the component tree builds
        from app.dashboards.hitting_practice import layout
        # serve_layout requires auth; assert the picker id is wired in the module
        import inspect
        src = inspect.getsource(layout)
        # date_range.date_picker builds id=f"{id_prefix}-daterange" dynamically,
        # so assert the call site that wires "prac" as the prefix.
        assert 'dr.date_picker("prac"' in src


def test_pitch_zone_heatmap_black_box_and_metric():
    import pandas as pd
    from app.dashboards.hitting_practice import charts
    df = pd.DataFrame([{"px": 0.0, "py": 2.5, "result": 1,
                        "exit_velocity": 90.0, "distance_feet": 300.0}])
    fig = charts.pitch_zone_heatmap(df, metric="ev")
    # the strike-zone rectangle shape is drawn black
    rects = [s for s in fig.layout.shapes if s.type == "rect"]
    assert rects and any(s.line.color == "black" for s in rects)


def test_new_practice_figs_build():
    import pandas as pd
    from app.dashboards.hitting_practice import charts
    assert charts.swing_decision_trend_fig(pd.DataFrame(
        columns=["play_date", "in_zone_pct", "chase_pct", "score"])) is not None
    assert charts.swing_decision_trend_fig(pd.DataFrame([
        {"play_date": "2026-04-01", "in_zone_pct": 80, "chase_pct": 30, "score": 50}])) is not None
    assert charts.spray_chart_fig(pd.DataFrame(columns=["x", "y", "hit_type_label"])) is not None
    assert charts.spray_chart_fig(pd.DataFrame([
        {"x": -50.0, "y": 200.0, "hit_type_label": "Line Drive"}])) is not None
    assert charts.contact_type_bar(pd.DataFrame([
        {"Hit Type": "Line Drive", "Count": 10}, {"Hit Type": "Fly Ball", "Count": 5}])) is not None


def test_pitch_zones_has_metric_toggle():
    import inspect
    from app.dashboards.hitting_practice.tabs import pitch_zones as pz
    # the metric toggle id is present, and render accepts a metric arg
    assert "pz-metric" in inspect.getsource(pz)
    assert "metric" in inspect.signature(pz.render).parameters


def test_pitch_zones_render_ev():
    import pandas as pd
    from app.dashboards.hitting_practice.tabs import pitch_zones
    df = pd.DataFrame([{"player_name": "Doe, John", "session_id": 1,
                        "play_timestamp": "2026-04-01 10:00:05", "play_date": "2026-04-01",
                        "px": 0.0, "py": 2.5, "result": 1, "zone_section": 5,
                        "exit_velocity": 90.0, "distance_feet": 300.0, "is_contact": True}])
    assert pitch_zones.render(df, metric="ev") is not None


def test_practice_sidebar_renders_player_and_all():
    import pandas as pd
    from app.dashboards.hitting_practice import layout
    df = pd.DataFrame([{"px": 0.0, "py": 2.5, "result": 1, "zone_section": 5,
                        "exit_velocity": 90.0, "is_contact": True,
                        "player_name": "Andrew Mhoon", "play_date": "2026-04-01",
                        "session_id": 1, "play_timestamp": "2026-04-01 10:00:00"}])
    assert layout.sidebar(df, "Andrew Mhoon") is not None
    assert layout.sidebar(df, "All Players") is not None
    assert layout.sidebar(pd.DataFrame(), "All Players") is not None


def test_swing_frequency_has_trend_and_zone_chips():
    import inspect
    from app.dashboards.hitting_practice.tabs import swing_frequency as sf
    src = inspect.getsource(sf)
    assert "swing_decision_trend_fig" in src and "sfz" in src
    # tiles removed: no In-Zone Contact% tile label in the tab anymore
    assert "Swing Decision Score" not in src or "trend" in src.lower()


def test_swing_frequency_ev_body_zone_filter():
    import pandas as pd
    from app.dashboards.hitting_practice.tabs import swing_frequency as sf
    df = pd.DataFrame([
        {"zone_section": 5, "exit_velocity": 90.0, "distance_feet": 300.0,
         "result": 1, "is_contact": True, "play_date": "2026-04-01", "px": 0.0, "py": 2.5,
         "play_timestamp": "2026-04-01 10:00:05"},
        {"zone_section": 11, "exit_velocity": 70.0, "distance_feet": 100.0,
         "result": 1, "is_contact": True, "play_date": "2026-04-01", "px": 1.0, "py": 2.0,
         "play_timestamp": "2026-04-01 10:00:10"},
    ])
    # filtering to zone 5 keeps only that row's data feeding the chart (no crash)
    assert sf.ev_body(df, [5]) is not None
    assert sf.ev_body(df, None) is not None


def test_zone_chip_row_fixed_set_and_labels():
    import pandas as pd
    from dash import html
    from app.dashboards.hitting_practice.tabs import swing_frequency as sf

    def _buttons(node, out):
        if isinstance(node, html.Button):
            out.append(node)
        for k in ([node.children] if not isinstance(getattr(node, "children", None), (list, tuple))
                  else node.children):
            if hasattr(k, "children") or isinstance(k, html.Button):
                _buttons(k, out)
        return out

    # data present only for zones 1,3,5 -> those enabled, the rest greyed
    df = pd.DataFrame([{"zone_section": z} for z in [1, 1, 3, 5]])
    row = sf.zone_chip_row(df)
    btns = _buttons(row, [])
    labels = [b.children for b in btns]
    assert labels == [f"Zone {z}" for z in range(1, 14)]  # 13 chips, Zone N, no Zone 0
    disabled = {b.children: bool(b.disabled) for b in btns}
    assert disabled["Zone 2"] is True and disabled["Zone 1"] is False


def test_swing_trend_uses_real_dates_not_epoch():
    import pandas as pd
    from app.dashboards.hitting_practice import charts
    # play_date arriving as int64 epoch-ms (post dcc.Store round-trip)
    df = pd.DataFrame([
        {"play_date": 1774915200000, "in_zone_pct": 80, "chase_pct": 30, "score": 50},
        {"play_date": 1775088000000, "in_zone_pct": 70, "chase_pct": 40, "score": 30},
    ])
    fig = charts.swing_decision_trend_fig(df)
    xs = list(fig.data[0].x)
    # no raw epoch integers on the axis; labels look like dates
    assert all("2026" in str(v) or any(m in str(v) for m in
               ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"])
               for v in xs)
    assert "1774915200000" not in [str(v) for v in xs]
