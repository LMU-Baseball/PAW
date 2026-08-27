"""Team-transparent FILTERS: a player-role account may switch subjects.

The view model (app/auth/models.py) is team-transparent -- every account may
view every player -- and the selectors already return the full roster to both
roles. The dashboards' subject dropdowns, though, were still painted with
`disabled=not is_coach`, which locked a player onto whichever player the layout
happened to default to. These tests pin the fix: for a player-role user the
subject dropdown renders enabled on every dashboard. WRITE access (coach notes,
dev plans, velo-board / Cauldron table edits) stays coach-only and is covered by
tests/test_notes_ui.py, tests/test_dev_plans.py, tests/test_velo_board_dash.py
and tests/test_cauldron_dash.py.
"""
import pytest
from flask_login import login_user

from app import create_app
from app.auth.models import User
from app.extensions import db
from config import Config

# (module path, dashboard url, subject dropdown id)
SUBJECT_DROPDOWNS = [
    ("app.dashboards.hitting.layout", "/dash/hitting/", "hitter-dd"),
    ("app.dashboards.pitching.layout", "/dash/pitching/", "pitcher-dd"),
    ("app.dashboards.catching.layout", "/dash/catching/", "catcher-dd"),
    ("app.dashboards.bullpen.layout", "/dash/bullpen/", "bp-pitcher-dd"),
    ("app.dashboards.hitting_practice.layout", "/dash/practice/", "prac-player"),
]


@pytest.fixture
def server(tmp_path):
    class TestConfig(Config):
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 't.db'}"

    return create_app(TestConfig)


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


def _render_as(server, role, module_path, url):
    from importlib import import_module
    layout = import_module(module_path)
    with server.app_context():
        # trackman_id=-999 -> an id with no data of its own, so nothing about
        # the render can be an accident of the account matching a real player.
        user = User(email=f"{role}-filters@lmu.edu", name="Filters T",
                    role=role, trackman_id=-999)
        user.set_password("x")
        db.session.add(user)
        db.session.commit()
        with server.test_request_context(url):
            login_user(user)
            return layout.serve_layout()


@pytest.mark.parametrize("module_path,url,dd_id", SUBJECT_DROPDOWNS)
def test_player_subject_dropdown_is_enabled(server, module_path, url, dd_id):
    out = _render_as(server, "player", module_path, url)
    dd = _find_component(out, dd_id)
    assert dd is not None, f"{dd_id} not rendered"
    assert not getattr(dd, "disabled", False), (
        f"{dd_id} is disabled for a player -- players must be able to switch "
        "subjects (team-transparent view)")
    # Hitting/pitching/catching/bullpen now default to TODAY's real calendar
    # season (2026-08-26 season-default fix), so a genuinely fresh season with
    # no Trackman/HitTrax data ingested yet legitimately renders zero options --
    # that's an honest empty default, not a bug. This test only pins that a
    # player never sees FEWER options than a coach would (checked exactly by
    # test_player_and_coach_see_the_same_filter_options below), not that
    # options are non-empty.


@pytest.mark.parametrize("module_path,url,dd_id", SUBJECT_DROPDOWNS)
def test_player_and_coach_see_the_same_filter_options(server, module_path, url, dd_id):
    """Transparency: identical option lists for both roles, not just an
    enabled-but-shorter list for players."""
    player_dd = _find_component(_render_as(server, "player", module_path, url), dd_id)
    coach_dd = _find_component(_render_as(server, "coach", module_path, url), dd_id)
    assert [o["value"] for o in player_dd.options] == \
           [o["value"] for o in coach_dd.options]


@pytest.mark.parametrize("module_path,url,dd_id", SUBJECT_DROPDOWNS)
def test_no_filter_is_role_disabled_for_a_player(server, module_path, url, dd_id):
    """Every filter on the row, not just the subject one: a player-role render
    must not disable any filter the coach render leaves enabled."""
    def disabled_ids(node, out):
        if getattr(node, "disabled", False) and getattr(node, "id", None):
            out.add(str(node.id))
        children = getattr(node, "children", None)
        if children is None:
            return out
        if not isinstance(children, (list, tuple)):
            children = [children]
        for c in children:
            disabled_ids(c, out)
        return out

    player_off = disabled_ids(_render_as(server, "player", module_path, url), set())
    coach_off = disabled_ids(_render_as(server, "coach", module_path, url), set())
    assert player_off <= coach_off, (
        f"disabled for a player but not a coach: {sorted(player_off - coach_off)}")


# --- Velo Board / Competitive Cauldron -------------------------------------
#
# These two aren't subject-dropdown dashboards: their filters (Season/Week on
# the velo board, Week on the Cauldron) used to be nested INSIDE the coach-only
# control block, so a player's render omitted them entirely. Splitting the view
# filters out of the write controls is what these pin.

