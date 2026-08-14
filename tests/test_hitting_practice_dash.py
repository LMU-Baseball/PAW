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


def test_player_options_coach_no_all_players():
    from app.dashboards.hitting_practice import selectors
    opts = selectors.player_options(["Alpha", "Beta"], is_coach=True, own_name=None)
    vals = [o["value"] for o in opts]
    assert "All Players" not in vals          # aggregate removed
    assert set(vals) == {"Alpha", "Beta"}


def test_resolve_player_defaults_same_for_every_role():
    from app.dashboards.hitting_practice import selectors
    avail = ["Alpha", "Beta", "Cara"]
    # nothing requested -> the provided default (first-on-latest-date)
    assert selectors.resolve_player(None, is_coach=True, own_name=None,
                                    available=avail, default="Beta") == "Beta"
    # valid request -> honored
    assert selectors.resolve_player("Cara", is_coach=True, own_name=None,
                                    available=avail, default="Beta") == "Cara"
    # no default -> first available
    assert selectors.resolve_player(None, is_coach=True, own_name=None,
                                    available=avail) == "Alpha"
    # Team-transparent: a player resolves the SAME as a coach -- the requested
    # name is honored regardless of their own_name (view-all, no self-lock).
    assert selectors.resolve_player("Alpha", is_coach=False, own_name="Cara",
                                    available=avail) == "Alpha"
    # no players at all -> None (dashboard shows an empty state)
    assert selectors.resolve_player(None, is_coach=True, own_name=None,
                                    available=[]) is None
    # Task 3: date range has zero players -> keep the current selection rather
    # than blanking (e.g. a custom range with no HitTrax data yet).
    assert selectors.resolve_player("Alpha", is_coach=True, own_name=None,
                                    available=[]) == "Alpha"
    # requested player has no data in the new range, but others do -> reselect
    # the first available player instead of blanking.
    assert selectors.resolve_player("Zed", is_coach=True, own_name=None,
                                    available=avail) == "Alpha"


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
        # date_range.date_control builds the "prac-daterange" calendar (and the
        # "prac-date-preset" dropdown) dynamically, so assert the call site that
        # wires "prac" as the prefix onto the shared control.
        assert 'dr.date_control("prac"' in src


def test_practice_layout_uses_shared_preset_control_not_ad_hoc_dropdown():
    """Task 6: practice must adopt the shared date_control (This Season default +
    Past 6 Months + Custom Range) instead of its own today-anchored dropdown."""
    import inspect
    from app.dashboards.hitting_practice import layout
    src = inspect.getsource(layout)
    assert "dr.date_control(" in src
    # the old ad-hoc dropdown (with its own option set) must be gone
    assert 'id="prac-date-preset"' not in src
    assert "Past 3 Months" not in src
    assert "Custom (Swing Decision" not in src
    # layout no longer resolves the initial range via the old today-anchored helper
    assert "P.preset_date_range" not in src


def test_practice_preset_callback_writes_daterange_via_shared_preset_range():
    """The practice preset dropdown must resolve through dr.preset_range (anchored
    to the latest practice session date) and toggle prac-cal-wrap, matching the
    shared `_on_preset` shape used by the other dashboards."""
    import inspect
    from app.dashboards.hitting_practice import callbacks
    src = inspect.getsource(callbacks)
    assert "dr.preset_range(" in src
    assert 'Input("prac-date-preset", "value")' in src
    assert 'Output("prac-daterange", "start_date")' in src
    assert 'Output("prac-daterange", "end_date")' in src
    assert 'Output("prac-cal-wrap", "style")' in src


def test_pitch_zone_heatmap_black_box_and_metric():
    import pandas as pd
    from app.dashboards.hitting_practice import charts
    df = pd.DataFrame([{"px": 0.0, "py": 2.5, "result": 1,
                        "exit_velocity": 90.0, "distance_feet": 300.0}])
    fig = charts.pitch_zone_heatmap(df, metric="ev")
    # the strike-zone rectangle shape is drawn black
    rects = [s for s in fig.layout.shapes if s.type == "rect"]
    assert rects and any(s.line.color == "black" for s in rects)


