"""User accounts and roles.

A `player` is scoped to their own Trackman data via `trackman_id`; a `coach`
has no trackman_id and may view every player.
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
        """Coaches see everyone; players see only their own Trackman id."""
        if self.is_coach:
            return True
        if self.trackman_id is None or trackman_id is None:
            return False
        return int(self.trackman_id) == int(trackman_id)

    def __repr__(self) -> str:
        return f"<User {self.email} ({self.role})>"


@login_manager.user_loader
def load_user(user_id: str):
    return db.session.get(User, int(user_id))
