"""Session revocation (deactivate / sign-out-everywhere / password change) and
the coach-only /accounts page."""
import os
import tempfile

import pytest

from app import create_app
from app.auth import mail
from app.auth.models import User
from app.extensions import db
from config import Config


@pytest.fixture()
def app(monkeypatch):
    monkeypatch.setenv("PAW_MAIL_BACKEND", "console")
    mail.outbox.clear()
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = "sqlite:///" + path.replace("\\", "/")

    application = create_app(TestConfig)
    with application.app_context():
        for email, role in (("coach@lmu.edu", "coach"), ("player@lmu.edu", "player")):
            u = User(email=email, name=email.split("@")[0], role=role)
            u.set_password("password123")
            u.mark_email_verified()
            db.session.add(u)
        db.session.commit()
    yield application
    with application.app_context():
        db.session.remove()
        db.engine.dispose()
    try:
        os.remove(path)
    except PermissionError:
        pass


def _client_logged_in(app, email):
    c = app.test_client()
    c.post("/login", data={"email": email, "password": "password123"})
    return c


def _logged_in(client) -> bool:
    return client.get("/change-password").status_code == 200


def _uid(app, email):
    with app.app_context():
        return User.query.filter_by(email=email).one().id


def _user(app, email):
    with app.app_context():
        u = User.query.filter_by(email=email).one()
        db.session.expunge(u)
        return u


# --- session revocation ---

def test_deactivating_logs_out_existing_session(app):
    player = _client_logged_in(app, "player@lmu.edu")
    assert _logged_in(player)
    with app.app_context():
        User.query.filter_by(email="player@lmu.edu").one().is_active = False
        db.session.commit()
    assert not _logged_in(player)


def test_sign_out_everywhere_ends_all_sessions(app):
    phone = _client_logged_in(app, "player@lmu.edu")
    laptop = _client_logged_in(app, "player@lmu.edu")
    with app.app_context():
        User.query.filter_by(email="player@lmu.edu").one().sign_out_everywhere()
        db.session.commit()
    assert not _logged_in(phone)
    assert not _logged_in(laptop)


def test_change_password_keeps_this_session_and_ends_others(app):
    here = _client_logged_in(app, "player@lmu.edu")
    elsewhere = _client_logged_in(app, "player@lmu.edu")
    here.post("/change-password", data={"current_password": "password123",
                                        "new_password": "new-password1",
                                        "confirm": "new-password1"})
    assert _logged_in(here)
    assert not _logged_in(elsewhere)


def test_pre_epoch_session_id_still_loads(app):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(_uid(app, "player@lmu.edu"))
        sess["_fresh"] = True
    assert _logged_in(client)


def test_login_records_last_login(app):
    assert _user(app, "player@lmu.edu").last_login_at is None
    _client_logged_in(app, "player@lmu.edu")
    assert _user(app, "player@lmu.edu").last_login_at is not None


# --- /accounts page ---

def test_accounts_page_coach_only(app):
    assert _client_logged_in(app, "player@lmu.edu").get("/accounts").status_code == 403
    resp = _client_logged_in(app, "coach@lmu.edu").get("/accounts")
    assert resp.status_code == 200
    assert b"player@lmu.edu" in resp.data


def test_player_cannot_post_account_actions(app):
    player = _client_logged_in(app, "player@lmu.edu")
    resp = player.post(f"/accounts/{_uid(app, 'coach@lmu.edu')}/deactivate")
    assert resp.status_code == 403
    assert _user(app, "coach@lmu.edu").is_active


def test_coach_deactivate_and_reactivate(app):
    coach = _client_logged_in(app, "coach@lmu.edu")
    player = _client_logged_in(app, "player@lmu.edu")
    pid = _uid(app, "player@lmu.edu")

    coach.post(f"/accounts/{pid}/deactivate")
    assert not _user(app, "player@lmu.edu").is_active
    assert not _logged_in(player)

    coach.post(f"/accounts/{pid}/activate")
    assert _user(app, "player@lmu.edu").is_active


def test_coach_role_change_and_sign_out(app):
    coach = _client_logged_in(app, "coach@lmu.edu")
    player = _client_logged_in(app, "player@lmu.edu")
    pid = _uid(app, "player@lmu.edu")
    coach.post(f"/accounts/{pid}/make-coach")
    assert _user(app, "player@lmu.edu").role == "coach"
    coach.post(f"/accounts/{pid}/make-player")
    assert _user(app, "player@lmu.edu").role == "player"
    coach.post(f"/accounts/{pid}/sign-out")
    assert not _logged_in(player)


def test_coach_cannot_lock_out_self(app):
    coach = _client_logged_in(app, "coach@lmu.edu")
    cid = _uid(app, "coach@lmu.edu")
    for action in ("deactivate", "make-player", "sign-out"):
        coach.post(f"/accounts/{cid}/{action}")
    me = _user(app, "coach@lmu.edu")
    assert me.is_active and me.role == "coach"
    assert _logged_in(coach)


def test_coach_can_email_reset_link(app):
    coach = _client_logged_in(app, "coach@lmu.edu")
    coach.post(f"/accounts/{_uid(app, 'player@lmu.edu')}/send-reset")
    assert len(mail.outbox) == 1
    assert mail.outbox[0]["To"] == "player@lmu.edu"


def test_unknown_action_rejected(app):
    coach = _client_logged_in(app, "coach@lmu.edu")
    coach.post(f"/accounts/{_uid(app, 'player@lmu.edu')}/delete")
    assert _user(app, "player@lmu.edu").is_active