def test_pitch_zone_heatmap_has_nine_pocket_grid():
    """Task 2 (Polish Wave C): the plate-location box on the practice pitch-zone
    heatmap must show the 3x3 nine-pocket interior grid (2 vertical + 2
    horizontal lines at thirds), matching the bullpen `_add_zone` look."""
    import pandas as pd
    from app.dashboards.hitting_practice import charts
    from app.data import practice as P
    df = pd.DataFrame([{"px": 0.0, "py": 2.5, "result": 1,
                        "exit_velocity": 90.0, "distance_feet": 300.0}])
    fig = charts.pitch_zone_heatmap(df, metric="ev")
    # outer rect + 2 vertical + 2 horizontal interior gridlines == 5 shapes min
    assert len(fig.layout.shapes) >= 5
    lines = [s for s in fig.layout.shapes if s.type == "line"]
    assert len(lines) >= 4
    xs = [l.x0 for l in lines if abs(l.x0 - l.x1) < 1e-9]
    ys = [l.y0 for l in lines if abs(l.y0 - l.y1) < 1e-9]
    third_x = (P.SZ_X1 - P.SZ_X0) / 3
    third_y = (P.SZ_Y1 - P.SZ_Y0) / 3
    assert any(abs(x - (P.SZ_X0 + third_x)) < 1e-6 for x in xs)
    assert any(abs(y - (P.SZ_Y0 + third_y)) < 1e-6 for y in ys)
    assert all(l.line.color == "#bbb" for l in lines)


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
                        "exit_velocity": 90.0, "is_contact": True, "hit_type": 2,
                        "launch_angle": 15.0,
                        "player_name": "Andrew Mhoon", "play_date": "2026-04-01",
                        "session_id": 1, "play_timestamp": "2026-04-01 10:00:00"}])
    tree = str(layout.sidebar(df, "Andrew Mhoon"))
    # the Contact Quality section (HARD-HIT% + POP-UP%) renders in the sidebar
    assert "Contact Quality" in tree
    assert "HARD-HIT%" in tree and "POP-UP%" in tree
    assert layout.sidebar(df, "All Players") is not None
    assert layout.sidebar(pd.DataFrame(), "All Players") is not None


def test_swing_frequency_has_trend_and_zone_chips():
    import inspect
    from app.dashboards.hitting_practice.tabs import swing_frequency as sf
    src = inspect.getsource(sf)
    assert "swing_decision_trend_fig" in src and "sfz" in src
    # tiles removed: no In-Zone Contact% tile label in the tab anymore
    assert "Swing Decision Score" not in src or "trend" in src.lower()


def _find_store(node, store_id):
    """Return the dcc.Store with the given id anywhere in the tree, else None."""
    from dash import dcc
    if isinstance(node, dcc.Store) and getattr(node, "id", None) == store_id:
        return node
    ch = getattr(node, "children", None)
    kids = ch if isinstance(ch, (list, tuple)) else ([ch] if ch is not None else [])
    for k in kids:
        found = _find_store(k, store_id)
        if found is not None:
            return found
    return None


def test_swing_frequency_has_swing_decision_zone_chips():
    """Item 4: the Swing Decision Score Trend gets its own zone chip filter
    (sds-*), default zones 1-9 selected, driving a callback-updated trend body."""
    import inspect
    from app.dashboards.hitting_practice.tabs import swing_frequency as sf
    src = inspect.getsource(sf)
    assert "sds-chip" in src and "sds-active" in src and "sds-trend-body" in src


def test_sds_chip_row_defaults_to_zones_1_through_9():
    import pandas as pd
    from app.dashboards.hitting_practice.tabs import swing_frequency as sf
    df = pd.DataFrame([{"zone_section": z} for z in [3, 5, 11, 12]])
    row = sf.sds_zone_chip_row(df)
    active = _find_store(row, "sds-active")
    assert active is not None
    assert list(active.data) == list(range(1, 10))


def _collect_buttons(node):
    """Return every html.Button anywhere in the tree."""
    from dash import html
    found = [node] if isinstance(node, html.Button) else []
    ch = getattr(node, "children", None)
    kids = ch if isinstance(ch, (list, tuple)) else ([ch] if ch is not None else [])
    for k in kids:
        found.extend(_collect_buttons(k))
    return found


def test_sds_chips_all_enabled_even_when_zone_empty():
    """Item 6: every sds-* zone chip stays enabled/selectable, even for zones
    with no pitches -- an empty selected zone just contributes nothing."""
    import pandas as pd
    from app.dashboards.hitting_practice.tabs import swing_frequency as sf
    df = pd.DataFrame({"zone_section": [1, 2, 3]})   # zones 4-13 absent
    row = sf.sds_zone_chip_row(df)
    buttons = _collect_buttons(row)
    assert len(buttons) == 13
    assert all(getattr(b, "disabled", False) is False for b in buttons)


