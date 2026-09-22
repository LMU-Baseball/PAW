"""Coach-managed date-level HitTrax practice plans."""
from __future__ import annotations

from datetime import date, datetime, timezone

from app.extensions import db


SEED_PLAN_NAMES = ("Fastball", "Running Fastball", "Curveball", "Slider")


class PracticePlan(db.Model):
    __tablename__ = "practice_plans"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    archived_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False,
                            default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, nullable=False,
                            default=lambda: datetime.now(timezone.utc),
                            onupdate=lambda: datetime.now(timezone.utc))


class PracticePlanAssignment(db.Model):
    __tablename__ = "practice_plan_assignments"
    __table_args__ = (
        db.UniqueConstraint("practice_date", "plan_id", name="uq_practice_date_plan"),
        db.Index("ix_practice_plan_assignment_date", "practice_date"),
    )
    id = db.Column(db.Integer, primary_key=True)
    practice_date = db.Column(db.Date, nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey("practice_plans.id"), nullable=False)
    assigned_by = db.Column(db.Integer, nullable=True)
    assigned_at = db.Column(db.DateTime, nullable=False,
                             default=lambda: datetime.now(timezone.utc))


def _clean_name(name: str) -> str:
    value = (name or "").strip()
    if not value:
        raise ValueError("Plan name cannot be empty")
    return value


def list_plans(*, include_archived: bool = False):
    query = db.select(PracticePlan).order_by(PracticePlan.name)
    if not include_archived:
        query = query.where(PracticePlan.archived_at.is_(None))
    return list(db.session.scalars(query))


def seed_plans() -> None:
    existing = {p.name.casefold() for p in list_plans(include_archived=True)}
    for name in SEED_PLAN_NAMES:
        if name.casefold() not in existing:
            db.session.add(PracticePlan(name=name))
    db.session.commit()


def assignments_for_dates(dates):
    values = [_as_date(d) for d in dates or []]
    if not values:
        return {}
    rows = db.session.execute(
        db.select(PracticePlanAssignment.practice_date, PracticePlan.name)
        .join(PracticePlan, PracticePlan.id == PracticePlanAssignment.plan_id)
        .where(PracticePlanAssignment.practice_date.in_(values))
        .where(PracticePlan.archived_at.is_(None))
        .order_by(PracticePlan.name)
    ).all()
    result = {}
    for day, name in rows:
        result.setdefault(day.isoformat(), []).append(name)
    return result


def replace_assignments(dates, plan_names, *, actor_is_coach: bool,
                        actor_id: int | None = None) -> None:
    if not actor_is_coach:
        raise PermissionError("Only coaches may assign practice plans")
    values = list(dict.fromkeys(_as_date(d) for d in dates or []))
    names = list(dict.fromkeys(_clean_name(n) for n in plan_names or []))
    if not values:
        raise ValueError("Select at least one practice date")
    active = list_plans()
    by_name = {p.name.casefold(): p for p in active}
    try:
        plans = [by_name[n.casefold()] for n in names]
    except KeyError as exc:
        raise ValueError("Select only active practice plans") from exc
    for day in values:
        db.session.execute(db.delete(PracticePlanAssignment).where(
            PracticePlanAssignment.practice_date == day))
        for plan in plans:
            db.session.add(PracticePlanAssignment(
                practice_date=day, plan_id=plan.id, assigned_by=actor_id))
    db.session.commit()


def create_plan(name: str, *, actor_is_coach: bool):
    if not actor_is_coach:
        raise PermissionError("Only coaches may create practice plans")
    value = _clean_name(name)
    if any(p.name.casefold() == value.casefold()
           for p in list_plans(include_archived=True)):
        raise ValueError("A practice plan with that name already exists")
    row = PracticePlan(name=value)
    db.session.add(row)
    db.session.commit()
    return row


def rename_plan(plan_id: int, name: str, *, actor_is_coach: bool):
    if not actor_is_coach:
        raise PermissionError("Only coaches may rename practice plans")
    value = _clean_name(name)
    row = db.session.get(PracticePlan, int(plan_id))
    if row is None:
        raise ValueError("Practice plan not found")
    if any(p.id != row.id and p.name.casefold() == value.casefold()
           for p in list_plans(include_archived=True)):
        raise ValueError("A practice plan with that name already exists")
    row.name = value
    db.session.commit()
    return row


def archive_plan(plan_id: int, *, actor_is_coach: bool):
    if not actor_is_coach:
        raise PermissionError("Only coaches may archive practice plans")
    row = db.session.get(PracticePlan, int(plan_id))
    if row is None:
        raise ValueError("Practice plan not found")
    row.archived_at = datetime.now(timezone.utc)
    db.session.commit()
    return row


def _as_date(value) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])
