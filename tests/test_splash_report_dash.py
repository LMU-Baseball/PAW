"""Tests for the assembled Built on the Bluff Dash app: route registration, auth
gate, and role-branched layout (coach gets Edit/Save controls, player doesn't
-- both see the same view content, team-transparent like every other
dashboard)."""
import pytest

from app import create_app
from config import Config

TEST_PID = -999102  # sandboxed fake player id; never collides with real GAMES data


@pytest.fixture
def server(tmp_path):
    class T(Config):
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 't.db'}"
    return create_app(T)


def test_splash_report_route_registered(server):
    rules = {r.rule for r in server.url_map.iter_rules()}
    assert any(r.startswith("/dash/splash_report/") for r in rules)


def test_splash_report_anon_redirects_to_login(server):
    rv = server.test_client().get("/dash/splash_report/")
    assert rv.status_code == 302
    assert "/login" in rv.headers.get("Location", "")


def test_serve_layout_shows_edit_save_for_coach(server):
    from app.extensions import db
    from app.auth.models import User
    from flask_login import login_user
    from app.dashboards.splash_report import layout
    with server.app_context():
        coach = User(email="splashc@lmu.edu", name="Coach", role="coach")
        coach.set_password("x")
        db.session.add(coach)
        db.session.commit()
        with server.test_request_context("/dash/splash_report/"):
            login_user(coach)
            out = layout.serve_layout()
    s = str(out)
    assert "Please log in" not in s
    assert "splash-edit" in s and "splash-save" in s
    assert "splash-player" in s and "splash-season" in s and "splash-cycle" in s
    # Manage Video Library: same deal -- coach-only, always rendered,
    # independent of the Edit/Save toggle. (Drill add/remove is inline
    # under each dropdown instead, and dropdowns only render in edit mode
    # -- see test_drill_catalog_controls_are_inline_and_coach_only below.)
    assert "splash-manage-videos-toggle" in s
    assert "splash-video-modal" in s  # the shared popup renders for everyone


def test_serve_layout_hides_edit_save_for_player(server):
    from app.extensions import db
    from app.auth.models import User
    from flask_login import login_user
    from app.dashboards.splash_report import layout
    with server.app_context():
        player = User(email="splashp@lmu.edu", name="Player", role="player",
                      trackman_id=TEST_PID)
        player.set_password("x")
        db.session.add(player)
        db.session.commit()
        with server.test_request_context("/dash/splash_report/"):
            login_user(player)
            out = layout.serve_layout()
    s = str(out)
    assert "Please log in" not in s
    assert "splash-player" in s  # player still sees the view-only filters
    # "splash-editing" (the always-present Store) contains "splash-edit" as a
    # substring, so match the quoted component id exactly, not a bare substring.
    assert "id='splash-edit'" not in s and "id='splash-save'" not in s
    assert "splash-update-readings-toggle" not in s  # coach-only, a player never sees it
    assert "splash-manage-videos-toggle" not in s
    assert "splash-video-modal" in s  # the shared popup still renders (a player can watch clips)


def test_render_from_data_view_mode_has_no_editable_inputs():
    from app.dashboards.splash_report import layout
    data = layout.load_data(TEST_PID, "2099/2100", "Fall")
    out = layout.render_from_data(data, editable=False)
    s = str(out)
    assert "splash-vision" not in s   # view mode renders a bullet list, no Textarea
    assert "splash-engine-strength-table" not in s or "'editable': False" in s


def test_render_from_data_edit_mode_has_editable_inputs():
    from app.dashboards.splash_report import layout
    data = layout.load_data(TEST_PID, "2099/2100", "Fall")
    out = layout.render_from_data(data, editable=True)
    s = str(out)
    assert "splash-vision" in s
    assert "splash-feetset" in s
    assert "splash-engine-strength-table" in s
    assert "splash-pen-table" in s


