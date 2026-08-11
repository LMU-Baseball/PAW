"""Competitive Cauldron storage layer: daily team pitching competition.

Three coach-editable tables, mirroring `app.data.velo_board`'s ensure_tables/
upsert idiom (CREATE TABLE IF NOT EXISTS with an explicit PRIMARY KEY;
`INSERT ... ON DUPLICATE KEY UPDATE` for upserts) against the pooled RDS
analytics engine:

  cauldron_scoring -- one row per metric: threshold/direction/points config a
                      coach tunes in-app. Seeded with placeholders that must
                      never be silently clobbered by a re-seed.
  cauldron_teams   -- one row per (player, cycle): which team a player is on
                      for a given competition cycle.
  cauldron_daily   -- one row per (player, play_date, metric): the day's raw
                      value + points awarded (auto-computed or coach-entered).
"""
from __future__ import annotations

from datetime import datetime, timezone

import math

import pandas as pd
from sqlalchemy import text

from app.db import get_engine, query_df

SCORING_TABLE = "cauldron_scoring"
TEAMS_TABLE = "cauldron_teams"
DAILY_TABLE = "cauldron_daily"

_DDL = {
    SCORING_TABLE: f"""
        CREATE TABLE IF NOT EXISTS {SCORING_TABLE} (
            metric        VARCHAR(32) NOT NULL,
            label         VARCHAR(48),
            threshold     FLOAT,
            direction     VARCHAR(4),
            points_met    INT,
            points_missed INT,
            is_manual     BOOL,
            min_sample    INT,
            sort_order    INT,
            PRIMARY KEY (metric)
        )""",
    TEAMS_TABLE: f"""
        CREATE TABLE IF NOT EXISTS {TEAMS_TABLE} (
            player_id  BIGINT NOT NULL,
            cycle_id   VARCHAR(24) NOT NULL,
            team       VARCHAR(24),
            updated_by INT,
            updated_at DATETIME,
            PRIMARY KEY (player_id, cycle_id)
        )""",
    DAILY_TABLE: f"""
        CREATE TABLE IF NOT EXISTS {DAILY_TABLE} (
            player_id  BIGINT NOT NULL,
            play_date  VARCHAR(10) NOT NULL,
            metric     VARCHAR(32) NOT NULL,
            raw_value  FLOAT,
            points     INT,
            source     VARCHAR(8),
            updated_by INT,
            updated_at DATETIME,
            PRIMARY KEY (player_id, play_date, metric)
        )""",
}

# Placeholder metric config the coach tunes later in-app. Order here doubles
# as the default sort_order (1-indexed). Auto metrics carry a min_sample (the
# rate needs this many qualifying pitches/PAs before it counts); manual
# metrics have no threshold/direction/min_sample -- a coach enters points
# directly on cauldron_daily for those.
_SCORING_DEFAULTS = [
    # metric,              label,               threshold, direction, points_met, points_missed, is_manual, min_sample
    ("strike_pct",         "Strike%",           55.0,  "gte", 20, -10, False, 5),
    ("first_pitch_strike", "FPS",               65.0,  "gte", 20, -10, False, 5),
    ("early_ahead",        "Early & Ahead",     70.0,  "gte", 20, -10, False, 5),
    ("pre2k_zone",         "Pre-2K Zone",       48.0,  "gte", 20, -10, False, 5),
    ("twok_kill",          "2K Kill",           55.0,  "gte", 20, -10, False, 5),
    ("k_pct",              "K%",                27.0,  "gte", 20, -10, False, 5),
    ("bb_pct",             "BB%",               6.0,   "lte", 20, -10, False, 5),
    ("offspeed_zone",      "Off-Speed Zone",    55.0,  "gte", 20, -10, False, 5),
    ("count_work",         "Count Work",        50.0,  "gte", 20, -10, False, 5),
    ("barrel",             "Barrel",            5.0,   "lte", 20, -10, False, 5),
    ("mod_command",        "Mod Command",       None,  None,  20, -10, True,  None),
    ("recovery_command",   "Recovery Command",  None,  None,  20, -10, True,  None),
    ("ah_rehab",           "AH/Rehab",          None,  None,  20, -10, True,  None),
]

_DAILY_UPDATE_COLS = ("raw_value", "points", "source", "updated_by", "updated_at")


def ensure_tables(engine=None) -> None:
    """Idempotently create cauldron_scoring/cauldron_teams/cauldron_daily."""
    engine = engine or get_engine()
    with engine.begin() as conn:
        for ddl in _DDL.values():
            conn.execute(text(ddl))


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


