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
    assert "cauldron-kpi-rows" in s
    assert "cauldron-kpi-add" in s
    assert "COMPETITIVE" in s and "CAULDRON" in s


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
    assert "cauldron-kpi-rows" not in s
    assert "cauldron-kpi-add" not in s
    assert "COMPETITIVE" in s and "CAULDRON" in s


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


def _raw_pattern_callback(dash_app, *, input_type):
    """Same idea as `_raw_callback`, for a callback whose sole Input is a
    pattern-matching id like `{"type": input_type, "index": ALL}` -- Dash
    stores a pattern-matching input's id as a JSON string (e.g.
    '{"index":["ALL"],"type":"foo"}'), not a plain string, so this matches
    on that JSON text containing the expected type instead of exact equality."""
    import json
    for spec in dash_app.callback_map.values():
        ids = spec["inputs"]
        if len(ids) == 1 and isinstance(ids[0]["id"], str):
            try:
                parsed = json.loads(ids[0]["id"])
            except (ValueError, TypeError):
                continue
            if isinstance(parsed, dict) and parsed.get("type") == input_type:
                return spec["callback"].__wrapped__
    raise AssertionError(f"no callback found with sole pattern-matching Input type {input_type!r}")


def test_serve_layout_uses_week_not_cycle_for_coach(server):
    from app.extensions import db
    from app.auth.models import User
    from flask_login import login_user
    from app.dashboards.cauldron import layout
    with server.app_context():
        coach = User(email="cldwk@lmu.edu", name="Coach", role="coach")
        coach.set_password("x")
        db.session.add(coach)
        db.session.commit()
        with server.test_request_context("/dash/cauldron/"):
            login_user(coach)
            s = str(layout.serve_layout())
    assert "cauldron-week" in s            # Week selector
    assert "cauldron-grid-wrap" in s       # hide-until-edit wrapper
    assert "cauldron-cycle" not in s       # Cycle selector removed
    assert "cauldron-recompute" not in s   # Recompute button removed


def test_save_is_noop_for_non_coach(server, monkeypatch):
    """CRITICAL (auth): a non-coach current_user hitting Save must be a complete
    no-op -- no grid write. The layout omits the grid for a player (belt), but
    callbacks.py re-checks `is_coach` (suspenders) since a client could fire the
    callback id directly."""
    from app.extensions import db
    from app.auth.models import User
    from flask_login import login_user
    from dash import Dash, no_update
    from app.dashboards.cauldron import layout, callbacks, grid

    save_calls = []
    monkeypatch.setattr(grid, "save_grid", lambda *a, **k: save_calls.append((a, k)))

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

        with server.test_request_context("/dash/cauldron/"):
            login_user(player)
            save_out = on_save(1, [{"player_id": 1, "player": "X", "team": "Team 1"}],
                               "2026-03-02", "2026-03-02", "2025/2026")

    assert all(v is no_update for v in save_out)   # all 5 outputs no_update
    assert save_calls == []


def test_kpi_save_is_noop_for_non_coach(server, monkeypatch):
    """Same double-gate as Save: the layout omits the KPI panel for a player
    (belt), but the callback re-checks `is_coach` (suspenders)."""
    from app.extensions import db
    from app.auth.models import User
    from flask_login import login_user
    from dash import Dash
    from app.data import cauldron
    from app.dashboards.cauldron import layout, callbacks

    label_calls = []
    monkeypatch.setattr(cauldron, "update_scoring_label",
                        lambda *a, **k: label_calls.append((a, k)))
    monkeypatch.setattr(cauldron, "update_scoring_labels",
                        lambda *a, **k: label_calls.append((a, k)))

    with server.app_context():
        player = User(email="cldkpc@lmu.edu", name="Player", role="player", trackman_id=-997)
        player.set_password("x")
        db.session.add(player)
        db.session.commit()

        dash_app = Dash(__name__, server=server, url_base_pathname="/dash/cldkpi/",
                        suppress_callback_exceptions=True)
        dash_app.layout = layout.serve_layout
        callbacks.register_callbacks(dash_app)

        on_kpi_save = _raw_callback(dash_app, input_id="cauldron-kpi-save")

        with server.test_request_context("/dash/cauldron/"):
            login_user(player)
            out = on_kpi_save(1, ["New Label"], [{"type": "cauldron-kpi-label-input",
                                                   "index": "strike_pct"}],
                              "2026-03-02", "2025/2026")

    from dash import no_update
    assert all(v is no_update for v in out)
    assert label_calls == []