def _minimal_render_data(pre_throw: str, post_throw: str) -> dict:
    """A hand-built dict matching the shape `layout.load_data` returns (see
    that function's own `return {...}`), with EVERY collection field left
    empty/blank except distinct Pre-Throw/Post-Throw checklist text --
    deliberately built WITHOUT calling `layout.load_data` itself (which
    hits the DB) so `render_from_data` can be exercised fully DB-free.
    `engine` still needs one blank row per `SR.ENGINE_METRIC_KEYS` (matching
    `SR.read_engine_metrics`'s own blank-state shape) -- `tables.
    engine_metrics_table` indexes into a `delta` column that a bare `[]`
    doesn't have."""
    from app.data import splash_report as SR
    engine_records = [
        {"metric_key": k, "label": SR.ENGINE_METRIC_LABELS[k], "base_value": None,
         "now_value": None, "delta": None, "d1_baseline": SR.D1_BASELINES.get(k),
         "flag": None}
        for k in SR.ENGINE_METRIC_KEYS
    ]
    return {
        "profile": {"photo": None, "jersey": None, "name": "P", "class_year": "",
                   "throws": "Right"},
        "kpis": {},
        "plan": {
            "vision_statement": "", "training_goals": "",
            "pre_throw_checklist": pre_throw, "post_throw_checklist": post_throw,
            "feet_set": "", "feet_moving": "", "work_day": "", "recovery_video_url": "",
        },
        "cycle": "Fall",
        "engine": engine_records, "gas": [], "scripts": [], "script_rows": {},
        "pen": [], "deleted_pen": [], "movement": {}, "drill_options": [], "videos": {},
    }


def test_render_from_data_shows_only_selected_keys_own_checklist_text():
    """Task 4, brief Step 4: distinguishes intentional identical DB content
    (a coach genuinely typing the same generic routine for every pitcher)
    from the render layer showing stale/wrong content for whichever key is
    actually selected. Two synthetic `data` dicts with distinct Pre-Throw/
    Post-Throw text (never touching the DB, see `_minimal_render_data`)
    must each render ONLY their own text -- never the other key's, which
    is what a caching/staleness bug in `render_from_data` would look like."""
    from app.dashboards.splash_report import layout

    data_a = _minimal_render_data("KEY-A-PRE-THROW", "KEY-A-POST-THROW")
    data_b = _minimal_render_data("KEY-B-PRE-THROW", "KEY-B-POST-THROW")

    out_a = str(layout.render_from_data(data_a, editable=False, is_coach=False))
    out_b = str(layout.render_from_data(data_b, editable=False, is_coach=False))

    assert "KEY-A-PRE-THROW" in out_a and "KEY-A-POST-THROW" in out_a
    assert "KEY-B-PRE-THROW" in out_b and "KEY-B-POST-THROW" in out_b
    # the actual isolation assertion: neither key's render tree contains
    # the OTHER key's text
    assert "KEY-B-PRE-THROW" not in out_a and "KEY-B-POST-THROW" not in out_a
    assert "KEY-A-PRE-THROW" not in out_b and "KEY-A-POST-THROW" not in out_b


def test_drill_catalog_controls_are_inline_and_coach_only():
    """2026-09-10 feedback: drill add/remove must live directly under each
    dropdown (Feet Set/Feet Moving/Work Day), not a separate "Manage
    Drills" section -- and only for a coach who's actually editing (the
    controls sit next to an editable dropdown, which only renders in edit
    mode to begin with)."""
    from app.dashboards.splash_report import layout
    data = layout.load_data(TEST_PID, "2099/2100", "Fall")

    coach_editing = str(layout.render_from_data(data, editable=True, is_coach=True))
    for section in ("feetset", "feetmoving", "workday"):
        for control_type in ("splash-drill-add-btn", "splash-drill-add-input",
                             "splash-drill-remove-select", "splash-drill-remove-btn"):
            assert f'"index": "{section}"' in coach_editing or f"'index': '{section}'" in coach_editing
            assert control_type in coach_editing

    player_editing = str(layout.render_from_data(data, editable=True, is_coach=False))
    assert "splash-drill-add-btn" not in player_editing  # a player never gets catalog controls

    coach_viewing = str(layout.render_from_data(data, editable=False, is_coach=True))
    assert "splash-drill-add-btn" not in coach_viewing  # only shows next to the live dropdown


