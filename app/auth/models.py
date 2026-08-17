"""User accounts and roles.

Team-transparent VIEW model: every authenticated account (coach or player) may
VIEW every player's data. Roles differ only in WRITE access -- a `coach` can
edit the velo board / Cauldron / coach notes / dev plans; a `player` account is
read-only (those edit paths re-check `is_coach` independently). `trackman_id`
still links a personal player account to its own Trackman data (used only as a
convenience default now, no longer a view restriction).
"""
from __future__ import annotations

import os

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db, login_manager

ROLES = ("player", "coach")

# Env-var specs for boot-time account seeding (see seed_users_from_env). Each is
# (email_var, password_var, name_var, role).
_SEED_SPECS = (
    ("PAW_SEED_COACH_EMAIL", "PAW_SEED_COACH_PASSWORD", "PAW_SEED_COACH_NAME", "coach"),
    ("PAW_SEED_PLAYER_EMAIL", "PAW_SEED_PLAYER_PASSWORD", "PAW_SEED_PLAYER_NAME", "player"),
)


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
        db.session.add(user)
        created += 1
    if created:
        db.session.commit()
    return created


@login_manager.user_loader
def load_user(user_id: str):
    return db.session.get(User, int(user_id))
