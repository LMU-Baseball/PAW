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
    # An enabled dropdown is only useful with options behind it.
    assert dd.options, f"{dd_id} rendered with no options for a player"


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