def test_scripts_section_cards_always_rendered_but_collapsed_by_default():
    """2026-09-10 planning session: script cards are collapsed behind the
    "Show Scripts" multi-select ("only show when clicked"), but they must
    still be IN the DOM (hidden via style, not omitted) so the Save
    callback's per-script State ids always resolve -- see
    layout.script_card's docstring."""
    from app.dashboards.splash_report import layout
    data = layout.load_data(TEST_PID, "2099/2100", "Fall")
    for editable in (False, True):
        out = layout.render_from_data(data, editable=editable)
        s = str(out)
        assert "splash-pen-graph" in s and "splash-pen-compare" in s
        assert "splash-script-select" in s
        assert "splash-engine-strength-table" in s and "splash-engine-rom-table" in s
        for n in range(1, 7):
            assert f"splash-script-wrap-{n}" in s
            assert f"splash-script-rows-{n}" in s  # the pitch table itself, always mounted


def test_movement_chart_inside_bullpen_scripts_card_above_script_grid():
    """2026-09-16 round 5: the shared HB/IVB chart stays under Script Pen
    Results, inside the one "Bullpen Scripts" card (`layout.scripts_section`)
    rather than a separate card of its own."""
    from app.dashboards.splash_report import layout
    data = layout.load_data(TEST_PID, "2099/2100", "Fall")
    out = str(layout.render_from_data(data, editable=True, is_coach=True))
    pen_graph_pos = out.index("splash-pen-graph")
    movement_graph_pos = out.index("splash-movement-graph")
    first_script_card_pos = out.index("splash-script-wrap-1")
    building_engine_pos = out.index("Building the Engine")
    assert pen_graph_pos < movement_graph_pos < first_script_card_pos < building_engine_pos


def test_movement_log_is_one_shared_table_next_to_pen_results_not_in_script_grid():
    """2026-09-17 (Brad, screenshot): the old per-script Movement Log entry
    table sitting beside each script's card "ruins the look... that area is
    designated only for scripts, so having a random movement log table looks
    awkward and messes up the perfect 3x2 columns" -- moved out of the script
    grid entirely into ONE shared table (`tables.movement_log_table`, a
    Script # column instead of six separate grids) placed right next to
    `pen_results_table`, "in the white space on the right." """
    from app.dashboards.splash_report import layout
    data = layout.load_data(TEST_PID, "2099/2100", "Fall")
    out = str(layout.render_from_data(data, editable=True, is_coach=True))
    assert "splash-movement-table" in out  # the one shared table, not per-script ids
    assert "splash-script-movement-table-1" not in out
    assert "splash-script-movement-wrap-1" not in out
    pen_table_pos = out.index("splash-pen-table")
    movement_table_pos = out.index("splash-movement-table")
    first_script_card_pos = out.index("splash-script-wrap-1")
    # both tables sit together, ahead of (not inside) the script grid below
    assert pen_table_pos < movement_table_pos < first_script_card_pos


def test_movement_log_table_hidden_in_view_mode():
    """2026-09-17 round 2 (Brad, screenshot): "just have this table show up
    when editing, the visual does a good enough telling the story" -- the
    Movement Log is edit-only now, same as `pen_results_table` (which was
    already edit-only); a player never sees the raw table, only the shared
    HB/IVB chart above it."""
    from app.dashboards.splash_report import layout
    data = layout.load_data(TEST_PID, "2099/2100", "Fall")
    out = str(layout.render_from_data(data, editable=False, is_coach=False))
    assert "splash-movement-table" not in out
    assert "Movement Log" not in out


