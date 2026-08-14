"""User accounts and roles.

Team-transparent VIEW model: every authenticated account (coach or player) may
VIEW every player's data. Roles differ only in WRITE access -- a `coach` can
edit the velo board / Cauldron / coach notes / dev plans; a `player` account is
read-only (those edit paths re-check `is_coach` independently). `trackman_id`
still links a personal player account to its own Trackman data (used only as a
convenience default now, no longer a view restriction).
"""
from __future__ import annotations

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db, login_manager

ROLES = ("player", "coach")


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


@login_manager.user_loader
def load_user(user_id: str):
    return db.session.get(User, int(user_id))
