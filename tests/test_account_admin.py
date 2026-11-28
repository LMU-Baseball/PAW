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
    monkeypatch.setenv("PAW_ACCOUNT_ADMINS", "coach@lmu.edu")
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


_OK = {"confirm": "yes"}


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


def test_account_admins_list_limits_accounts_page_to_named_coaches(app, monkeypatch):
    with app.app_context():
        other = User(email="assistant@lmu.edu", name="assistant", role="coach")
        other.set_password("password123")
        other.mark_email_verified()
        db.session.add(other)
        db.session.commit()
    monkeypatch.setenv("PAW_ACCOUNT_ADMINS", " Coach@LMU.edu ")
    admin = _client_logged_in(app, "coach@lmu.edu")
    assistant = _client_logged_in(app, "assistant@lmu.edu")
    assert admin.get("/accounts").status_code == 200
    assert assistant.get("/accounts").status_code == 403
    pid = _uid(app, "player@lmu.edu")
    assert assistant.post(f"/accounts/{pid}/deactivate", data=_OK).status_code == 403
    assert _user(app, "player@lmu.edu").is_active
    assert b"Account management" not in assistant.get("/change-password").data
    assert b"Account management" in admin.get("/change-password").data


def test_no_account_admins_listed_means_no_coach_manages_accounts(app, monkeypatch):
    monkeypatch.delenv("PAW_ACCOUNT_ADMINS")
    coach = _client_logged_in(app, "coach@lmu.edu")
    assert coach.get("/accounts").status_code == 403
    assert b"Account management" not in coach.get("/change-password").data


def test_player_cannot_post_account_actions(app):
    player = _client_logged_in(app, "player@lmu.edu")
    resp = player.post(f"/accounts/{_uid(app, 'coach@lmu.edu')}/deactivate", data=_OK)
    assert resp.status_code == 403
    assert _user(app, "coach@lmu.edu").is_active


def test_coach_deactivate_and_reactivate(app):
    coach = _client_logged_in(app, "coach@lmu.edu")
    player = _client_logged_in(app, "player@lmu.edu")
    pid = _uid(app, "player@lmu.edu")

    coach.post(f"/accounts/{pid}/deactivate", data=_OK)
    assert not _user(app, "player@lmu.edu").is_active
    assert not _logged_in(player)

    coach.post(f"/accounts/{pid}/activate", data=_OK)
    assert _user(app, "player@lmu.edu").is_active


def test_coach_role_change_and_sign_out(app):
    coach = _client_logged_in(app, "coach@lmu.edu")
    player = _client_logged_in(app, "player@lmu.edu")
    pid = _uid(app, "player@lmu.edu")
    coach.post(f"/accounts/{pid}/make-coach", data=_OK)
    assert _user(app, "player@lmu.edu").role == "coach"
    coach.post(f"/accounts/{pid}/make-player", data=_OK)
    assert _user(app, "player@lmu.edu").role == "player"
    coach.post(f"/accounts/{pid}/sign-out", data=_OK)
    assert not _logged_in(player)


def test_coach_cannot_lock_out_self(app):
    coach = _client_logged_in(app, "coach@lmu.edu")
    cid = _uid(app, "coach@lmu.edu")
    for action in ("deactivate", "make-player", "sign-out", "reset-password", "delete"):
        coach.post(f"/accounts/{cid}/{action}", data=_OK)
    me = _user(app, "coach@lmu.edu")
    assert me.is_active and me.role == "coach"
    assert _logged_in(coach)


def test_coach_can_email_reset_link(app):
    coach = _client_logged_in(app, "coach@lmu.edu")
    coach.post(f"/accounts/{_uid(app, 'player@lmu.edu')}/send-reset", data=_OK)
    assert len(mail.outbox) == 1
    assert mail.outbox[0]["To"] == "player@lmu.edu"


def test_unknown_action_rejected(app):
    coach = _client_logged_in(app, "coach@lmu.edu")
    coach.post(f"/accounts/{_uid(app, 'player@lmu.edu')}/nuke", data=_OK)
    assert _user(app, "player@lmu.edu").is_active


def test_action_without_confirm_checkbox_is_rejected(app):
    coach = _client_logged_in(app, "coach@lmu.edu")
    pid = _uid(app, "player@lmu.edu")
    coach.post(f"/accounts/{pid}/make-coach")
    coach.post(f"/accounts/{pid}/delete", data={"confirm": ""})
    assert _user(app, "player@lmu.edu").role == "player"


def test_coach_resets_password_to_default(app):
    coach = _client_logged_in(app, "coach@lmu.edu")
    player = _client_logged_in(app, "player@lmu.edu")
    coach.post(f"/accounts/{_uid(app, 'player@lmu.edu')}/reset-password", data=_OK)
    assert _user(app, "player@lmu.edu").check_password("golions")
    assert not _logged_in(player)


def test_coach_deletes_account(app):
    coach = _client_logged_in(app, "coach@lmu.edu")
    player = _client_logged_in(app, "player@lmu.edu")
    coach.post(f"/accounts/{_uid(app, 'player@lmu.edu')}/delete", data=_OK)
    with app.app_context():
        assert User.query.filter_by(email="player@lmu.edu").first() is None
    assert not _logged_in(player)