def test_movement_log_table_flattens_and_sorts_by_script_then_date():
    """`tables.movement_log_table` replaces six per-script tables with one
    flat table -- verify it actually regroups {script_number: [rows]} into
    a single row list, stamping each row with its script_number, sorted by
    script then date so a coach reads it top-to-bottom by script."""
    from app.dashboards.splash_report import tables

    movement_records = {
        "2": [{"id": 5, "pitch_type": "Fastball", "pen_date": "2026-09-20",
              "hb": 8, "ivb": 15}],
        "1": [{"id": 7, "pitch_type": "Slider", "pen_date": "2026-09-08",
              "hb": 3, "ivb": -2},
             {"id": 9, "pitch_type": "Fastball", "pen_date": "2026-09-01",
              "hb": 8, "ivb": 15}],
    }
    edit_table = tables.movement_log_table(movement_records, editable=True)
    col_ids = [c["id"] for c in edit_table.columns]
    assert col_ids == ["script_number", "pitch_type", "pen_date", "hb", "ivb"]
    real_rows = [r for r in edit_table.data if r.get("id") is not None]
    assert [(r["script_number"], r["pen_date"]) for r in real_rows] == [
        (1, "2026-09-01"), (1, "2026-09-08"), (2, "2026-09-20")]
    # Padded to 6 rows in edit mode (same as pen_results_table) so a coach
    # always has blank rows to type a brand new entry into.
    assert len(edit_table.data) == 6

    view_table = tables.movement_log_table(movement_records, editable=False)
    assert len(view_table.data) == 3  # no padding, and not row_deletable
    assert view_table.row_deletable is False


def test_gas_station_table_exercise_dropdown_in_edit_markdown_link_in_view():
    """2026-09-16 round 4 (Brad): the standalone "Gas Station Videos"
    browsable list is gone -- a video is now tied to ONE exercise row via
    the Exercise cell itself: a filterable dropdown while a coach edits
    (`gas_videos` options), a plain link for everyone else. A legacy
    free-typed exercise that isn't a known video title stays plain text
    rather than a broken link."""
    import pandas as pd

    from app.dashboards.splash_report import tables

    gas_videos = [
        {"id": 1, "title": "Forearm Extensor Release", "category": "Gas Station",
         "drill_category": "Elbow Strength", "link_url": "https://drive.google.com/x"},
        {"id": 2, "title": "Uploaded Clip", "category": "Gas Station",
         "drill_category": "Rehab", "link_url": None},
    ]
    df = pd.DataFrame([
        {"need": "Elbow", "exercise": "Forearm Extensor Release", "sets_reps": "3x10", "notes": ""},
        {"need": "Elbow", "exercise": "Uploaded Clip", "sets_reps": "2x8", "notes": ""},
        {"need": "Elbow", "exercise": "Not A Video", "sets_reps": "1x1", "notes": ""},
        {"need": "Elbow", "exercise": None, "sets_reps": "", "notes": ""},
    ])

    edit_table = tables.gas_station_table(df, gas_videos, editable=True)
    exercise_col = next(c for c in edit_table.columns if c["id"] == "exercise")
    assert exercise_col["presentation"] == "dropdown"
    values = {o["value"] for o in edit_table.dropdown["exercise"]["options"]}
    assert values == {"Forearm Extensor Release", "Uploaded Clip"}
    # 2026-09-16 round 6 (Brad): "add a way to search... so the coach
    # doesn't have to scroll the entire thing" -- the cell already filters
    # live as you type, but `gas_videos` arrives newest-first from
    # SR.list_videos, so scrolling by eye was effectively unordered.
    # Sorted by category then title makes scanning without typing usable.
    labels = [o["label"] for o in edit_table.dropdown["exercise"]["options"]]
    assert labels == ["Elbow Strength — Forearm Extensor Release", "Rehab — Uploaded Clip"]

    view_table = tables.gas_station_table(df, gas_videos, editable=False)
    exercise_col_view = next(c for c in view_table.columns if c["id"] == "exercise")
    assert exercise_col_view["presentation"] == "markdown"
    rows = view_table.data
    assert rows[0]["exercise"] == "[Forearm Extensor Release](https://drive.google.com/x)"
    assert rows[1]["exercise"] == "[Uploaded Clip](/splash-video/2)"
    assert rows[2]["exercise"] == "Not A Video"
    # A blank/None exercise must render as "" -- a markdown cell shows the
    # literal text "null" for None otherwise (2026-09-16 live bug: the
    # sandbox's blank-exercise test row showed "null" in the Gas Station
    # table after this column switched to markdown presentation).
    assert rows[3]["exercise"] == ""

    # 2026-09-16 round 7 (Brad): "without anything in the column it is
    # skinny and hard to read" -- a fixed width so an empty/short cell
    # doesn't collapse the column.
    exercise_width = next(c for c in edit_table.style_cell_conditional
                          if c["if"]["column_id"] == "exercise")
    assert exercise_width["width"] == "260px"