def _render_board_as(server, role, module_path, url):
    from importlib import import_module
    layout = import_module(module_path)
    with server.app_context():
        # Email must be unique per (role, dashboard): one test renders both
        # boards for the same role, and users.email is UNIQUE.
        slug = module_path.rsplit(".", 2)[-2]
        user = User(email=f"{role}-{slug}@lmu.edu", name="Board T",
                    role=role, trackman_id=-999)
        user.set_password("x")
        db.session.add(user)
        db.session.commit()
        with server.test_request_context(url):
            login_user(user)
            return str(layout.serve_layout())


def test_player_gets_velo_season_and_week_filters(server):
    s = _render_board_as(server, "player", "app.dashboards.velo_board.layout",
                         "/dash/velo_board/")
    assert "velo-season" in s, "player has no Season filter on the velo board"
    assert "velo-week" in s, "player has no Week filter on the velo board"
    # ...and still no write controls.
    assert "velo-edit" not in s and "velo-save" not in s


def test_player_gets_cauldron_week_filter(server):
    s = _render_board_as(server, "player", "app.dashboards.cauldron.layout",
                         "/dash/cauldron/")
    assert "cauldron-week" in s, "player has no Week filter on the Cauldron"
    assert "cauldron-season" in s, "player has no Season filter on the Cauldron"
    # The entry-date picker and the grid are WRITE controls -- still coach-only.
    assert "cauldron-date" not in s
    assert "cauldron-grid" not in s
    assert "cauldron-save" not in s


def test_coach_still_gets_board_write_controls(server):
    """The split must not have cost the coach anything."""
    velo = _render_board_as(server, "coach", "app.dashboards.velo_board.layout",
                            "/dash/velo_board/")
    assert all(t in velo for t in ("velo-season", "velo-week", "velo-edit", "velo-save"))
    cauldron = _render_board_as(server, "coach", "app.dashboards.cauldron.layout",
                                "/dash/cauldron/")
    assert all(t in cauldron for t in ("cauldron-season", "cauldron-week",
                                       "cauldron-date", "cauldron-grid",
                                       "cauldron-save"))


def test_cauldron_week_callback_is_renderable_for_a_player(server):
    """Dash won't fire a callback whose Inputs/Outputs are absent from the
    current render. The week->scoreboard callback must therefore touch ONLY ids
    a player actually gets, or the filter is inert for them despite rendering."""
    from dash import Dash
    from app.dashboards.cauldron import layout, callbacks
    with server.app_context():
        dash_app = Dash(__name__, server=server, url_base_pathname="/dash/cldwk/",
                        suppress_callback_exceptions=True)
        dash_app.layout = layout.serve_layout
        callbacks.register_callbacks(dash_app)
    player_html = _render_board_as(server, "player", "app.dashboards.cauldron.layout",
                                   "/dash/cauldron/")
    specs = [spec for spec in dash_app.callback_map.values()
             if [i["id"] for i in spec["inputs"]] == ["cauldron-season", "cauldron-week"]]
    assert specs, "no callback driven by cauldron-season + cauldron-week"
    for spec in specs:
        for dep in list(spec["inputs"]) + list(spec["output"]
                                               if isinstance(spec["output"], list)
                                               else [spec["output"]]):
            comp_id = dep["id"] if isinstance(dep, dict) else dep.component_id
            assert comp_id in player_html, (
                f"week callback touches {comp_id!r}, which a player never renders "
                "-- the Week filter would be dead for players")


def test_velo_filter_callback_is_renderable_for_a_player(server):
    """Same for the velo board's Season/Week -> table-rows callback."""
    from dash import Dash
    from app.dashboards.velo_board import layout, callbacks
    with server.app_context():
        dash_app = Dash(__name__, server=server, url_base_pathname="/dash/vbwk/",
                        suppress_callback_exceptions=True)
        dash_app.layout = layout.serve_layout
        callbacks.register_callbacks(dash_app)
    player_html = _render_board_as(server, "player", "app.dashboards.velo_board.layout",
                                   "/dash/velo_board/")
    specs = [spec for spec in dash_app.callback_map.values()
             if [i["id"] for i in spec["inputs"]] == ["velo-season", "velo-week"]]
    assert specs, "no callback driven by velo-season + velo-week"
    for spec in specs:
        outs = spec["output"] if isinstance(spec["output"], list) else [spec["output"]]
        for dep in list(spec["inputs"]) + list(outs):
            comp_id = dep["id"] if isinstance(dep, dict) else dep.component_id
            assert comp_id in player_html, (
                f"velo filter callback touches {comp_id!r}, which a player never "
                "renders -- the filters would be dead for players")
