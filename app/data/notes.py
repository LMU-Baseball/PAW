"""Per-game coach notes, stored in the app DB and shared across game dashboards."""
from __future__ import annotations

from datetime import datetime, timezone

from app.extensions import db


class GameNote(db.Model):
    __tablename__ = "game_notes"
    __table_args__ = (
        db.UniqueConstraint("module", "subject_id", "game_id", name="uq_game_note"),
    )
    id = db.Column(db.Integer, primary_key=True)
    module = db.Column(db.String(16), nullable=False)
    subject_id = db.Column(db.Integer, nullable=False)
    # GameID is an opaque string (numeric surrogate for warehouse games,
    # composite like "20220311-GoodwinField-1" for legacy/cron games).
    game_id = db.Column(db.String(64), nullable=False)
    text = db.Column(db.Text, nullable=False, default="")
    author_id = db.Column(db.Integer, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=True)


def _row(module, subject_id, game_id):
    return db.session.scalar(db.select(GameNote).filter_by(
        module=module, subject_id=int(subject_id), game_id=str(game_id)))


def get_note(module, subject_id, game_id) -> str:
    if subject_id is None or game_id is None:
        return ""
    row = _row(module, subject_id, game_id)
    return row.text if row else ""


def upsert_note(module, subject_id, game_id, text, author_id=None) -> None:
    if subject_id is None or game_id is None:
        return
    text = (text or "").strip()
    if not text:
        delete_note(module, subject_id, game_id)
        return
    row = _row(module, subject_id, game_id)
    if row is None:
        row = GameNote(module=module, subject_id=int(subject_id), game_id=str(game_id))
        db.session.add(row)
    row.text = text
    row.author_id = author_id
    row.updated_at = datetime.now(timezone.utc)
    db.session.commit()


def delete_note(module, subject_id, game_id) -> None:
    if subject_id is None or game_id is None:
        return
    db.session.execute(db.delete(GameNote).filter_by(
        module=module, subject_id=int(subject_id), game_id=str(game_id)))
    db.session.commit()