def test_gas_station_exercise_search_box_and_callback_registered(server):
    """2026-09-16 round 7 (Brad): "add an exercise search bar at the top
    of the column so coaches can search" -- a real, visible dcc.Input
    above the table (edit mode only), wired to a clientside callback that
    narrows `splash-gas-table`'s dropdown options as the coach types."""
    from dash import Dash

    from app.dashboards.splash_report import callbacks, layout

    data = layout.load_data(TEST_PID, "2099/2100", "Fall")
    editing = str(layout.render_from_data(data, editable=True))
    assert "splash-gas-exercise-search" in editing
    viewing = str(layout.render_from_data(data, editable=False))
    assert "splash-gas-exercise-search" not in viewing

    app = Dash(__name__, server=server, url_base_pathname="/dash/splashtest3/",
              suppress_callback_exceptions=True)
    app.layout = layout.serve_layout
    callbacks.register_callbacks(app)
    spec = app.callback_map["splash-gas-table.dropdown"]
    assert [i["id"] for i in spec["inputs"]] == ["splash-gas-exercise-search"]


def test_backspace_fix_clientside_callback_registered(server):
    """2026-09-17 round 3 (Brad: "backspace nor delete work in these
    tables... can you make it so the data we type can be deleted") --
    confirmed live that dash_table's own Backspace/Delete handling silently
    does nothing once a cell is actively being typed into (a documented
    dash_table limitation, not a prop we control). A page-wide clientside
    keydown patch (`splash-backspace-fix`, wired to fire once on page load)
    replaces it -- this just checks the callback is actually registered."""
    from dash import Dash

    from app.dashboards.splash_report import callbacks, layout

    app = Dash(__name__, server=server, url_base_pathname="/dash/splashtest5/",
              suppress_callback_exceptions=True)
    app.layout = layout.serve_layout
    callbacks.register_callbacks(app)
    spec = app.callback_map["splash-backspace-fix.children"]
    assert [i["id"] for i in spec["inputs"]] == ["splash-editing"]


def test_serve_layout_has_backspace_fix_target(server):
    """The clientside callback above needs its dummy Output id to actually
    exist in the page (Dash rejects an Output whose target is never
    rendered) -- confirm it's there for a real coach render."""
    from app.extensions import db
    from app.auth.models import User
    from flask_login import login_user
    from app.dashboards.splash_report import layout
    with server.app_context():
        coach = User(email="splashbf@lmu.edu", name="Coach BF", role="coach")
        coach.set_password("x")
        db.session.add(coach)
        db.session.commit()
        with server.test_request_context("/dash/splash_report/"):
            login_user(coach)
            out = layout.serve_layout()
    assert "splash-backspace-fix" in str(out)


def test_load_data_no_pitcher_selected_is_empty():
    from app.dashboards.splash_report import layout
    assert layout.load_data(None, "2099/2100", "Fall") == {}


def test_render_from_data_no_data_is_safe():
    from app.dashboards.splash_report import layout
    from dash import html
    out = layout.render_from_data({}, editable=False)
    assert isinstance(out, html.Div)
    assert "Select a pitcher" in str(out)


def test_register_callbacks_adds_callbacks(server):
    from dash import Dash
    from app.dashboards.splash_report import layout, callbacks
    app = Dash(__name__, server=server, url_base_pathname="/dash/splashtest/",
              suppress_callback_exceptions=True)
    app.layout = layout.serve_layout
    before = len(app.callback_map)
    callbacks.register_callbacks(app)
    assert len(app.callback_map) > before


