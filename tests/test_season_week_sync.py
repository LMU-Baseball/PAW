"""Season <-> Week coherence on the velo board and the Competitive Cauldron.

Both boards have a Season selector and a Mon-start Week picker. They used to be
fully independent, so changing Season left the week wherever it was: the velo
table then showed season-level columns (Season Max / Avg / trend) for the NEW
season alongside weekly Velo Goal / Assessment for a week that isn't in it, and
nothing stopped a user picking a week from years away.

The week is now snapped to `velo_board.default_week_for(season)` whenever it
falls outside the selected season, and the picker is re-bounded to
`season_bounds(season)`. The callbacks decide by asking whether the week is
in-season rather than which input fired, so a week the user picked is left alone
while it stays valid -- and the week Output is `no_update` in that case, since
it is also an Input and echoing it back would fire the callback twice.
"""
import pytest
from dash import Dash, no_update
from flask_login import login_user

from app import create_app
from app.auth.models import User
from app.data import velo_board
from app.data.seasons import season_bounds
from app.extensions import db
from config import Config

OTHER_SEASON = "2023/2024"


@pytest.fixture
def server(tmp_path):
    class T(Config):
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 't.db'}"
    return create_app(T)


def _callback(dash_app, input_ids):
    for spec in dash_app.callback_map.values():
        if [i["id"] for i in spec["inputs"]] == input_ids:
            return spec["callback"].__wrapped__
    raise AssertionError(f"no callback with Inputs {input_ids!r}")


def _coach(server, email):
    user = User(email=email, name="Coach", role="coach")
    user.set_password("x")
    db.session.add(user)
    db.session.commit()
    return user


# --- the shared helper ------------------------------------------------------

def test_default_week_is_inside_its_season():
    """Whatever it returns must fall within the season it was asked about --
    that is the whole point of snapping to it."""
    for label in ("2025/2026", "2024/2025", OTHER_SEASON):
        start, end = season_bounds(label)
        week = velo_board.default_week_for(label)
        # The week's MONDAY can precede the Aug 1 start (the season opens
        # mid-week), so compare against that Monday, not the raw bound.
        assert velo_board.week_start_for(start) <= week <= end, label


def test_default_week_is_a_monday():
    from datetime import date
    for label in ("2025/2026", OTHER_SEASON):
        assert date.fromisoformat(velo_board.default_week_for(label)).weekday() == 0


def test_default_week_differs_across_seasons():
    """Sanity: the snap is season-dependent, so the tests below aren't
    coincidentally asserting a constant."""
    assert velo_board.default_week_for("2025/2026") != velo_board.default_week_for(OTHER_SEASON)


# --- velo board -------------------------------------------------------------

def test_velo_season_change_snaps_and_bounds_week(server):
    from app.dashboards.velo_board import layout, callbacks
    with server.app_context():
        coach = _coach(server, "vbsync@lmu.edu")
        app = Dash(__name__, server=server, url_base_pathname="/dash/vbsync/",
                   suppress_callback_exceptions=True)
        app.layout = layout.serve_layout
        callbacks.register_callbacks(app)
        cb = _callback(app, ["velo-season", "velo-week"])
        with server.test_request_context("/dash/velo_board/"):
            login_user(coach)
            # A stale week from a DIFFERENT season, exactly the drift case.
            rows, week, lo, hi = cb(OTHER_SEASON, "2026-03-02")
    assert week == velo_board.default_week_for(OTHER_SEASON)
    assert (lo, hi) == season_bounds(OTHER_SEASON)
    assert rows is not no_update


def test_velo_in_season_week_leaves_picker_alone(server):
    """A week that is already valid for the selected season must not be moved --
    the callback must not fight the user's own selection -- and the week Output
    must be no_update so the callback doesn't re-fire on its own echo."""
    from app.dashboards.velo_board import layout, callbacks
    with server.app_context():
        coach = _coach(server, "vbweek@lmu.edu")
        app = Dash(__name__, server=server, url_base_pathname="/dash/vbweek/",
                   suppress_callback_exceptions=True)
        app.layout = layout.serve_layout
        callbacks.register_callbacks(app)
        cb = _callback(app, ["velo-season", "velo-week"])
        with server.test_request_context("/dash/velo_board/"):
            login_user(coach)
            rows, week, lo, hi = cb("2025/2026", "2026-03-02")
    assert week is no_update
    assert (lo, hi) == season_bounds("2025/2026")
    assert rows is not no_update


def test_velo_week_picker_is_bounded_on_first_paint(server):
    from app.dashboards.velo_board import grid
    with server.app_context():
        s = str(grid.board_filters("2025/2026", "2026-03-02"))
    lo, hi = season_bounds("2025/2026")
    assert lo in s and hi in s


# --- cauldron ---------------------------------------------------------------

def test_cauldron_season_change_snaps_and_bounds_week(server):
    from app.dashboards.cauldron import layout, callbacks
    with server.app_context():
        coach = _coach(server, "cldsync@lmu.edu")
        app = Dash(__name__, server=server, url_base_pathname="/dash/cldsync/",
                   suppress_callback_exceptions=True)
        app.layout = layout.serve_layout
        callbacks.register_callbacks(app)
        cb = _callback(app, ["cauldron-season", "cauldron-week"])
        with server.test_request_context("/dash/cauldron/"):
            login_user(coach)
            board, week, lo, hi = cb(OTHER_SEASON, "2026-03-02")
    assert week == velo_board.default_week_for(OTHER_SEASON)
    assert (lo, hi) == season_bounds(OTHER_SEASON)
    assert board is not no_update


def test_cauldron_in_season_week_leaves_picker_alone(server):
    from app.dashboards.cauldron import layout, callbacks
    with server.app_context():
        coach = _coach(server, "cldweek@lmu.edu")
        app = Dash(__name__, server=server, url_base_pathname="/dash/cldweek/",
                   suppress_callback_exceptions=True)
        app.layout = layout.serve_layout
        callbacks.register_callbacks(app)
        cb = _callback(app, ["cauldron-season", "cauldron-week"])
        with server.test_request_context("/dash/cauldron/"):
            login_user(coach)
            board, week, lo, hi = cb("2025/2026", "2026-03-02")
    assert week is no_update
    assert (lo, hi) == season_bounds("2025/2026")
    assert board is not no_update


def test_cauldron_save_uses_selected_season_not_current(server, monkeypatch):
    """Save must build its cycle id from the SELECTED season -- otherwise a
    coach editing a past season would write into the current season's cycle."""
    from app.dashboards.cauldron import layout, callbacks, grid
    seen = {}
    monkeypatch.setattr(grid, "save_grid",
                        lambda data, play_date, cycle_id, updated_by=None:
                            seen.update(cycle_id=cycle_id))
    monkeypatch.setattr(callbacks, "_scoreboard", lambda w, s: "board")
    with server.app_context():
        coach = _coach(server, "cldsave@lmu.edu")
        app = Dash(__name__, server=server, url_base_pathname="/dash/cldsave/",
                   suppress_callback_exceptions=True)
        app.layout = layout.serve_layout
        callbacks.register_callbacks(app)
        on_save = _callback(app, ["cauldron-save"])
        with server.test_request_context("/dash/cauldron/"):
            login_user(coach)
            on_save(1, [{"player_id": 1, "player": "X"}], "2024-03-02",
                    "2024-03-02", OTHER_SEASON)
    assert seen["cycle_id"] == f"{OTHER_SEASON}-c1"
