"""Tests for the assembled Velo Board Dash app: route registration, auth
gate, and role-branched layout (coach sees the editable grid, player does
not, both see the leaderboard)."""
import pytest

from app import create_app
from config import Config


@pytest.fixture
def server(tmp_path):
    class T(Config):
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 't.db'}"
    return create_app(T)


def test_velo_board_route_registered(server):
    rules = {r.rule for r in server.url_map.iter_rules()}
    assert any(r.startswith("/dash/velo_board/") for r in rules)


def test_velo_board_anon_redirects_to_login(server):
    rv = server.test_client().get("/dash/velo_board/")
    assert rv.status_code == 302
    assert "/login" in rv.headers.get("Location", "")


def test_serve_layout_renders_grid_for_coach(server):
    from app.extensions import db
    from app.auth.models import User
    from flask_login import login_user
    from app.dashboards.velo_board import layout
    with server.app_context():
        coach = User(email="vbc@lmu.edu", name="Coach", role="coach")
        coach.set_password("x")
        db.session.add(coach)
        db.session.commit()
        with server.test_request_context("/dash/velo_board/"):
            login_user(coach)
            out = layout.serve_layout()
    s = str(out)
    assert "Please log in" not in s
    assert "velo-grid" in s
    assert "velo-save" in s
    assert "LMU" in s


def test_serve_layout_hides_grid_for_player(server):
    from app.extensions import db
    from app.auth.models import User
    from flask_login import login_user
    from app.dashboards.velo_board import layout
    with server.app_context():
        player = User(email="vbp@lmu.edu", name="Player", role="player", trackman_id=-999)
        player.set_password("x")
        db.session.add(player)
        db.session.commit()
        with server.test_request_context("/dash/velo_board/"):
            login_user(player)
            out = layout.serve_layout()
    s = str(out)
    assert "Please log in" not in s
    assert "velo-grid" in s          # player sees the shared read-only table
    assert "velo-save" not in s      # but no Save/Edit controls
    assert "velo-edit" not in s
    assert "LMU" in s


def test_register_callbacks_adds_callbacks(server):
    from dash import Dash
    from app.dashboards.velo_board import layout, callbacks
    app = Dash(__name__, server=server, url_base_pathname="/dash/vbtest/",
               suppress_callback_exceptions=True)
    app.layout = layout.serve_layout
    before = len(app.callback_map)
    callbacks.register_callbacks(app)
    assert len(app.callback_map) > before


def _raw_callback(dash_app, *, input_id):
    for spec in dash_app.callback_map.values():
        ids = [i["id"] for i in spec["inputs"]]
        if ids == [input_id]:
            return spec["callback"].__wrapped__
    raise AssertionError(f"no callback found with sole Input id {input_id!r}")


def test_edit_unlocks_table_in_place_for_coach(server):
    """Edit flips the shared velo-grid table to editable=True (in place), so the
    four editable columns can be typed into -- no separate/hidden grid."""
    from app.extensions import db
    from app.auth.models import User
    from flask_login import login_user
    from dash import Dash
    from app.dashboards.velo_board import layout, callbacks
    with server.app_context():
        coach = User(email="vbedit@lmu.edu", name="Coach", role="coach")
        coach.set_password("x")
        db.session.add(coach)
        db.session.commit()
        dash_app = Dash(__name__, server=server, url_base_pathname="/dash/vbedit/",
                         suppress_callback_exceptions=True)
        dash_app.layout = layout.serve_layout
        callbacks.register_callbacks(dash_app)
        on_edit = _raw_callback(dash_app, input_id="velo-edit")
        with server.test_request_context("/dash/velo_board/"):
            login_user(coach)
            editable, status = on_edit(1)
    assert editable is True
    assert "Editing" in status


def test_pitching_hub_has_velo_board_card(server):
    server.config["WTF_CSRF_ENABLED"] = False
    from app.auth.models import User
    from app.extensions import db
    with server.app_context():
        u = User(email="vbhub@lmu.edu", name="Coach", role="coach")
        u.set_password("x")
        db.session.add(u)
        db.session.commit()
    client = server.test_client()
    client.post("/login", data={"email": "vbhub@lmu.edu", "password": "x"})
    body = client.get("/pitching").get_data(as_text=True)
    assert "Velo Board" in body and "/dash/velo_board/" in body