def test_on_save_state_bound_to_live_selectors_not_a_stale_store(server):
    """Task 4 (coaches: every pitcher showed the exact same Pre-Throw/
    Post-Throw checklist text on Built on the Bluff) -- the code trace
    found `_on_save` reads State("splash-player"/"splash-season"/
    "splash-cycle", "value"), the live dropdown selections at click time,
    never a cached/stale store. Confirms that by inspecting the registered
    callback's own State spec (same technique as
    test_gas_station_exercise_search_box_and_callback_registered /
    test_backspace_fix_clientside_callback_registered above -- read
    app.callback_map, don't trust the source) rather than re-deriving it
    from scratch. No DB access needed: registering callbacks only wires
    up functions, it never queries."""
    from dash import Dash
    from app.dashboards.splash_report import layout, callbacks

    dash_app = Dash(__name__, server=server, url_base_pathname="/dash/splashsavestate/",
                    suppress_callback_exceptions=True)
    dash_app.layout = layout.serve_layout
    callbacks.register_callbacks(dash_app)
    spec = next(s for s in dash_app.callback_map.values()
               if [i["id"] for i in s["inputs"]] == ["splash-save"])
    state_ids = [s["id"] for s in spec["state"]]
    # splash-data (the cached render payload, read only to carry
    # recovery_video_url through untouched) comes first, then the three
    # live selectors -- never a separate/duplicate player-season-cycle
    # store that could go stale relative to the dropdowns.
    assert state_ids[0] == "splash-data"
    assert state_ids[1:4] == ["splash-player", "splash-season", "splash-cycle"]


def _raw_callback(dash_app, *, input_id):
    for spec in dash_app.callback_map.values():
        ids = [i["id"] for i in spec["inputs"]]
        if ids == [input_id]:
            return spec["callback"].__wrapped__
    raise AssertionError(f"no callback found with sole Input id {input_id!r}")


def test_on_save_calls_save_all_with_that_calls_own_player_season_cycle(server, monkeypatch):
    """Task 4, brief: "a callback-level test that passes selector values
    for one key and verifies save_all receives exactly that player,
    season, and cycle rather than a stale value captured during initial
    render." Actually INVOKES `_on_save` (unlike
    test_on_save_state_bound_to_live_selectors_not_a_stale_store above,
    which only inspects registered State ids) -- same `_raw_callback` +
    monkeypatch idiom as test_season_change_keeps_valid_player_else_falls_back_to_first.
    Monkeypatches callbacks.py's own `SR.save_all` (captures its args) and
    `layout.load_data` (returns {} so the post-save reload needs no DB) --
    real DB access is never reached."""
    from app.extensions import db
    from app.auth.models import User
    from flask_login import login_user
    from dash import Dash
    from app.dashboards.splash_report import layout, callbacks
    from app.dashboards.splash_report import callbacks as cb_module
    from app.data import splash_report as SR

    calls = []

    def fake_save_all(player_id, season_label, cycle, **kwargs):
        calls.append((player_id, season_label, cycle))

    monkeypatch.setattr(cb_module.SR, "save_all", fake_save_all)
    monkeypatch.setattr(cb_module.layout, "load_data", lambda *a, **kw: {})

    with server.app_context():
        coach = User(email="[EMAIL]", name="Coach OS", role="coach")
        coach.set_password("x")
        db.session.add(coach)
        db.session.commit()
        dash_app = Dash(__name__, server=server, url_base_pathname="/dash/splashonsave/",
                        suppress_callback_exceptions=True)
        dash_app.layout = layout.serve_layout
        callbacks.register_callbacks(dash_app)
        on_save = _raw_callback(dash_app, input_id="splash-save")

        # the rest of _on_save's States (vision/goals/pre/post/feet*/engine
        # tables/gas/pen/movement + 24 per-script states) -- their content
        # doesn't matter for this test, only player_id/season/cycle do.
        other_states = ["V", "G", "Pre", "Post", [], [], [], [], [], [], [], []]
        script_states = []
        for _ in range(SR.N_SCRIPTS):
            script_states += [None, None, None, []]

        with server.test_request_context("/dash/splash_report/"):
            login_user(coach)
            on_save(1, {}, -999301, "2091/2092", "Fall", *other_states, *script_states)
            on_save(1, {}, -999302, "2092/2093", "Winter", *other_states, *script_states)

    # NOT a stale value from a prior call/initial render -- each call's own
    # player/season/cycle, in order.
    assert calls == [(-999301, "2091/2092", "Fall"), (-999302, "2092/2093", "Winter")]


