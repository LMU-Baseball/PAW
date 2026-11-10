"""User accounts and roles.

Team-transparent VIEW model: every authenticated account (coach or player) may
VIEW every player's data. Roles differ only in WRITE access -- a `coach` can
edit the velo board / Cauldron / coach notes / dev plans; a `player` account is
read-only (those edit paths re-check `is_coach` independently). `trackman_id`
still links a personal player account to its own Trackman data (used only as a
convenience default now, no longer a view restriction).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from flask_login import UserMixin
from sqlalchemy import inspect, text
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db, login_manager

ROLES = ("player", "coach")

# Env-var specs for boot-time account seeding (see seed_users_from_env). Each is
# (email_var, password_var, name_var, role).
_SEED_SPECS = (
    ("PAW_SEED_COACH_EMAIL", "PAW_SEED_COACH_PASSWORD", "PAW_SEED_COACH_NAME", "coach"),
    ("PAW_SEED_PLAYER_EMAIL", "PAW_SEED_PLAYER_PASSWORD", "PAW_SEED_PLAYER_NAME", "player"),
)


def is_coach_email(email: str) -> bool:
    """True if `email` is in the PAW_COACH_EMAILS allowlist (comma-separated,
    case-insensitive) -- determines the role a self-registered account gets.
    Not used for the seeded shared accounts, which already specify role
    explicitly via PAW_SEED_COACH_EMAIL/PAW_SEED_PLAYER_EMAIL."""
    allowlist = {e.strip().lower() for e in os.getenv("PAW_COACH_EMAILS", "").split(",") if e.strip()}
    return email.strip().lower() in allowlist


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(16), nullable=False, default="player")
    # Links a player account to GAMES.BatterId / PitcherId & PLAYERS.TrackmanId.
    trackman_id = db.Column(db.Integer, nullable=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    # NULL = address not yet confirmed. Only enforced at login while account
    # email is turned on (see app.auth.mail.mail_enabled).
    email_verified_at = db.Column(db.DateTime, nullable=True)
    # Part of every session's stored id (see get_id); bumping it invalidates
    # every existing login for this account on its next request.
    session_epoch = db.Column(db.Integer, nullable=False, default=0)
    last_login_at = db.Column(db.DateTime, nullable=True)
    # Last time this person proved they still read this inbox (verify link,
    # reset link, or emailed sign-in code). Drives reverify_due().
    email_checked_at = db.Column(db.DateTime, nullable=True)

    def get_id(self) -> str:
        return f"{self.id}:{self.session_epoch or 0}"

    def sign_out_everywhere(self) -> None:
        self.session_epoch = (self.session_epoch or 0) + 1

    def record_login(self) -> None:
        self.last_login_at = _utcnow()

    @property
    def email_verified(self) -> bool:
        return self.email_verified_at is not None

    def mark_email_verified(self) -> None:
        if self.email_verified_at is None:
            self.email_verified_at = _utcnow()
        self.mark_email_checked()

    def mark_email_checked(self) -> None:
        self.email_checked_at = _utcnow()

    @property
    def reverify_due(self) -> bool:
        """True when this account must prove inbox access again before using
        the PAW -- the check that locks out someone whose LMU email has been
        shut off after they leave. Off while account email is off."""
        from app.auth.mail import mail_enabled
        days = reverify_days()
        if not days or not mail_enabled() or self.email in _reverify_exempt():
            return False
        return (self.email_checked_at is None
                or _utcnow() - self.email_checked_at > timedelta(days=days))

    # --- password ---
    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    # --- roles ---
    @property
    def is_coach(self) -> bool:
        return self.role == "coach"

    def can_view_player(self, trackman_id) -> bool:
        """Team-transparent: any authenticated account may view any player.
        Write access is gated separately (coach-only) in the dashboards."""
        return True

    def __repr__(self) -> str:
        return f"<User {self.email} ({self.role})>"


log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def reverify_days() -> int:
    try:
        return max(0, int(os.getenv("PAW_REVERIFY_DAYS", "30")))
    except ValueError:
        return 30


def _reverify_exempt() -> set[str]:
    # For shared accounts with no real inbox behind them (coaches@lmu.edu-style
    # fallbacks), which could otherwise never pass the emailed code.
    return {e.strip().lower() for e in os.getenv("PAW_REVERIFY_EXEMPT_EMAILS", "").split(",")
            if e.strip()}


# (column, DDL type, backfill run once right after the column is added).
_USER_COLUMNS = (
    # Grandfather every account that existed before verification did --
    # otherwise the whole roster is locked out the day email turns on.
    ("email_verified_at", "DATETIME NULL", "UPDATE users SET email_verified_at = :now"),
    ("session_epoch", "INTEGER NOT NULL DEFAULT 0", None),
    ("last_login_at", "DATETIME NULL", None),
    # Start every existing account's 30-day clock at deploy, not "overdue".
    ("email_checked_at", "DATETIME NULL", "UPDATE users SET email_checked_at = :now"),
)


def _user_column_names() -> set[str]:
    return {c["name"] for c in inspect(db.engine).get_columns("users")}


def ensure_user_columns() -> None:
    """Additive, idempotent migration for columns added to `users` after it
    already existed on Lightsail (db.create_all never alters an existing table).

    Every gunicorn worker runs create_app at boot (no --preload), so two workers
    can race here; the loser's ALTER fails on a duplicate column, which is fine
    as long as the column now exists.
    """
    existing = _user_column_names()
    for col, ddl, backfill in _USER_COLUMNS:
        if col in existing:
            continue
        try:
            with db.engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {ddl}"))
                if backfill:
                    conn.execute(text(backfill), {"now": _utcnow()})
        except Exception:
            if col not in _user_column_names():
                raise
            log.info("users.%s added concurrently by another worker", col)


def seed_users_from_env() -> int:
    """Create shared login accounts from env vars when they don't already exist.

    For a host with no shell or one-off command (e.g. Render's free tier) and an
    ephemeral disk, the app provisions its own logins on every boot. Reads a
    coach spec and a player spec; each is skipped unless BOTH its email and
    password env vars are set. Create-if-missing, so an in-app password change
    survives until the next restart. Returns the number of accounts created.

    Must run inside an app context, after the tables exist (db.create_all).
    """
    created = 0
    for email_var, pw_var, name_var, role in _SEED_SPECS:
        email = (os.getenv(email_var) or "").strip().lower()
        password = os.getenv(pw_var) or ""
        if not email or not password:
            continue
        if User.query.filter_by(email=email).first():
            continue
        user = User(email=email, name=(os.getenv(name_var) or email).strip(),
                    role=role)
        user.set_password(password)
        user.mark_email_verified()
        db.session.add(user)
        created += 1
    if created:
        db.session.commit()
    return created


@login_manager.user_loader
def load_user(user_id: str):
    # Sessions issued before session_epoch existed store a bare "<id>"; treat
    # those as epoch 0 so the deploy doesn't log everyone out.
    raw_id, _, raw_epoch = user_id.partition(":")
    try:
        user = db.session.get(User, int(raw_id))
        epoch = int(raw_epoch or 0)
    except ValueError:
        return None
    if user is None or not user.is_active or epoch != (user.session_epoch or 0):
        return None
    # Ends a long-running session once the periodic check comes due, so the
    # next sign-in goes through the emailed code.
    if user.reverify_due:
        return None
    return user
