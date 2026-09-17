"""Tests for the app factory, login, and player/coach role access control."""
import os
import tempfile

import pytest

from app import create_app
from app.auth.access import can_view_player
from app.auth.models import User
from app.extensions import db
from config import Config


@pytest.fixture()
def app():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = "sqlite:///" + path.replace("\\", "/")

    application = create_app(TestConfig)
    with application.app_context():
        coach = User(email="coach@lmu.edu", name="Coach K", role="coach")
        coach.set_password("pw-coach")
        player = User(email="player@lmu.edu", name="Devan O", role="player",
                      trackman_id=694990)
        player.set_password("pw-player")
        db.session.add_all([coach, player])
        db.session.commit()

    yield application

    with application.app_context():
        db.session.remove()
        db.engine.dispose()
    try:
        os.remove(path)
    except PermissionError:
        pass  # Windows may still hold the handle briefly; temp file is harmless


@pytest.fixture()
def client(app):
    return app.test_client()


def _login(client, email, password):
    return client.post("/login", data={"email": email, "password": password},
                       follow_redirects=True)


# --- boot-time account seeding from env (shell-less hosts, e.g. Render free) ---

def _make_temp_app(monkeypatch, **env):
    """Build a create_app instance on a throwaway sqlite DB with the given env
    vars set BEFORE construction (so seed_users_from_env sees them)."""
    for key, val in env.items():
        monkeypatch.setenv(key, val)
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = "sqlite:///" + path.replace("\\", "/")

    return create_app(TestConfig), path


def _dispose(application, path):
    with application.app_context():
        db.session.remove()
        db.engine.dispose()
    try:
        os.remove(path)
    except PermissionError:
        pass  # Windows may still hold the handle; temp file is harmless


def test_seed_users_from_env_creates_accounts(monkeypatch):
    application, path = _make_temp_app(
        monkeypatch,
        PAW_SEED_COACH_EMAIL="Coaches@LMU.edu",  # mixed case -> normalized
        PAW_SEED_COACH_PASSWORD="coach-pw",
        PAW_SEED_COACH_NAME="LMU Coaches",
        PAW_SEED_PLAYER_EMAIL="team@lmu.edu",
        PAW_SEED_PLAYER_PASSWORD="team-pw",
    )
    try:
        with application.app_context():
            coach = User.query.filter_by(email="coaches@lmu.edu").first()
            assert coach is not None and coach.role == "coach"
            assert coach.name == "LMU Coaches"
            assert coach.check_password("coach-pw")
            player = User.query.filter_by(email="team@lmu.edu").first()
            assert player is not None and player.role == "player"
            assert player.check_password("team-pw")
    finally:
        _dispose(application, path)


def test_seed_users_from_env_is_idempotent(monkeypatch):
    from app.auth.models import seed_users_from_env
    application, path = _make_temp_app(
        monkeypatch,
        PAW_SEED_COACH_EMAIL="coaches@lmu.edu",
        PAW_SEED_COACH_PASSWORD="coach-pw",
    )
    try:
        with application.app_context():
            # create_app already seeded once; a second call adds nothing.
            assert seed_users_from_env() == 0
            assert User.query.filter_by(email="coaches@lmu.edu").count() == 1
    finally:
        _dispose(application, path)