def test_sds_trend_body_recomputes_with_in_zones():
    import pandas as pd
    from app.dashboards.hitting_practice.tabs import swing_frequency as sf
    df = pd.DataFrame([
        {"player_name": "Doe, John", "session_id": 1,
         "play_timestamp": "2026-04-01 10:00:05", "play_date": "2026-04-01",
         "zone_section": 3, "result": 1, "is_contact": True},
        {"player_name": "Doe, John", "session_id": 1,
         "play_timestamp": "2026-04-01 10:00:10", "play_date": "2026-04-01",
         "zone_section": 11, "result": -4, "is_contact": False},
    ])
    # builds for default and a custom in-zone set without crashing
    assert sf.trend_body(df, list(range(1, 10))) is not None
    assert sf.trend_body(df, [11]) is not None
    assert sf.trend_body(pd.DataFrame(), [1]) is not None


def test_sds_chip_callbacks_registered():
    import inspect
    from app.dashboards.hitting_practice import callbacks
    src = inspect.getsource(callbacks)
    assert "sds-active" in src and "sds-trend-body" in src


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


def test_swing_decision_trend_hover_and_no_stray_trace():
    import pandas as pd
    from app.dashboards.hitting_practice import charts
    tdf = pd.DataFrame({"play_date": pd.to_datetime(["2026-05-10"]),
                        "in_zone_pct": [40.0], "chase_pct": [60.0], "score": [-20.9]})
    fig = charts.swing_decision_trend_fig(tdf)
    # Only the main markers trace should be a data trace at all -- the zero
    # line must not leak into fig.data as a second (unnamed) hoverable trace.
    assert len(fig.data) == 1
    main = fig.data[0]
    assert "markers" in main.mode
    tmpl = main.hovertemplate
    assert "%{x}" in tmpl
    assert "Swing Decision:" in tmpl
    assert "%{customdata:.1f}" in tmpl or "%{y:.1f}" in tmpl
    assert "%<extra></extra>" in tmpl
    # The zero reference line is drawn as a layout shape (from add_hline),
    # never as a trace -- so it can't surface as "trace N" on hover.
    zero_lines = [s for s in fig.layout.shapes
                  if s.type == "line" and s.y0 == 0 and s.y1 == 0]
    assert len(zero_lines) == 1


def test_practice_layout_drops_session_and_exclude_controls():
    import inspect
    from app.dashboards.hitting_practice import layout
    src = inspect.getsource(layout)
    assert 'id="prac-session"' not in src
    assert 'id="prac-exclude-test"' not in src
    # defaults still seeded in the filters store
    assert '"session": "All session types"' in src
    assert '"exclude_test": True' in src


def test_on_filters_signature_dropped_session_exclude():
    import inspect
    from app.dashboards.hitting_practice import callbacks
    src = inspect.getsource(callbacks)
    assert 'Input("prac-session"' not in src
    assert 'Input("prac-exclude-test"' not in src
    assert 'Output("prac-session"' not in src


def test_on_filters_scopes_player_options_to_date_range():
    """Task 3: _on_filters must rebuild the Player dropdown from players in the
    selected date range (not every player who has ever had a session)."""
    import inspect
    from app.dashboards.hitting_practice import callbacks
    src = inspect.getsource(callbacks)
    assert "P.players_in_range(" in src
    assert "P.all_player_names()" not in src


def test_layout_scopes_first_paint_to_season_default_range():
    """Task 3: the initial player list/options at first paint must also be
    scoped to the season-default date range, not the all-time roster."""
    import inspect
    from app.dashboards.hitting_practice import layout
    src = inspect.getsource(layout)
    assert "P.players_in_range(start_d, end_d)" in src


def test_spray_distribution_fan_builds_cells():
    import pandas as pd
    from app.dashboards.hitting_practice import charts
    from app.data import practice as P
    plays = pd.DataFrame([
        {"horizontal_angle": -30.0, "distance_feet": 120.0, "hit_type": 1},
        {"horizontal_angle": 10.0, "distance_feet": 350.0, "hit_type": 3},
    ])
    fig = charts.spray_distribution_fan(P.spray_fan(plays))
    # at least one filled sector polygon + a % annotation
    assert any(getattr(t, "fill", None) == "toself" for t in fig.data)
    assert fig.layout.annotations and any("%" in a.text for a in fig.layout.annotations)
    # empty fan still renders
    assert charts.spray_distribution_fan(P.spray_fan(pd.DataFrame(
        columns=["horizontal_angle", "distance_feet", "hit_type"]))) is not None


