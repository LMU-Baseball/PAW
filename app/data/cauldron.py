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

from app.data import pitching as P
from app.data import pitching_caps
from app.data.cache import cached
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


# ================================= COMPUTE ===================================
#
# Off-speed pitch types for offspeed_zone -- everything that isn't a
# fastball-family pitch (Fastball/Sinker/Cutter), matching pitching.py's
# PITCH_COLORS vocabulary.
_OFFSPEED_TYPES = {"ChangeUp", "Curveball", "Slider", "Sweeper", "Splitter"}

# NON-STANDARD auto metrics whose scoring formula the coaching staff hasn't
# defined yet. Each stays a hard None until a coach signs off on a definition
# (see the seed placeholders in _SCORING_DEFAULTS).
_NON_STANDARD_METRICS = ("early_ahead", "pre2k_zone", "twok_kill", "count_work")


@cached
def compute_player_day(pitcher_id, play_date) -> dict:
    """One pitcher's raw AUTO-metric values for one calendar day, computed
    straight from GAMES pitch data (no DB read/write here -- pure compute).

    Reuses `app.data.pitching`'s existing pure transforms wherever they already
    compute a metric (strike_pct, fps_pct, k_pct, bb_pct, barrel_pct_ev), scoped
    to this one pitcher/day via `pitching_caps.range_pitches_for(pid, date, date)`
    -- start==end==play_date already gets the sibling-id union and Date scoping
    for free, exactly like the velo board's day-scoped reads.

    Returns `{}` if the pitcher threw no tracked GAMES pitches that day. A
    metric whose denominator is 0 for the day (no off-speed pitches, no balls
    in play, etc.) resolves to `None` for that metric, never 0 or NaN -- a
    scoreless/data-starved day must not read as "met the bar."
    """
    df = pitching_caps.range_pitches_for(pitcher_id, play_date, play_date)
    if df.empty:
        return {}

    metrics: dict[str, float | None] = {}

    # strike_pct: strikes / all pitches. df is non-empty (checked above), so
    # the denominator can't be 0.
    metrics["strike_pct"] = P.strike_pct(df)[0]

    # first_pitch_strike: strike rate on each PA's first pitch. Reuses
    # pitching.fps_pct, whose pitch_of_pa == 1 filter IS "balls == 0 and
    # strikes == 0" (the count before any pitch has been thrown can only be
    # 0-0 on the PA's first pitch).
    first_pitches = df[df["pitch_of_pa"] == 1]
    metrics["first_pitch_strike"] = P.fps_pct(df)[0] if len(first_pitches) else None

    # k_pct / bb_pct: strikeouts / walks per plate appearance faced.
    pa_count = P._pa_count(df)
    metrics["k_pct"] = P.k_pct(df)[0] if pa_count else None
    metrics["bb_pct"] = P.bb_pct(df)[0] if pa_count else None

    # offspeed_zone: in-zone rate on off-speed pitch types only (reuses
    # pitching.pitch_type's tagged/auto fallback + pitching's in-zone code set).
    pt = P.pitch_type(df)
    offspeed = df[pt.isin(_OFFSPEED_TYPES)]
    if len(offspeed):
        in_zone = offspeed["izt_zone"].isin(P._IN_ZONE_CODES)
        metrics["offspeed_zone"] = round(100.0 * float(in_zone.mean()), 1)
    else:
        metrics["offspeed_zone"] = None

    # barrel: barrels-allowed rate on balls in play (reuses pitching's
    # coach-simplified barrel_pct_ev: exit_speed >= 95, no LineDrive/FlyBall
    # qualifier). None (not 0) when there's no balls-in-play data to judge --
    # either no InPlay pitches, or exit_speed wasn't captured for any of them.
    if "exit_speed" not in df.columns:
        metrics["barrel"] = None
    else:
        bip_with_ev = df.loc[df["pitch_call"] == "InPlay", "exit_speed"].dropna()
        metrics["barrel"] = P.barrel_pct_ev(df)[0] if len(bip_with_ev) else None

    # NON-STANDARD metrics: no coach-approved formula yet (placeholders only
    # in the Task-1 scoring seed). Each stays None until defined.
    for metric in _NON_STANDARD_METRICS:
        # TODO(coach-def): formula pending coach sign-off for this metric.
        metrics[metric] = None

    return metrics