def test_header_menu_shows_account_management_to_coaches_only(app):
    coach_page = _client_logged_in(app, "coach@lmu.edu").get("/change-password").data
    player_page = _client_logged_in(app, "player@lmu.edu").get("/change-password").data
    for page in (coach_page, player_page):
        assert b"paw-menu" in page and b"Log out" in page
    assert b"Account management" in coach_page
    assert b"Account management" not in player_page


def _info(client, uid, name, *checked):
    return client.post(f"/accounts/{uid}/info", data={"name": name, "player_type": list(checked)},
                       follow_redirects=True)


def test_coach_edits_a_players_info_and_forge_channel_follows(app):
    from app.data import forge
    coach = _client_logged_in(app, "coach@lmu.edu")
    pid = _uid(app, "player@lmu.edu")
    assert b"Edit info" in coach.get("/accounts").data
    page = _info(coach, pid, "  Will   Kaczynski ", "position", "pitcher").data
    assert b"Saved Will Kaczynski&#39;s info." in page
    page = coach.get("/accounts").data
    assert b'data-type="both"' in page and b"position + pitcher" in page
    with app.app_context():
        assert _user(app, "player@lmu.edu").name == "Will Kaczynski"
        assert "Will Kaczynski" in [c.name for c in forge.sync_channels()]
    _info(coach, pid, "William Kaczynski", "pitcher")
    with app.app_context():
        assert _user(app, "player@lmu.edu").player_type == "pitcher"
        assert "William Kaczynski" in [c.name for c in forge.sync_channels()]
    _info(coach, pid, "William Kaczynski", "position")
    with app.app_context():
        assert "William Kaczynski" not in [c.name for c in forge.sync_channels()]


def test_edit_info_needs_full_name_and_a_position(app):
    coach = _client_logged_in(app, "coach@lmu.edu")
    pid = _uid(app, "player@lmu.edu")
    _info(coach, pid, "Will Kaczynski", "pitcher")
    assert b"Enter a first and last name." in _info(coach, pid, "Will", "pitcher").data
    assert b"Pick position player, pitcher, or both." in _info(coach, pid, "Bill Kaczynski").data
    user = _user(app, "player@lmu.edu")
    assert (user.name, user.player_type) == ("Will Kaczynski", "pitcher")


def test_edit_info_renames_coaches_without_positions(app):
    coach = _client_logged_in(app, "coach@lmu.edu")
    _info(coach, _uid(app, "coach@lmu.edu"), "Head Coach", "pitcher")
    user = _user(app, "coach@lmu.edu")
    assert (user.name, user.player_type) == ("Head Coach", None)


def test_edit_info_is_account_admins_only(app):
    with app.app_context():
        other = User(email="assistant@lmu.edu", name="assistant", role="coach")
        other.set_password("password123")
        other.mark_email_verified()
        db.session.add(other)
        db.session.commit()
    pid = _uid(app, "player@lmu.edu")
    assistant = _client_logged_in(app, "assistant@lmu.edu")
    assert _info(assistant, pid, "New Name", "pitcher").status_code == 403
    player = _client_logged_in(app, "player@lmu.edu")
    assert _info(player, pid, "New Name", "pitcher").status_code == 403
    user = _user(app, "player@lmu.edu")
    assert (user.name, user.player_type) == ("player", None)


def test_edit_info_switches_player_and_coach(app):
    coach = _client_logged_in(app, "coach@lmu.edu")
    pid = _uid(app, "player@lmu.edu")
    client = coach
    client.post(f"/accounts/{pid}/info", data={"name": "Player One", "role": "coach"})
    assert _user(app, "player@lmu.edu").role == "coach"
    page = client.post(f"/accounts/{pid}/info", data={"name": "Player One", "role": "player"},
                       follow_redirects=True).data
    assert b"Pick position player, pitcher, or both." in page
    assert _user(app, "player@lmu.edu").role == "coach"
    client.post(f"/accounts/{pid}/info",
                data={"name": "Player One", "role": "player", "player_type": ["pitcher"]})
    user = _user(app, "player@lmu.edu")
    assert (user.role, user.player_type) == ("player", "pitcher")


def test_edit_info_cant_change_your_own_role(app):
    coach = _client_logged_in(app, "coach@lmu.edu")
    coach.post(f"/accounts/{_uid(app, 'coach@lmu.edu')}/info",
               data={"name": "Head Coach", "role": "player", "player_type": ["pitcher"]})
    user = _user(app, "coach@lmu.edu")
    assert (user.name, user.role) == ("Head Coach", "coach")


def test_accounts_page_has_two_controls_per_row(app):
    page = _client_logged_in(app, "coach@lmu.edu").get("/accounts").data
    assert b"Edit info" in page and b"Edit account" in page
    assert b"Make coach" not in page and b"Make player" not in page


def test_accounts_page_has_search(app):
    page = _client_logged_in(app, "coach@lmu.edu").get("/accounts").data
    assert b'id="acct-search"' in page and b'data-search="' in page