def test_on_kpi_save_writes_only_the_labels_that_changed(server, monkeypatch):
    """Save submits every column's label; rewriting all of them one by one
    made Save visibly slow (2026-10-04). Only changed labels are written,
    in one batch, and an unchanged submit writes nothing."""
    import pandas as pd
    from app.extensions import db
    from app.auth.models import User
    from flask_login import login_user
    from dash import Dash
    from app.data import cauldron
    from app.dashboards.cauldron import layout, callbacks

    scoring = pd.DataFrame({"metric": ["k_pct", "bb_pct"], "label": ["K%", "BB%"],
                            "is_manual": [0, 0], "sort_order": [1, 2]})
    written = []
    monkeypatch.setattr(cauldron, "read_scoring", lambda: scoring)
    monkeypatch.setattr(cauldron, "update_scoring_labels", lambda labels: written.append(labels))
    monkeypatch.setattr(callbacks, "_scoreboard", lambda *a: "scoreboard")
    ids = [{"type": "cauldron-kpi-label-input", "index": m} for m in ("k_pct", "bb_pct")]

    with server.app_context():
        coach = User(email="cldkpch@lmu.edu", name="Coach", role="coach")
        coach.set_password("x")
        db.session.add(coach)
        db.session.commit()
        dash_app = Dash(__name__, server=server, url_base_pathname="/dash/cldkpich/",
                        suppress_callback_exceptions=True)
        dash_app.layout = layout.serve_layout
        callbacks.register_callbacks(dash_app)
        on_kpi_save = _raw_callback(dash_app, input_id="cauldron-kpi-save")

        with server.test_request_context("/dash/cauldron/"):
            login_user(coach)
            status, _, _ = on_kpi_save(1, ["K%", "Walk%"], ids, "2026-03-02", "2025/2026")
            unchanged_status, _, _ = on_kpi_save(2, ["K%", "BB%"], ids, "2026-03-02", "2025/2026")

    assert written == [{"bb_pct": "Walk%"}]
    assert status == "Labels saved."
    assert unchanged_status == "No changes to save."


def test_on_kpi_save_updates_label_and_refreshes_grid_columns(server):
    """A coach renaming a KPI column persists ONLY the label
    (`cauldron.update_scoring_label` -- see its own docstring for why
    threshold/direction/points/is_manual/min_sample are untouched) and the
    callback's own returned `cauldron-grid` columns must reflect it
    immediately, without a page reload. Restores the real seeded label
    afterward -- SCORING_TABLE is shared global config, not sandboxed by a
    fake id like the player-keyed tables other tests clean up."""
    from app.extensions import db
    from app.auth.models import User
    from flask_login import login_user
    from dash import Dash
    from app.data import cauldron
    from app.dashboards.cauldron import layout, callbacks

    cauldron.ensure_tables()
    cauldron.seed_default_scoring()
    original_label = cauldron.read_scoring().set_index("metric").loc["strike_pct", "label"]

    with server.app_context():
        coach = User(email="cldkpsv@lmu.edu", name="Coach", role="coach")
        coach.set_password("x")
        db.session.add(coach)
        db.session.commit()

        dash_app = Dash(__name__, server=server, url_base_pathname="/dash/cldkpisave/",
                        suppress_callback_exceptions=True)
        dash_app.layout = layout.serve_layout
        callbacks.register_callbacks(dash_app)

        on_kpi_save = _raw_callback(dash_app, input_id="cauldron-kpi-save")

        try:
            with server.test_request_context("/dash/cauldron/"):
                login_user(coach)
                status, columns, _scoreboard_out = on_kpi_save(
                    1, ["Strike Rate"],
                    [{"type": "cauldron-kpi-label-input", "index": "strike_pct"}],
                    "2026-03-02", "2025/2026")
        finally:
            cauldron.update_scoring_label("strike_pct", original_label)

    assert status == "Labels saved."
    by_id = {c["id"]: c["name"] for c in columns}
    assert by_id["strike_pct"] == "Strike Rate"
    saved = cauldron.read_scoring().set_index("metric").loc["strike_pct"]
    assert saved["direction"] == "gte" and float(saved["threshold"]) == 55.0