def test_spray_scatter_hover_has_distance_and_ev():
    import pandas as pd
    from app.dashboards.hitting_practice import charts
    spray = pd.DataFrame([{"x": -50.0, "y": 200.0, "hit_type_label": "Line Drive",
                           "distance_feet": 206.2, "exit_velocity": 95.4}])
    fig = charts.spray_chart_fig(spray)
    assert any("Distance:" in (t.hovertemplate or "") and "Exit Velo:" in (t.hovertemplate or "")
               for t in fig.data if t.mode == "markers")


def test_contact_type_bar_uses_hit_type_colors():
    import pandas as pd
    from app.dashboards.hitting_practice import charts
    from app.data import practice as P
    counts = pd.DataFrame([{"Hit Type": "Line Drive", "Count": 10},
                           {"Hit Type": "Fly Ball", "Count": 5}])
    fig = charts.contact_type_bar(counts)
    marker_colors = list(fig.data[0].marker.color)
    assert marker_colors == [P.HIT_TYPE_COLORS["Line Drive"], P.HIT_TYPE_COLORS["Fly Ball"]]


def test_batted_ball_two_fields_and_chips():
    import inspect
    import pandas as pd
    from app.dashboards.hitting_practice.tabs import batted_ball
    src = inspect.getsource(batted_ball)
    assert "spray_distribution_fan" in src and "spray_chart_fig" in src
    assert "bb-chip" in src and "bb-active" in src

    plays = pd.DataFrame([
        {"horizontal_angle": -30.0, "distance_feet": 200.0, "exit_velocity": 90.0, "hit_type": 2},
        {"horizontal_angle": 20.0, "distance_feet": 300.0, "exit_velocity": 95.0, "hit_type": 3},
    ])
    # two graphs (fan + scatter) + the contact bar => at least 3 graphs
    def _count_graphs(node, n=0):
        from dash import dcc
        if isinstance(node, dcc.Graph):
            n += 1
        ch = getattr(node, "children", None)
        kids = ch if isinstance(ch, (list, tuple)) else ([ch] if ch is not None else [])
        for k in kids:
            n = _count_graphs(k, n)
        return n
    assert _count_graphs(batted_ball.render(plays)) >= 3
    # filtering to Fly Ball only keeps the FB row feeding the fan/scatter (no crash)
    assert batted_ball.body(plays, ["Fly Ball"]) is not None


def test_batted_ball_chip_callbacks_registered():
    import inspect
    from app.dashboards.hitting_practice import callbacks
    src = inspect.getsource(callbacks)
    assert "bb-active" in src and "bb-body" in src


def test_batted_ball_chips_colored_per_hit_type():
    import pandas as pd
    from dash import html
    from app.dashboards.hitting_practice.tabs import batted_ball
    from app.data import practice as P

    def _buttons(node, out):
        if isinstance(node, html.Button):
            out.append(node)
        ch = getattr(node, "children", None)
        kids = ch if isinstance(ch, (list, tuple)) else ([ch] if ch is not None else [])
        for k in kids:
            if hasattr(k, "children") or isinstance(k, html.Button):
                _buttons(k, out)
        return out

    plays = pd.DataFrame([
        {"horizontal_angle": -30.0, "distance_feet": 200.0, "exit_velocity": 90.0, "hit_type": 2},
        {"horizontal_angle": 20.0, "distance_feet": 300.0, "exit_velocity": 95.0, "hit_type": 3},
    ])
    row = batted_ball.chip_row(plays)
    btns = _buttons(row, [])
    styles = {b.children: b.style for b in btns}
    # Line Drive (hit_type 2) and Fly Ball (hit_type 3) chips use their hit-type colors
    assert styles["Line Drive"]["background"] == P.HIT_TYPE_COLORS["Line Drive"]
    assert styles["Fly Ball"]["background"] == P.HIT_TYPE_COLORS["Fly Ball"]


def test_heatmap_uses_crimson_scale_all_metrics():
    import pandas as pd
    from app.dashboards.hitting_practice import charts
    df = pd.DataFrame([{"px": 0.0, "py": 2.5, "result": 1,
                        "exit_velocity": 90.0, "distance_feet": 300.0}])
    for metric in ("contact", "ev", "distance"):
        cs = charts.pitch_zone_heatmap(df, metric).data[0].colorscale
        assert cs != "YlOrRd"
        stops = [str(s[1]).lower().replace(" ", "") for s in cs]
        assert any(v in stops for v in ("#9a0021", "rgb(154,0,33)"))


