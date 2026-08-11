"""Tests for the assembled Competitive Cauldron Dash app: route
registration, auth gate, and role-branched layout (coach sees the editable
grid, player does not, both see the scoreboard)."""
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


def test_cauldron_route_registered(server):
    rules = {r.rule for r in server.url_map.iter_rules()}
    assert any(r.startswith("/dash/cauldron/") for r in rules)


def test_cauldron_anon_redirects_to_login(server):
    rv = server.test_client().get("/dash/cauldron/")
    assert rv.status_code == 302
    assert "/login" in rv.headers.get("Location", "")


def test_serve_layout_renders_grid_for_coach(server):
    from app.extensions import db
    from app.auth.models import User
    from flask_login import login_user
    from app.dashboards.cauldron import layout
    with server.app_context():
        coach = User(email="cldc@lmu.edu", name="Coach", role="coach")
        coach.set_password("x")
        db.session.add(coach)
        db.session.commit()
        with server.test_request_context("/dash/cauldron/"):
            login_user(coach)
            out = layout.serve_layout()
    s = str(out)
    assert "Please log in" not in s
    assert "cauldron-grid" in s
    assert "cauldron-save" in s
    assert "COMPETITIVE CAULDRON" in s


def test_serve_layout_hides_grid_for_player(server):
    from app.extensions import db
    from app.auth.models import User
    from flask_login import login_user
    from app.dashboards.cauldron import layout
    with server.app_context():
        player = User(email="cldp@lmu.edu", name="Player", role="player", trackman_id=-999)
        player.set_password("x")
        db.session.add(player)
        db.session.commit()
        with server.test_request_context("/dash/cauldron/"):
            login_user(player)
            out = layout.serve_layout()
    s = str(out)
    assert "Please log in" not in s
    assert "cauldron-grid" not in s
    assert "cauldron-save" not in s
    assert "COMPETITIVE CAULDRON" in s


def test_register_callbacks_adds_callbacks(server):
    from dash import Dash
    from app.dashboards.cauldron import layout, callbacks
    app = Dash(__name__, server=server, url_base_pathname="/dash/cldtest/",
               suppress_callback_exceptions=True)
    app.layout = layout.serve_layout
    before = len(app.callback_map)
    callbacks.register_callbacks(app)
    assert len(app.callback_map) > before


def _raw_callback(dash_app, *, input_id):
    """Dig the undecorated function out of `dash_app.callback_map` for the
    callback whose sole Input id is `input_id` -- Dash wraps the registered
    function in a context-managing `add_context` closure (`@wraps(func)`),
    so `.__wrapped__` is the original callable, invokable directly with plain
    positional args and no Dash request-context machinery required."""
    for spec in dash_app.callback_map.values():
        ids = [i["id"] for i in spec["inputs"]]
        if ids == [input_id]:
            return spec["callback"].__wrapped__
    raise AssertionError(f"no callback found with sole Input id {input_id!r}")


def test_save_and_recompute_are_noop_for_non_coach(server, monkeypatch):
    """CRITICAL (auth): a non-coach current_user hitting Save or Recompute
    must be a complete no-op -- no grid write, no auto-score write. The
    layout already omits the grid for a player (belt), but callbacks.py
    re-checks `is_coach` itself (suspenders) since a client could still fire
    these callback ids directly."""
    from app.extensions import db
    from app.auth.models import User
    from flask_login import login_user
    from dash import Dash
    from app.dashboards.cauldron import layout, callbacks, grid
    from app.data import cauldron

    save_calls, recompute_calls = [], []
    monkeypatch.setattr(grid, "save_grid", lambda *a, **k: save_calls.append((a, k)))
    monkeypatch.setattr(cauldron, "score_day", lambda *a, **k: recompute_calls.append((a, k)))

    with server.app_context():
        player = User(email="cldnc@lmu.edu", name="Player", role="player", trackman_id=-998)
        player.set_password("x")
        db.session.add(player)
        db.session.commit()

        dash_app = Dash(__name__, server=server, url_base_pathname="/dash/cldauth/",
                         suppress_callback_exceptions=True)
        dash_app.layout = layout.serve_layout
        callbacks.register_callbacks(dash_app)

        on_save = _raw_callback(dash_app, input_id="cauldron-save")
        on_recompute = _raw_callback(dash_app, input_id="cauldron-recompute")

        with server.test_request_context("/dash/cauldron/"):
            login_user(player)

            save_out = on_save(1, [{"player_id": 1, "player": "X", "team": "Team 1"}],
                                "2026-03-02", "cycle-1")
            recompute_out = on_recompute(1, "2026-03-02", "cycle-1")

    from dash import no_update
    assert all(v is no_update for v in save_out)
    assert all(v is no_update for v in recompute_out)
    assert save_calls == []
    assert recompute_calls == []


def test_pitching_hub_has_cauldron_card(server):
    server.config["WTF_CSRF_ENABLED"] = False
    from app.auth.models import User
    from app.extensions import db
    with server.app_context():
        u = User(email="cldhub@lmu.edu", name="Coach", role="coach")
        u.set_password("x")
        db.session.add(u)
        db.session.commit()
    client = server.test_client()
    client.post("/login", data={"email": "cldhub@lmu.edu", "password": "x"})
    body = client.get("/pitching").get_data(as_text=True)
    assert "Competitive Cauldron" in body and "/dash/cauldron/" in body
