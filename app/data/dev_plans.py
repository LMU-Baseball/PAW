"""Per-player coach-authored development plans, stored in the app DB.

One plan per (module, subject_id) — e.g. a hitter's development plan. Coaches
write; players read. Mirrors app/data/notes.py but without a game_id.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.extensions import db


class DevPlan(db.Model):
    __tablename__ = "dev_plans"
    __table_args__ = (
        db.UniqueConstraint("module", "subject_id", name="uq_dev_plan"),
    )
    id = db.Column(db.Integer, primary_key=True)
    module = db.Column(db.String(16), nullable=False)
    subject_id = db.Column(db.Integer, nullable=False)
    text = db.Column(db.Text, nullable=False, default="")
    author_id = db.Column(db.Integer, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=True)


def _row(module, subject_id):
    return db.session.scalar(db.select(DevPlan).filter_by(
        module=module, subject_id=int(subject_id)))


def get_plan(module, subject_id) -> str:
    if subject_id is None:
        return ""
    row = _row(module, subject_id)
    return row.text if row else ""


def upsert_plan(module, subject_id, text, author_id=None) -> None:
    if subject_id is None:
        return
    text = (text or "").strip()
    if not text:
        delete_plan(module, subject_id)
        return
    row = _row(module, subject_id)
    if row is None:
        row = DevPlan(module=module, subject_id=int(subject_id))
        db.session.add(row)
    row.text = text
    row.author_id = author_id
    row.updated_at = datetime.now(timezone.utc)
    db.session.commit()


def delete_plan(module, subject_id) -> None:
    if subject_id is None:
        return
    db.session.execute(db.delete(DevPlan).filter_by(
        module=module, subject_id=int(subject_id)))
    db.session.commit()