def test_seed_users_from_env_noop_without_env(monkeypatch):
    for var in ("PAW_SEED_COACH_EMAIL", "PAW_SEED_COACH_PASSWORD",
                "PAW_SEED_PLAYER_EMAIL", "PAW_SEED_PLAYER_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    application, path = _make_temp_app(monkeypatch)
    try:
        with application.app_context():
            assert User.query.count() == 0
    finally:
        _dispose(application, path)


# --------------------------- model / role logic ---------------------------

def test_password_hashing(app):
    with app.app_context():
        u = User(email="x@y.z", name="X", role="coach")
        u.set_password("secret")
        assert u.password_hash != "secret"
        assert u.check_password("secret")
        assert not u.check_password("wrong")


def test_coach_can_view_anyone(app):
    with app.app_context():
        coach = User.query.filter_by(email="coach@lmu.edu").first()
        assert coach.is_coach
        assert coach.can_view_player(694990)
        assert coach.can_view_player(111111)


def test_player_can_view_everyone(app):
    # Team-transparent model: a player VIEWS every player (edit stays coach-only).
    with app.app_context():
        player = User.query.filter_by(email="player@lmu.edu").first()
        assert not player.is_coach
        assert player.can_view_player(694990)          # own id
        assert player.can_view_player(111111)          # someone else -- now allowed
        assert player.can_view_player(None)


def test_can_view_player_helper_anonymous():
    class Anon:
        is_authenticated = False
    assert can_view_player(Anon(), 694990) is False


# --------------------------- auth flow ------------------------------------

def test_login_required_redirects(client):
    resp = client.get("/")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_login_success(client):
    resp = _login(client, "coach@lmu.edu", "pw-coach")
    assert resp.status_code == 200
    # Home hero greets the user; the name is wrapped in markup, so match the name.
    assert b"Coach K" in resp.data


def test_login_bad_password(client):
    resp = _login(client, "coach@lmu.edu", "nope")
    assert b"Invalid email or password." in resp.data


def test_logout(client):
    _login(client, "coach@lmu.edu", "pw-coach")
    resp = client.post("/logout", follow_redirects=True)
    assert resp.status_code == 200
    assert b"Sign in" in resp.data


def test_email_case_insensitive(client):
    resp = _login(client, "COACH@LMU.EDU", "pw-coach")
    assert b"Coach K" in resp.data


def test_open_redirect_blocked(client):
    # An absolute off-site 'next' must be ignored after login.
    resp = client.post("/login?next=https://evil.com",
                       data={"email": "coach@lmu.edu", "password": "pw-coach"})
    assert resp.status_code == 302
    assert "evil.com" not in resp.headers["Location"]


# --------------------------- dash protection ------------------------------

def test_dash_requires_login(client):
    resp = client.get("/dash/hitting/")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_dash_accessible_after_login(client):
    _login(client, "player@lmu.edu", "pw-player")
    resp = client.get("/dash/hitting/")
    assert resp.status_code == 200


# --------------------------- change password ------------------------------

def test_change_password_requires_login(client):
    resp = client.get("/change-password")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_change_password_player_now_allowed(client):
    # Accounts are per-person now (self-service registration), so the old
    # shared-login lockout risk is gone -- a player may change their own
    # password same as a coach.
    _login(client, "player@lmu.edu", "pw-player")
    resp = client.post("/change-password", data={
        "current_password": "pw-player", "new_password": "brand-new-pw",
        "confirm": "brand-new-pw"}, follow_redirects=True)
    assert b"Password changed." in resp.data
    client.post("/logout")
    assert b"Invalid email or password." in _login(client, "player@lmu.edu", "pw-player").data
    assert b"Devan O" in _login(client, "player@lmu.edu", "brand-new-pw").data


def test_change_password_wrong_current_rejected(client):
    _login(client, "coach@lmu.edu", "pw-coach")
    resp = client.post("/change-password", data={
        "current_password": "not-it", "new_password": "brand-new-pw",
        "confirm": "brand-new-pw"}, follow_redirects=True)
    assert b"Current password is incorrect." in resp.data


def test_change_password_mismatch_rejected(client):
    _login(client, "coach@lmu.edu", "pw-coach")
    resp = client.post("/change-password", data={
        "current_password": "pw-coach", "new_password": "brand-new-pw",
        "confirm": "different-pw"}, follow_redirects=True)
    assert b"Passwords must match." in resp.data


def test_change_password_success_updates_login(client):
    _login(client, "coach@lmu.edu", "pw-coach")
    resp = client.post("/change-password", data={
        "current_password": "pw-coach", "new_password": "brand-new-pw",
        "confirm": "brand-new-pw"}, follow_redirects=True)
    assert b"Password changed." in resp.data
    client.post("/logout")
    # old password no longer works; the new one does
    assert b"Invalid email or password." in _login(client, "coach@lmu.edu", "pw-coach").data
    assert b"Coach K" in _login(client, "coach@lmu.edu", "brand-new-pw").data


# --------------------------- registration ----------------------------------

def _register(client, name, email, password, confirm=None, team_code=""):
    return client.post("/register", data={
        "name": name, "email": email, "password": password,
        "confirm": confirm if confirm is not None else password,
        "team_code": team_code,
    }, follow_redirects=True)


def test_register_creates_player_account(app, client):
    resp = _register(client, "New Kid", "newkid@lmu.edu", "a-real-password")
    assert b"Account created." in resp.data
    assert b"New Kid" in resp.data  # auto-logged-in, home greets by name
    with app.app_context():
        user = User.query.filter_by(email="newkid@lmu.edu").first()
        assert user is not None and user.role == "player"
        assert user.check_password("a-real-password")


def test_register_creates_coach_account_for_allowlisted_email(app, client, monkeypatch):
    monkeypatch.setenv("PAW_COACH_EMAILS", "Assistant@LMU.edu, other@lmu.edu")
    _register(client, "New Coach", "assistant@lmu.edu", "a-real-password")
    with app.app_context():
        user = User.query.filter_by(email="assistant@lmu.edu").first()
        assert user is not None and user.role == "coach"


def test_register_rejects_non_lmu_email(app, client):
    resp = _register(client, "Outsider", "outsider@gmail.com", "a-real-password")
    assert b"Use your LMU email address" in resp.data
    with app.app_context():
        assert User.query.filter_by(email="outsider@gmail.com").first() is None


def test_register_rejects_duplicate_email(app, client):
    resp = _register(client, "Impostor", "coach@lmu.edu", "a-real-password")
    assert b"already exists" in resp.data
    with app.app_context():
        assert User.query.filter_by(email="coach@lmu.edu").count() == 1


def test_register_rejects_password_mismatch(app, client):
    resp = _register(client, "New Kid", "mismatch@lmu.edu", "a-real-password",
                     confirm="different-password")
    assert b"Passwords must match." in resp.data
    with app.app_context():
        assert User.query.filter_by(email="mismatch@lmu.edu").first() is None


def test_register_rejects_short_password(app, client):
    resp = _register(client, "New Kid", "short@lmu.edu", "short")
    assert b"Use at least 8 characters." in resp.data
    with app.app_context():
        assert User.query.filter_by(email="short@lmu.edu").first() is None


def test_register_email_case_and_whitespace_normalized(app, client):
    _register(client, "New Kid", "  Mixed.Case@LMU.edu  ", "a-real-password")
    with app.app_context():
        assert User.query.filter_by(email="mixed.case@lmu.edu").first() is not None


def test_register_allows_no_code_when_team_code_unset(app, client, monkeypatch):
    monkeypatch.delenv("PAW_TEAM_CODE", raising=False)
    resp = _register(client, "New Kid", "nocode@lmu.edu", "a-real-password")
    assert b"Account created." in resp.data
    with app.app_context():
        assert User.query.filter_by(email="nocode@lmu.edu").first() is not None


def test_register_rejects_wrong_team_code_when_configured(app, client, monkeypatch):
    monkeypatch.setenv("PAW_TEAM_CODE", "GoLions26")
    resp = _register(client, "New Kid", "wrongcode@lmu.edu", "a-real-password",
                     team_code="nope")
    assert b"Incorrect team code." in resp.data
    with app.app_context():
        assert User.query.filter_by(email="wrongcode@lmu.edu").first() is None


def test_register_accepts_correct_team_code_case_insensitive(app, client, monkeypatch):
    monkeypatch.setenv("PAW_TEAM_CODE", "GoLions26")
    resp = _register(client, "New Kid", "rightcode@lmu.edu", "a-real-password",
                     team_code="  golions26  ")
    assert b"Account created." in resp.data
    with app.app_context():
        assert User.query.filter_by(email="rightcode@lmu.edu").first() is not None


# --------------------------- coach code (2026-09-18) -----------------------
# Brad: "add a team code so I can share that one with coaches and their
# account will register as a coach / the team code is for player accounts"
# -- PAW_COACH_CODE is a second, separate code; whichever of the two the
# registrant enters into the same "team_code" form field decides their role.

def test_register_with_coach_code_creates_coach_account(app, client, monkeypatch):
    monkeypatch.setenv("PAW_TEAM_CODE", "GoLions26")
    monkeypatch.setenv("PAW_COACH_CODE", "CoachesOnly26")
    resp = _register(client, "New Coach", "newcoach@lmu.edu", "a-real-password",
                     team_code="  coachesonly26  ")  # case/whitespace insensitive
    assert b"Account created." in resp.data
    with app.app_context():
        user = User.query.filter_by(email="newcoach@lmu.edu").first()
        assert user is not None and user.role == "coach"


def test_register_with_team_code_still_creates_player_account(app, client, monkeypatch):
    monkeypatch.setenv("PAW_TEAM_CODE", "GoLions26")
    monkeypatch.setenv("PAW_COACH_CODE", "CoachesOnly26")
    resp = _register(client, "New Kid", "newplayer@lmu.edu", "a-real-password",
                     team_code="GoLions26")
    assert b"Account created." in resp.data
    with app.app_context():
        user = User.query.filter_by(email="newplayer@lmu.edu").first()
        assert user is not None and user.role == "player"


def test_register_rejects_wrong_code_when_both_configured(app, client, monkeypatch):
    monkeypatch.setenv("PAW_TEAM_CODE", "GoLions26")
    monkeypatch.setenv("PAW_COACH_CODE", "CoachesOnly26")
    resp = _register(client, "New Kid", "wrongboth@lmu.edu", "a-real-password",
                     team_code="neither-code")
    assert b"Incorrect team code." in resp.data
    with app.app_context():
        assert User.query.filter_by(email="wrongboth@lmu.edu").first() is None


def test_coach_code_still_accepted_when_team_code_unset(app, client, monkeypatch):
    # The team-code gate being open (PAW_TEAM_CODE unset) must never block a
    # coach entering the separate coach code.
    monkeypatch.delenv("PAW_TEAM_CODE", raising=False)
    monkeypatch.setenv("PAW_COACH_CODE", "CoachesOnly26")
    resp = _register(client, "New Coach", "opengatecoach@lmu.edu", "a-real-password",
                     team_code="CoachesOnly26")
    assert b"Account created." in resp.data
    with app.app_context():
        user = User.query.filter_by(email="opengatecoach@lmu.edu").first()
        assert user is not None and user.role == "coach"


def test_coach_email_allowlist_still_works_alongside_coach_code(app, client, monkeypatch):
    # PAW_COACH_EMAILS keeps working unchanged -- either path is sufficient.
    monkeypatch.setenv("PAW_COACH_EMAILS", "allowlisted@lmu.edu")
    monkeypatch.setenv("PAW_COACH_CODE", "CoachesOnly26")
    monkeypatch.delenv("PAW_TEAM_CODE", raising=False)
    resp = _register(client, "Allowlisted Coach", "allowlisted@lmu.edu", "a-real-password")
    assert b"Account created." in resp.data
    with app.app_context():
        user = User.query.filter_by(email="allowlisted@lmu.edu").first()
        assert user is not None and user.role == "coach"