def test_on_kpi_add_creates_a_manual_column_and_refreshes_the_grid(server):
    """2026-09-27 (Brad: "is it possible to have the edit KPI section also
    have an ability to add or delete columns"). A coach typing a new KPI
    name and clicking Add must persist a real (always-manual) scoring row
    and have the callback's own return values reflect it immediately --
    the new rows list, the cleared input, and the grid's refreshed columns."""
    from app.extensions import db
    from app.auth.models import User
    from flask_login import login_user
    from dash import Dash
    from app.data import cauldron
    from app.dashboards.cauldron import layout, callbacks

    cauldron.ensure_tables()
    cauldron.seed_default_scoring()

    with server.app_context():
        coach = User(email="cldkpadd@lmu.edu", name="Coach", role="coach")
        coach.set_password("x")
        db.session.add(coach)
        db.session.commit()

        dash_app = Dash(__name__, server=server, url_base_pathname="/dash/cldkpiadd/",
                        suppress_callback_exceptions=True)
        dash_app.layout = layout.serve_layout
        callbacks.register_callbacks(dash_app)

        on_kpi_add = _raw_callback(dash_app, input_id="cauldron-kpi-add")

        metric = None
        try:
            with server.test_request_context("/dash/cauldron/"):
                login_user(coach)
                rows, cleared, status, columns, _scoreboard_out = on_kpi_add(
                    1, "__Test Sandbox Add__", "2026-03-02", "2025/2026")
            assert cleared == ""
            assert "Added" in status
            scoring = cauldron.read_scoring()
            metric = next(m for m in scoring["metric"]
                          if scoring.set_index("metric").loc[m, "label"] == "__Test Sandbox Add__")
            assert bool(scoring.set_index("metric").loc[metric, "is_manual"]) is True
            assert {c["id"] for c in columns} >= {metric, "player", "team"}
            assert str(rows).count(metric) >= 1   # the new row rendered in the KPI list
        finally:
            if metric:
                cauldron.delete_scoring_metric(metric)


def test_on_kpi_add_is_noop_for_non_coach(server, monkeypatch):
    from app.extensions import db
    from app.auth.models import User
    from flask_login import login_user
    from dash import Dash, no_update
    from app.data import cauldron
    from app.dashboards.cauldron import layout, callbacks

    add_calls = []
    monkeypatch.setattr(cauldron, "add_scoring_metric", lambda *a, **k: add_calls.append(a))

    with server.app_context():
        player = User(email="cldkpaddnc@lmu.edu", name="Player", role="player", trackman_id=-996)
        player.set_password("x")
        db.session.add(player)
        db.session.commit()

        dash_app = Dash(__name__, server=server, url_base_pathname="/dash/cldkpiaddnc/",
                        suppress_callback_exceptions=True)
        dash_app.layout = layout.serve_layout
        callbacks.register_callbacks(dash_app)

        on_kpi_add = _raw_callback(dash_app, input_id="cauldron-kpi-add")

        with server.test_request_context("/dash/cauldron/"):
            login_user(player)
            out = on_kpi_add(1, "Sneaky KPI", "2026-03-02", "2025/2026")

    assert all(v is no_update for v in out)
    assert add_calls == []


def test_on_kpi_delete_removes_the_clicked_column_only(server, monkeypatch):
    """Pattern-matching delete buttons: `ctx.triggered_id` names which
    metric was actually clicked (simulated the same way
    test_splash_report_dash's script copy/paste tests fake the callback
    context, since invoking `.__wrapped__` directly bypasses Dash's own
    request-scoped ctx)."""
    from app.extensions import db
    from app.auth.models import User
    from flask_login import login_user
    from dash import Dash
    from app.data import cauldron
    from app.dashboards.cauldron import layout, callbacks

    cauldron.ensure_tables()
    cauldron.seed_default_scoring()
    metric_a = cauldron.add_scoring_metric("__Test Sandbox Delete A__")
    metric_b = cauldron.add_scoring_metric("__Test Sandbox Delete B__")

    class FakeCtx:
        triggered_id = None

    fake_ctx = FakeCtx()

    with server.app_context():
        coach = User(email="cldkpdel@lmu.edu", name="Coach", role="coach")
        coach.set_password("x")
        db.session.add(coach)
        db.session.commit()

        dash_app = Dash(__name__, server=server, url_base_pathname="/dash/cldkpidel/",
                        suppress_callback_exceptions=True)
        dash_app.layout = layout.serve_layout
        callbacks.register_callbacks(dash_app)

        on_kpi_delete = _raw_pattern_callback(dash_app, input_type="cauldron-kpi-delete")
        monkeypatch.setattr(callbacks, "ctx", fake_ctx)

        try:
            fake_ctx.triggered_id = {"type": "cauldron-kpi-delete", "index": metric_a}
            with server.test_request_context("/dash/cauldron/"):
                login_user(coach)
                rows, status, columns, _scoreboard_out = on_kpi_delete(
                    [1, 0], "2026-03-02", "2025/2026")
            assert status == "Column removed."
            remaining = set(cauldron.read_scoring()["metric"])
            assert metric_a not in remaining
            assert metric_b in remaining          # only the clicked one is gone
            assert {c["id"] for c in columns} == remaining | {"player", "team", "captain"}
        finally:
            for m in (metric_a, metric_b):
                if m in set(cauldron.read_scoring()["metric"]):
                    cauldron.delete_scoring_metric(m)


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
