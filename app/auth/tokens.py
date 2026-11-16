"""Signed, expiring links for email verification and password reset.

Signed with SECRET_KEY (same mechanism as the session cookie), so no token table
is needed. Each purpose has its own salt so a verify link can never be replayed
as a reset link.
"""
from __future__ import annotations

from flask import current_app
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.auth.models import User
from app.extensions import db

VERIFY_MAX_AGE = 3 * 24 * 3600
RESET_MAX_AGE = 3600


def _serializer(purpose: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=f"paw-{purpose}")


def _password_fingerprint(user: User) -> str:
    # Embedding part of the current hash makes a reset link single-use: once the
    # password changes, every outstanding link for that account stops matching.
    return user.password_hash[-16:]


def make_verify_token(user: User) -> str:
    return _serializer("verify").dumps({"uid": user.id, "email": user.email})


def make_reset_token(user: User) -> str:
    return _serializer("reset").dumps({"uid": user.id, "pw": _password_fingerprint(user)})


def _load(purpose: str, token: str, max_age: int) -> dict | None:
    try:
        data = _serializer(purpose).loads(token, max_age=max_age)
    except BadSignature:
        return None
    return data if isinstance(data, dict) else None


def user_from_verify_token(token: str) -> User | None:
    data = _load("verify", token, VERIFY_MAX_AGE)
    if not data:
        return None
    user = db.session.get(User, data.get("uid"))
    if user is None or user.email != data.get("email"):
        return None
    return user


def user_from_reset_token(token: str) -> User | None:
    data = _load("reset", token, RESET_MAX_AGE)
    if not data:
        return None
    user = db.session.get(User, data.get("uid"))
    if user is None or not user.is_active or _password_fingerprint(user) != data.get("pw"):
        return None
    return user