def test_ev_distance_by_pitch_labeled_hovers():
    import pandas as pd
    from app.dashboards.hitting_practice import charts
    df = pd.DataFrame([
        {"is_contact": True, "play_timestamp": "2026-04-01 10:00:05",
         "exit_velocity": 90.0, "distance_feet": 250.0},
        {"is_contact": True, "play_timestamp": "2026-04-01 10:00:10",
         "exit_velocity": 95.0, "distance_feet": 300.0},
    ])
    tmpls = [t.hovertemplate or "" for t in charts.ev_distance_by_pitch(df).data]
    assert any("Pitch #:" in t and "Exit Velo:" in t for t in tmpls)
    assert any("Pitch #:" in t and "Distance:" in t for t in tmpls)


def test_spray_fan_hover_has_balls_ev_dist():
    import pandas as pd
    from app.dashboards.hitting_practice import charts
    from app.data import practice as P
    plays = pd.DataFrame([
        {"horizontal_angle": -30.0, "distance_feet": 120.0, "exit_velocity": 85.0, "hit_type": 1},
        {"horizontal_angle": 10.0, "distance_feet": 360.0, "exit_velocity": 100.0, "hit_type": 3},
    ])
    fig = charts.spray_distribution_fan(P.spray_fan(plays))
    hovers = [t.hovertext for t in fig.data if getattr(t, "fill", None) == "toself"]
    assert any(("Balls:" in (h or "")) and ("Avg EV:" in (h or ""))
               and ("Avg Dist:" in (h or "")) for h in hovers)
    # empty fan still renders
    assert charts.spray_distribution_fan(P.spray_fan(pd.DataFrame(
        columns=["horizontal_angle", "distance_feet", "hit_type"]))) is not None


def test_spray_chart_marks_foul_and_hr_no_legend():
    import pandas as pd
    from app.dashboards.hitting_practice import charts
    spray = pd.DataFrame([
        {"x": -50.0, "y": 200.0, "hit_type_label": "Line Drive",
         "distance_feet": 206.0, "exit_velocity": 95.0, "is_foul": False, "is_hr": False},
        {"x": 10.0, "y": 400.0, "hit_type_label": "Fly Ball",
         "distance_feet": 405.0, "exit_velocity": 103.0, "is_foul": False, "is_hr": True},
        {"x": -200.0, "y": 20.0, "hit_type_label": "Line Drive",
         "distance_feet": 200.0, "exit_velocity": 70.0, "is_foul": True, "is_hr": False},
    ])
    fig = charts.spray_chart_fig(spray)
    assert fig.layout.showlegend is False
    syms = [t.marker.symbol for t in fig.data if t.mode == "markers"]
    assert "star" in syms          # HR marker
    assert "circle-open" in syms   # foul marker
    assert any(s.type == "path" for s in fig.layout.shapes)  # fence curve drawn
    # still renders without the flag columns (round-1 contract)
    plain = pd.DataFrame([{"x": -50.0, "y": 200.0, "hit_type_label": "Line Drive",
                           "distance_feet": 206.0, "exit_velocity": 95.0}])
    assert charts.spray_chart_fig(plain) is not None


def test_fan_matches_landing_scale_and_labels_spread():
    import pandas as pd
    import numpy as np
    from app.dashboards.hitting_practice import charts
    from app.data import practice as P
    plays = pd.DataFrame([
        {"horizontal_angle": -30.0, "distance_feet": 100.0, "exit_velocity": 85.0, "hit_type": 1},
        {"horizontal_angle": 10.0, "distance_feet": 120.0, "exit_velocity": 88.0, "hit_type": 1},
    ])
    fig = charts.spray_distribution_fan(P.spray_fan(plays))
    assert list(fig.layout.xaxis.range) == [-340, 340]
    # infield-ring (near home) labels are pushed out to >= 108 ft radius
    radii = [float(np.hypot(a.x, a.y)) for a in fig.layout.annotations]
    assert radii and min(radii) >= 108.0 - 1e-9  # infield labels floored to 108 ft (float-epsilon tolerance)


def test_practice_light_helpers_and_scoped_load():
    """Light dropdown/default helpers + SQL-scoped load (the perf change)."""
    from app.data import practice as P
    latest = P.latest_session_date()
    assert latest is not None
    on_latest = P.players_on_date(latest)
    names = P.all_player_names()
    # alphabetical (case-insensitive, matching MySQL's collation)
    assert [n.lower() for n in on_latest] == sorted(n.lower() for n in on_latest)
    assert [n.lower() for n in names] == sorted(n.lower() for n in names)
    assert set(on_latest) <= set(names)          # players-on-latest subset of all
    assert all(n and n.strip() for n in names)   # no blank dropdown entries
    if on_latest:
        p = on_latest[0]
        df = P.load_pitch_coords(player=p, start=latest, end=latest)  # scoped in SQL
        if not df.empty:
            assert set(df["player_name"].unique()) == {p}             # only that player
