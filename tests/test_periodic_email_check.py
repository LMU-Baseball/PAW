"""Periodic emailed sign-in code (PAW_REVERIFY_DAYS) -- locks out anyone who can
no longer read their LMU inbox."""
import os
import re
import tempfile
from datetime import timedelta

import pytest

from app import create_app
from app.auth import mail
from app.auth.models import User, _utcnow
from app.extensions import db
from config import Config

EMAIL = "player@lmu.edu"


@pytest.fixture()
def app(monkeypatch):
    monkeypatch.setenv("PAW_MAIL_BACKEND", "console")
    monkeypatch.delenv("PAW_REVERIFY_DAYS", raising=False)
    monkeypatch.delenv("PAW_REVERIFY_EXEMPT_EMAILS", raising=False)
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
        u = User(email=EMAIL, name="P", role="player")
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


def _age_check(app, days):
    with app.app_context():
        u = User.query.filter_by(email=EMAIL).one()
        u.email_checked_at = _utcnow() - timedelta(days=days)
        db.session.commit()


def _login(client):
    return client.post("/login", data={"email": EMAIL, "password": "password123"})


def _logged_in(client) -> bool:
    return client.get("/change-password").status_code == 200


def _code_from_outbox() -> str:
    return re.search(r"\b(\d{6})\b", mail.outbox[-1].get_content()).group(1)


def test_recent_check_signs_in_without_code(app):
    client = app.test_client()
    _login(client)
    assert _logged_in(client)
    assert not mail.outbox


def test_overdue_check_requires_emailed_code(app):
    _age_check(app, 31)
    client = app.test_client()
    resp = _login(client)
    assert resp.headers["Location"].endswith("/login/code")
    assert not _logged_in(client)
    assert len(mail.outbox) == 1

    client.post("/login/code", data={"code": _code_from_outbox()})
    assert _logged_in(client)
    with app.app_context():
        checked = User.query.filter_by(email=EMAIL).one().email_checked_at
        assert _utcnow() - checked < timedelta(minutes=1)


def test_wrong_code_rejected_and_limited(app):
    _age_check(app, 31)
    client = app.test_client()
    _login(client)
    real = _code_from_outbox()
    wrong = "000000" if real != "000000" else "111111"
    for _ in range(4):
        assert client.post("/login/code", data={"code": wrong}).status_code == 200
    resp = client.post("/login/code", data={"code": wrong})
    assert resp.headers["Location"].endswith("/login")
    client.post("/login/code", data={"code": real})
    assert not _logged_in(client)


def test_code_not_readable_from_session_cookie(app):
    _age_check(app, 31)
    client = app.test_client()
    _login(client)
    code = _code_from_outbox()
    with client.session_transaction() as sess:
        assert code not in str(dict(sess))


def test_expired_code_rejected(app, monkeypatch):
    _age_check(app, 31)
    client = app.test_client()
    _login(client)
    code = _code_from_outbox()
    import app.auth.routes as routes
    real_time = routes.time.time
    monkeypatch.setattr(routes.time, "time", lambda: real_time() + 16 * 60)
    client.post("/login/code", data={"code": code})
    assert not _logged_in(client)


def test_running_session_ends_when_check_comes_due(app):
    client = app.test_client()
    _login(client)
    assert _logged_in(client)
    _age_check(app, 31)
    assert not _logged_in(client)


def test_deactivated_during_code_step_is_stopped(app):
    _age_check(app, 31)
    client = app.test_client()
    _login(client)
    with app.app_context():
        User.query.filter_by(email=EMAIL).one().is_active = False
        db.session.commit()
    client.post("/login/code", data={"code": _code_from_outbox()})
    assert not _logged_in(client)


def test_disabled_when_mail_off_or_days_zero(app, monkeypatch):
    _age_check(app, 400)
    monkeypatch.setenv("PAW_REVERIFY_DAYS", "0")
    client = app.test_client()
    _login(client)
    assert _logged_in(client)

    monkeypatch.delenv("PAW_REVERIFY_DAYS")
    monkeypatch.delenv("PAW_MAIL_BACKEND")
    client2 = app.test_client()
    _login(client2)
    assert _logged_in(client2)


def test_exempt_email_skips_check(app, monkeypatch):
    _age_check(app, 400)
    monkeypatch.setenv("PAW_REVERIFY_EXEMPT_EMAILS", " Player@LMU.edu ")
    client = app.test_client()
    _login(client)
    assert _logged_in(client)


def test_password_reset_counts_as_check(app):
    _age_check(app, 31)
    client = app.test_client()
    client.post("/forgot-password", data={"email": EMAIL})
    path = re.search(r"https?://\S+", mail.outbox[-1].get_content()).group(0)
    path = path.split("localhost", 1)[1]
    client.post(path, data={"new_password": "brand-new-pw", "confirm": "brand-new-pw"})
    mail.outbox.clear()
    client.post("/login", data={"email": EMAIL, "password": "brand-new-pw"})
    assert _logged_in(client)
    assert not mail.outbox
