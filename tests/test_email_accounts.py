"""Email verification + forgot-password flows (app/auth/mail.py, tokens.py, routes.py)."""
import os
import re
import tempfile
from urllib.parse import urlparse

import pytest
from sqlalchemy import inspect, text

from app import create_app
from app.auth import mail
from app.auth.models import _USER_COLUMNS, User, ensure_user_columns
from app.extensions import db
from config import Config


def _build_app():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = "sqlite:///" + path.replace("\\", "/")

    return create_app(TestConfig), path


@pytest.fixture()
def app(monkeypatch):
    monkeypatch.setenv("PAW_MAIL_BACKEND", "console")
    monkeypatch.delenv("PAW_TEAM_CODE", raising=False)
    monkeypatch.delenv("PAW_COACH_CODE", raising=False)
    mail.outbox.clear()
    application, path = _build_app()
    with application.app_context():
        verified = User(email="verified@lmu.edu", name="Vee", role="player")
        verified.set_password("old-password")
        verified.mark_email_verified()
        db.session.add(verified)
        db.session.commit()
    yield application
    with application.app_context():
        db.session.remove()
        db.engine.dispose()
    try:
        os.remove(path)
    except PermissionError:
        pass


@pytest.fixture()
def client(app):
    return app.test_client()


def _register(client, email="new@lion.lmu.edu"):
    return client.post("/register", data={
        "name": "New Guy", "email": email, "team_code": "",
        "password": "password123", "confirm": "password123"})


def _login(client, email, password):
    return client.post("/login", data={"email": email, "password": password})


def _link_path(msg) -> str:
    url = re.search(r"https?://\S+", msg.get_content()).group(0)
    return urlparse(url).path


def _logged_in(client) -> bool:
    return client.get("/change-password").status_code == 200


# --- verification at signup ---

def test_register_sends_verify_email_and_blocks_login_until_confirmed(client, app):
    resp = _register(client)
    assert resp.status_code == 302
    assert len(mail.outbox) == 1
    assert mail.outbox[0]["To"] == "new@lion.lmu.edu"
    assert not _logged_in(client)

    resp = _login(client, "new@lion.lmu.edu", "password123")
    assert "/resend-verification" in resp.headers["Location"]
    assert not _logged_in(client)

    resp = client.get(_link_path(mail.outbox[0]))
    assert resp.status_code == 302
    assert _logged_in(client)
    with app.app_context():
        assert User.query.filter_by(email="new@lion.lmu.edu").one().email_verified


def test_register_auto_verifies_when_mail_disabled(client, app, monkeypatch):
    monkeypatch.delenv("PAW_MAIL_BACKEND")
    _register(client)
    assert not mail.outbox
    assert _logged_in(client)
    with app.app_context():
        assert User.query.filter_by(email="new@lion.lmu.edu").one().email_verified


def test_tampered_verify_token_rejected(client):
    _register(client)
    path = _link_path(mail.outbox[0])
    resp = client.get(path[:-3] + "xyz")
    assert "/resend-verification" in resp.headers["Location"]
    assert not _logged_in(client)


def test_resend_verification_does_not_reveal_accounts(client):
    _register(client)
    mail.outbox.clear()
    a = client.post("/resend-verification", data={"email": "new@lion.lmu.edu"})
    b = client.post("/resend-verification", data={"email": "nobody@lmu.edu"})
    c = client.post("/resend-verification", data={"email": "verified@lmu.edu"})
    assert a.status_code == b.status_code == c.status_code == 302
    assert len(mail.outbox) == 1


# --- forgot password ---

def test_forgot_password_reset_round_trip(client, app):
    client.post("/forgot-password", data={"email": "VERIFIED@lmu.edu"})
    assert len(mail.outbox) == 1
    path = _link_path(mail.outbox[0])

    assert client.get(path).status_code == 200
    resp = client.post(path, data={"new_password": "brand-new-pw", "confirm": "brand-new-pw"})
    assert resp.headers["Location"].endswith("/login")

    _login(client, "verified@lmu.edu", "brand-new-pw")
    assert _logged_in(client)


def test_reset_link_is_single_use(client):
    client.post("/forgot-password", data={"email": "verified@lmu.edu"})
    path = _link_path(mail.outbox[0])
    client.post(path, data={"new_password": "brand-new-pw", "confirm": "brand-new-pw"})
    resp = client.get(path)
    assert "/forgot-password" in resp.headers["Location"]


def test_forgot_password_unknown_or_inactive_sends_nothing(client, app):
    with app.app_context():
        User.query.filter_by(email="verified@lmu.edu").one().is_active = False
        db.session.commit()
    a = client.post("/forgot-password", data={"email": "verified@lmu.edu"})
    b = client.post("/forgot-password", data={"email": "nobody@lmu.edu"})
    assert a.status_code == b.status_code == 302
    assert not mail.outbox


def test_forgot_password_page_explains_when_mail_disabled(client, monkeypatch):
    monkeypatch.delenv("PAW_MAIL_BACKEND")
    resp = client.post("/forgot-password", data={"email": "verified@lmu.edu"})
    assert resp.status_code == 200
    assert b"Ask a coach" in resp.data
    assert not mail.outbox


def test_reset_completes_pending_verification(client, app):
    _register(client)
    mail.outbox.clear()
    client.post("/forgot-password", data={"email": "new@lion.lmu.edu"})
    path = _link_path(mail.outbox[0])
    client.post(path, data={"new_password": "brand-new-pw", "confirm": "brand-new-pw"})
    with app.app_context():
        assert User.query.filter_by(email="new@lion.lmu.edu").one().email_verified


def test_send_mail_failure_returns_false(monkeypatch):
    monkeypatch.setenv("PAW_MAIL_BACKEND", "smtp")
    monkeypatch.setenv("PAW_SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("PAW_SMTP_PORT", "1")
    assert mail.send_mail("x@lmu.edu", "s", "b") is False


# --- migration ---

def test_ensure_user_columns_grandfathers_existing_accounts_and_is_idempotent(app):
    with app.app_context():
        added = [col for col, _, _ in _USER_COLUMNS]
        with db.engine.begin() as conn:
            for col in added:
                conn.execute(text(f"ALTER TABLE users DROP COLUMN {col}"))
        assert not set(added) & {c["name"] for c in inspect(db.engine).get_columns("users")}

        ensure_user_columns()
        ensure_user_columns()

        assert set(added) <= {c["name"] for c in inspect(db.engine).get_columns("users")}
        db.session.expire_all()
        u = User.query.filter_by(email="verified@lmu.edu").one()
        assert u.email_verified
        assert u.session_epoch == 0