def test_load_data_callback_reads_the_db_with_each_calls_own_key_not_a_cached_default(
        server, monkeypatch):
    """Task 4, Finding 3 (task reviewer): `_load_data` (callbacks.py
    ~line 84) is the file's own documented split-caching layer --
    Player/Season/Cycle change re-reads the DB into `splash-data`, and
    `_render` (the next callback) only re-draws from whatever's already in
    that Store. `_load_data` itself is a bare passthrough
    (`return layout.load_data(player_id, season, cycle)`), so if it ever
    re-keyed incorrectly (e.g. closed over a stale value, or ignored its
    own arguments) that would be the actual mechanism behind "every pitcher
    shows the same content." Monkeypatches `layout.load_data` with a stub
    that echoes its own arguments back in the result, then calls the raw
    callback twice with two different (player, season, cycle) triples and
    asserts each call's OWN return value reflects only that call's inputs
    -- never the previous call's. No DB access needed."""
    from dash import Dash
    from app.dashboards.splash_report import layout, callbacks
    from app.dashboards.splash_report import callbacks as cb_module

    monkeypatch.setattr(
        cb_module.layout, "load_data",
        lambda player_id, season, cycle: {"marker": f"{player_id}-{season}-{cycle}"})

    dash_app = Dash(__name__, server=server, url_base_pathname="/dash/splashloadkey/",
                    suppress_callback_exceptions=True)
    dash_app.layout = layout.serve_layout
    callbacks.register_callbacks(dash_app)
    on_load = dash_app.callback_map["splash-data.data"]["callback"].__wrapped__

    result_a = on_load(-999401, "2081/2082", "Fall")
    result_b = on_load(-999402, "2082/2083", "Winter")

    assert result_a == {"marker": "-999401-2081/2082-Fall"}
    assert result_b == {"marker": "-999402-2082/2083-Winter"}
    # the actual regression check: the second call's result must not carry
    # anything from the first call
    assert result_a != result_b
    assert "-999401" not in result_b["marker"]


def test_edit_click_sets_editing_true_for_coach_only(server):
    from app.extensions import db
    from app.auth.models import User
    from flask_login import login_user
    from dash import Dash
    from app.dashboards.splash_report import layout, callbacks
    with server.app_context():
        coach = User(email="splashedit@lmu.edu", name="Coach", role="coach")
        coach.set_password("x")
        player = User(email="splashedit2@lmu.edu", name="Player", role="player",
                      trackman_id=TEST_PID)
        player.set_password("x")
        db.session.add_all([coach, player])
        db.session.commit()
        dash_app = Dash(__name__, server=server, url_base_pathname="/dash/splashedit/",
                        suppress_callback_exceptions=True)
        dash_app.layout = layout.serve_layout
        callbacks.register_callbacks(dash_app)
        on_edit = _raw_callback(dash_app, input_id="splash-edit")
        with server.test_request_context("/dash/splash_report/"):
            login_user(coach)
            editing, status = on_edit(1)
        with server.test_request_context("/dash/splash_report/"):
            login_user(player)
            editing_player, status_player = on_edit(1)
    assert editing is True and "Editing" in status
    from dash import no_update
    assert editing_player is no_update


