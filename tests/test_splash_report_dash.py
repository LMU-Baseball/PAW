"""Tests for the assembled Splash Report Dash app: route registration, auth
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


def test_render_body_view_mode_has_no_editable_inputs():
    from app.dashboards.splash_report import layout
    out = layout.render_body(TEST_PID, "2099/2100", "Fall", editable=False)
    s = str(out)
    assert "splash-vision" not in s   # view mode renders a bullet list, no Textarea
    assert "splash-engine-strength-table" not in s or "'editable': False" in s


def test_render_body_edit_mode_has_editable_inputs():
    from app.dashboards.splash_report import layout
    out = layout.render_body(TEST_PID, "2099/2100", "Fall", editable=True)
    s = str(out)
    assert "splash-vision" in s
    assert "splash-feetset" in s
    assert "splash-engine-strength-table" in s
    assert "splash-pen-table" in s


def test_render_body_no_pitcher_selected_is_safe():
    from app.dashboards.splash_report import layout
    from dash import html
    out = layout.render_body(None, "2099/2100", "Fall", editable=False)
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


def _raw_callback(dash_app, *, input_id):
    for spec in dash_app.callback_map.values():
        ids = [i["id"] for i in spec["inputs"]]
        if ids == [input_id]:
            return spec["callback"].__wrapped__
    raise AssertionError(f"no callback found with sole Input id {input_id!r}")


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
    assert "Splash Report" in body and "/dash/splash_report/" in body
