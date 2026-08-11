"""Top Gun Velo Board storage layer: coach-editable pitcher-velo grid.

One row per (pitcher, season, week) so a coach can record/adjust a pitcher's
weekly velo numbers; the leaderboard and grid UI both read off this table.
Mirrors `app.data.precalc`'s ensure_tables/upsert idiom (CREATE TABLE IF NOT
EXISTS with an explicit PRIMARY KEY; `INSERT ... ON DUPLICATE KEY UPDATE` for
upserts) against the pooled RDS analytics engine.
"""
from __future__ import annotations

from datetime import datetime, timezone

import math

import pandas as pd
from sqlalchemy import text

from app.db import get_engine, query_df

VELO_BOARD_TABLE = "velo_board_entries"

_DDL = f"""
    CREATE TABLE IF NOT EXISTS {VELO_BOARD_TABLE} (
        pitcher_id   BIGINT NOT NULL,
        pitcher_name VARCHAR(128),
        season_label VARCHAR(32) NOT NULL,
        week_start   VARCHAR(10) NOT NULL,
        velo_avg     FLOAT,
        velo_max     FLOAT,
        velo_goal    FLOAT,
        assessment   FLOAT,
        max_pr       FLOAT,
        updated_by   INT,
        updated_at   DATETIME,
        PRIMARY KEY (pitcher_id, season_label, week_start)
    )"""

# Non-PK columns that get overwritten on a repeat (pitcher_id, season_label,
# week_start) upsert.
_UPDATE_COLS = ("pitcher_name", "velo_avg", "velo_max", "velo_goal",
                "assessment", "max_pr", "updated_by", "updated_at")


def ensure_tables(engine=None) -> None:
    """Idempotently create velo_board_entries."""
    engine = engine or get_engine()
    with engine.begin() as conn:
        conn.execute(text(_DDL))


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _clean(value):
    """Scrub NaN/NaT -> None; leave everything else as-is."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def upsert_entries(rows: list[dict], updated_by=None) -> None:
    """Insert or update each row keyed by (pitcher_id, season_label,
    week_start). Missing optional columns default to None; NaN scrubbed to
    NULL. One transaction for the whole batch."""
    ensure_tables()
    if not rows:
        return
    now = _now()
    set_clause = ", ".join(f"{c} = VALUES({c})" for c in _UPDATE_COLS)
    sql = text(f"""
        INSERT INTO {VELO_BOARD_TABLE}
            (pitcher_id, pitcher_name, season_label, week_start,
             velo_avg, velo_max, velo_goal, assessment, max_pr,
             updated_by, updated_at)
        VALUES
            (:pitcher_id, :pitcher_name, :season_label, :week_start,
             :velo_avg, :velo_max, :velo_goal, :assessment, :max_pr,
             :updated_by, :updated_at)
        ON DUPLICATE KEY UPDATE {set_clause}
    """)
    with get_engine().begin() as conn:
        for row in rows:
            params = {
                "pitcher_id": int(row["pitcher_id"]),
                "pitcher_name": _clean(row.get("pitcher_name")),
                "season_label": row["season_label"],
                "week_start": row["week_start"],
                "velo_avg": _clean(row.get("velo_avg")),
                "velo_max": _clean(row.get("velo_max")),
                "velo_goal": _clean(row.get("velo_goal")),
                "assessment": _clean(row.get("assessment")),
                "max_pr": _clean(row.get("max_pr")),
                "updated_by": _clean(row["updated_by"]) if row.get("updated_by") is not None else updated_by,
                "updated_at": now,
            }
            conn.execute(sql, params)


def read_entries(season_label, week_start=None) -> pd.DataFrame:
    """All velo_board_entries rows for a season (optionally narrowed to one
    week_start)."""
    if week_start is not None:
        return query_df(
            f"SELECT * FROM {VELO_BOARD_TABLE} WHERE season_label = :s "
            f"AND week_start = :w",
            {"s": season_label, "w": week_start})
    return query_df(
        f"SELECT * FROM {VELO_BOARD_TABLE} WHERE season_label = :s",
        {"s": season_label})