def test_season_change_keeps_valid_player_else_falls_back_to_first(server, monkeypatch):
    """Pins the reported bug: changing Season used to leave the Player
    dropdown's stale id selected (e.g. a placeholder id only valid in the
    OLD season), so the KPI tiles/body kept showing the old season's data
    no matter what Season was picked -- "the filters don't work." A season
    change must now re-resolve the Player id against that season's roster:
    keep it if still valid there, else fall back to the first option --
    never silently keep an id that's invalid for the newly selected season."""
    from dash import Dash
    from app.dashboards.splash_report import layout, callbacks
    from app.dashboards.splash_report import callbacks as cb_module

    roster_by_season = {
        "2026/2027": [{"label": "Placeholder, P", "value": -13}],
        "2025/2026": [{"label": "Behrens, Adam", "value": 823008},
                     {"label": "Casole, John", "value": 111}],
    }
    monkeypatch.setattr(cb_module.selectors, "pitcher_options",
                        lambda **kw: roster_by_season[kw["season"]])

    dash_app = Dash(__name__, server=server, url_base_pathname="/dash/splashseason/",
                    suppress_callback_exceptions=True)
    dash_app.layout = layout.serve_layout
    callbacks.register_callbacks(dash_app)
    on_season = _raw_callback(dash_app, input_id="splash-season")

    # the OLD season's id (-13) doesn't exist in the new season's roster
    opts, value = on_season("2025/2026", -13)
    assert value == 823008  # falls back to the new season's first option
    assert {o["value"] for o in opts} == {823008, 111}

    # a still-valid id is left untouched
    opts2, value2 = on_season("2025/2026", 111)
    assert value2 == 111


def test_splash_video_route_requires_login_and_streams_bytes(server):
    from app.auth.models import User
    from app.extensions import db
    from app.data import splash_report as SR
    from sqlalchemy import text as _text
    from app.db import get_engine
    server.config["WTF_CSRF_ENABLED"] = False
    with server.app_context():
        u = User(email="splashvid@lmu.edu", name="Coach", role="coach")
        u.set_password("x")
        db.session.add(u)
        db.session.commit()
        vid_id = SR.add_video("__test_sandbox_route_clip__", "Recovery", "video/mp4",
                              b"fake-bytes", created_by=1)
    try:
        client = server.test_client()

        anon = client.get(f"/splash-video/{vid_id}")
        assert anon.status_code == 302 and "/login" in anon.headers.get("Location", "")

        client.post("/login", data={"email": "splashvid@lmu.edu", "password": "x"})
        rv = client.get(f"/splash-video/{vid_id}")
        assert rv.status_code == 200 and rv.data == b"fake-bytes"

        rv2 = client.get(f"/splash-video/{vid_id + 999999}")
        assert rv2.status_code == 404

        with server.app_context():
            SR.deactivate_video(vid_id)
        rv3 = client.get(f"/splash-video/{vid_id}")
        assert rv3.status_code == 404  # deactivated -> not servable
    finally:
        with get_engine().begin() as conn:
            conn.execute(_text(f"DELETE FROM {SR.VIDEOS_TABLE} WHERE id = :id"), {"id": vid_id})


def test_graffiti_header_has_solid_color_fallback_behind_backdrop_image():
    """2026-09-20 (coaches: Pre-Throw/Post-Throw headers sometimes render as
    just floating white text, no visible box) -- `_graffiti_header`'s whole
    background used to be `url(...)` with no color fallback, so a slow/
    failed image load left the always-white label with nothing behind it.
    Pins the fix: the `background` shorthand must also carry a solid color
    matching each backdrop image's dominant tone, so the box is never blank."""
    from app.dashboards.splash_report import layout

    pre = layout._graffiti_header("Pre-Throw Checklist", 0)
    post = layout._graffiti_header("Post-Throw Checklist", 1)

    pre_bg = pre.style["background"]
    assert layout.BLUE in pre_bg
    assert layout._HEADER_IMAGES[0] in pre_bg

    post_bg = post.style["background"]
    assert layout.CRIMSON in post_bg
    assert layout._HEADER_IMAGES[1] in post_bg

    assert pre.children.style["color"] == "#fff"
    assert post.children.style["color"] == "#fff"


def test_pitching_hub_has_splash_report_card(server):
    server.config["WTF_CSRF_ENABLED"] = False
    from app.auth.models import User
    from app.extensions import db
    with server.app_context():
        u = User(email="splashhub@lmu.edu", name="Coach", role="coach")
        u.set_password("x")
        db.session.add(u)
        db.session.commit()
    client = server.test_client()
    client.post("/login", data={"email": "splashhub@lmu.edu", "password": "x"})
    body = client.get("/pitching").get_data(as_text=True)
    assert "Built on the Bluff" in body and "/dash/splash_report/" in body