# ============================== SCORING CONFIG ===============================

def seed_default_scoring() -> None:
    """Insert the placeholder metric config rows if they don't already exist.
    `ON DUPLICATE KEY UPDATE metric=metric` is a no-op on conflict, so a
    re-seed (e.g. on every app boot) NEVER overwrites a coach's tuned
    threshold/points -- only fills in metrics that are missing."""
    ensure_tables()
    sql = text(f"""
        INSERT INTO {SCORING_TABLE}
            (metric, label, threshold, direction, points_met, points_missed,
             is_manual, min_sample, sort_order)
        VALUES
            (:metric, :label, :threshold, :direction, :points_met, :points_missed,
             :is_manual, :min_sample, :sort_order)
        ON DUPLICATE KEY UPDATE metric = metric
    """)
    with get_engine().begin() as conn:
        for i, (metric, label, threshold, direction, points_met, points_missed,
                is_manual, min_sample) in enumerate(_SCORING_DEFAULTS, start=1):
            conn.execute(sql, {
                "metric": metric,
                "label": label,
                "threshold": threshold,
                "direction": direction,
                "points_met": points_met,
                "points_missed": points_missed,
                "is_manual": is_manual,
                "min_sample": min_sample,
                "sort_order": i,
            })


def read_scoring() -> pd.DataFrame:
    """All cauldron_scoring rows, ordered by sort_order."""
    return query_df(f"SELECT * FROM {SCORING_TABLE} ORDER BY sort_order")


# ================================== DAILY ====================================

def upsert_daily(rows: list[dict], updated_by=None) -> None:
    """Insert or update each row keyed by (player_id, play_date, metric).
    Missing optional columns default to None; NaN scrubbed to NULL. One
    transaction for the whole batch."""
    ensure_tables()
    if not rows:
        return
    now = _now()
    set_clause = ", ".join(f"{c} = VALUES({c})" for c in _DAILY_UPDATE_COLS)
    sql = text(f"""
        INSERT INTO {DAILY_TABLE}
            (player_id, play_date, metric, raw_value, points, source,
             updated_by, updated_at)
        VALUES
            (:player_id, :play_date, :metric, :raw_value, :points, :source,
             :updated_by, :updated_at)
        ON DUPLICATE KEY UPDATE {set_clause}
    """)
    with get_engine().begin() as conn:
        for row in rows:
            params = {
                "player_id": int(row["player_id"]),
                "play_date": row["play_date"],
                "metric": row["metric"],
                "raw_value": _clean(row.get("raw_value")),
                "points": _clean(row.get("points")),
                "source": _clean(row.get("source")),
                "updated_by": _clean(row["updated_by"]) if row.get("updated_by") is not None else updated_by,
                "updated_at": now,
            }
            conn.execute(sql, params)


def read_daily(play_date=None, player_id=None) -> pd.DataFrame:
    """cauldron_daily rows, optionally narrowed to a play_date and/or
    player_id."""
    clauses, params = [], {}
    if play_date is not None:
        clauses.append("play_date = :d")
        params["d"] = play_date
    if player_id is not None:
        clauses.append("player_id = :p")
        params["p"] = int(player_id)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    return query_df(f"SELECT * FROM {DAILY_TABLE}{where}", params)


# ================================== TEAMS ====================================

def set_team(player_id, cycle_id, team, updated_by=None) -> None:
    """Upsert one player's team assignment for a competition cycle."""
    ensure_tables()
    sql = text(f"""
        INSERT INTO {TEAMS_TABLE} (player_id, cycle_id, team, updated_by, updated_at)
        VALUES (:player_id, :cycle_id, :team, :updated_by, :updated_at)
        ON DUPLICATE KEY UPDATE team = VALUES(team), updated_by = VALUES(updated_by),
            updated_at = VALUES(updated_at)
    """)
    with get_engine().begin() as conn:
        conn.execute(sql, {
            "player_id": int(player_id),
            "cycle_id": cycle_id,
            "team": _clean(team),
            "updated_by": _clean(updated_by),
            "updated_at": _now(),
        })


def read_teams(cycle_id) -> pd.DataFrame:
    """All cauldron_teams rows for one competition cycle."""
    return query_df(f"SELECT * FROM {TEAMS_TABLE} WHERE cycle_id = :c", {"c": cycle_id})
