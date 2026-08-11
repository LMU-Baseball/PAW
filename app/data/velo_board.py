"""Top Gun Velo Board storage layer: coach-editable pitcher-velo grid.

One row per (pitcher, season, week) so a coach can record/adjust a pitcher's
weekly velo numbers; the leaderboard and grid UI both read off this table.
Mirrors `app.data.precalc`'s ensure_tables/upsert idiom (CREATE TABLE IF NOT
EXISTS with an explicit PRIMARY KEY; `INSERT ... ON DUPLICATE KEY UPDATE` for
upserts) against the pooled RDS analytics engine.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import math

import pandas as pd
from sqlalchemy import text

from app.data.cache import cached
from app.db import get_engine, query_df

VELO_BOARD_TABLE = "velo_board_entries"

# Fastball/Sinker RelSpeed is what "velo" means everywhere on this board
# (matches the warehouse's vw_pitcher_appearance_velo filter -- see
# pitching_caps._pitcher_velo_appearances).
_VELO_PITCH_TYPES = "'Fastball', 'Sinker'"

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


# ========================== AUTO-POPULATION =================================
#
# Weekly velo + running max PR, computed live off Trackman (GAMES + BULLPEN)
# so a coach's grid pre-fills without manual entry. "Velo" = Fastball/Sinker
# RelSpeed only, matching pitching_caps's appearance-velo definition.

def week_start_for(d) -> str:
    """The Monday (ISO date string) of the week containing date `d`."""
    dt = date.fromisoformat(str(d)[:10])
    return (dt - timedelta(days=dt.weekday())).isoformat()


def _week_end(week_start) -> str:
    """ISO date string 6 days after `week_start` (the week's Sunday)."""
    return (date.fromisoformat(str(week_start)[:10]) + timedelta(days=6)).isoformat()


def _velo_series(pitcher_id, start=None, end=None) -> pd.Series:
    """Fastball/Sinker RelSpeed values from GAMES + BULLPEN for one raw
    trackman pitcher_id, optionally bounded by [start, end] (either open-
    ended). A direct PitcherId match (no sibling-id union) -- simplest
    correct version per the task brief."""
    pid = int(pitcher_id)
    g_clause = f"PitcherId = :p AND TaggedPitchType IN ({_VELO_PITCH_TYPES})"
    b_clause = g_clause
    params = {"p": pid}
    if start is not None:
        g_clause += " AND Date >= :s"
        b_clause += " AND DATE(Date) >= :s"
        params["s"] = str(start)
    if end is not None:
        g_clause += " AND Date <= :e"
        b_clause += " AND DATE(Date) <= :e"
        params["e"] = str(end)
    games = query_df(f"SELECT RelSpeed AS rel_speed FROM GAMES WHERE {g_clause}", params)
    bullpen = query_df(f"SELECT RelSpeed AS rel_speed FROM BULLPEN WHERE {b_clause}", params)
    return pd.concat([games["rel_speed"], bullpen["rel_speed"]], ignore_index=True).dropna()


@cached
def weekly_velo(pitcher_id, week_start) -> dict:
    """{"velo_avg", "velo_max"} over Fastball/Sinker RelSpeed (GAMES+BULLPEN)
    in the week starting `week_start` (Mon-Sun, inclusive). Both None if the
    pitcher threw no qualifying pitches that week."""
    velo = _velo_series(pitcher_id, start=week_start, end=_week_end(week_start))
    if velo.empty:
        return {"velo_avg": None, "velo_max": None}
    return {"velo_avg": float(velo.mean()), "velo_max": float(velo.max())}


@cached
def running_max_pr(pitcher_id, upto_week=None) -> float | None:
    """Max Fastball/Sinker RelSpeed (GAMES+BULLPEN) through the end of
    `upto_week` (inclusive), or all-time if `upto_week` is None. None if the
    pitcher has no qualifying pitches in range."""
    end = _week_end(upto_week) if upto_week is not None else None
    velo = _velo_series(pitcher_id, end=end)
    return None if velo.empty else float(velo.max())


def _stored_value(stored: pd.DataFrame, pitcher_id: int, week_start: str, col: str):
    """This pitcher's stored `col` for exactly `week_start`, or None."""
    if stored.empty:
        return None
    row = stored[(stored["pitcher_id"] == pitcher_id) & (stored["week_start"] == week_start)]
    if row.empty or pd.isna(row.iloc[0][col]):
        return None
    return float(row.iloc[0][col])


def _previous_stored_velo(stored: pd.DataFrame, pitcher_id: int, week_start: str) -> dict:
    """This pitcher's stored velo_avg/velo_max from their latest stored week
    strictly before `week_start`, or {"velo_avg": None, "velo_max": None} if
    there is no earlier stored week."""
    if stored.empty:
        return {"velo_avg": None, "velo_max": None}
    prior = stored[(stored["pitcher_id"] == pitcher_id) & (stored["week_start"] < week_start)]
    if prior.empty:
        return {"velo_avg": None, "velo_max": None}
    prev = prior.sort_values("week_start").iloc[-1]
    return {
        "velo_avg": None if pd.isna(prev["velo_avg"]) else float(prev["velo_avg"]),
        "velo_max": None if pd.isna(prev["velo_max"]) else float(prev["velo_max"]),
    }


def grid_rows(season_label, week_start) -> pd.DataFrame:
    """One row per rostered pitcher for the coach grid: auto-computed
    velo_avg/velo_max/max_pr, stored velo_goal/assessment (if a row already
    exists for this pitcher+week), and change_avg/change_max vs. the
    pitcher's previous STORED week.

    Deliberately NOT @cached: unlike weekly_velo/running_max_pr (pure
    Trackman reads), this merges live coach-edited `read_entries` data --
    caching it would serve stale velo_goal/assessment/change_* right after a
    coach saves the grid (Task 5's save-then-redraw flow)."""
    from app.data import pitching_caps  # lazy: avoid import cost when unused

    cols = ["pitcher_id", "pitcher_name", "velo_avg", "velo_max", "velo_goal",
            "assessment", "max_pr", "change_avg", "change_max"]
    roster = pitching_caps.lmu_pitchers(season_label)
    if roster.empty:
        return pd.DataFrame(columns=cols)

    stored = read_entries(season_label)
    rows = []
    for _, r in roster.iterrows():
        pid = int(r["PitcherId"])
        wv = weekly_velo(pid, week_start)
        prev = _previous_stored_velo(stored, pid, week_start)
        change_avg = (wv["velo_avg"] - prev["velo_avg"]
                      if wv["velo_avg"] is not None and prev["velo_avg"] is not None else None)
        change_max = (wv["velo_max"] - prev["velo_max"]
                       if wv["velo_max"] is not None and prev["velo_max"] is not None else None)
        rows.append({
            "pitcher_id": pid,
            "pitcher_name": r["Pitcher"],
            "velo_avg": wv["velo_avg"],
            "velo_max": wv["velo_max"],
            "velo_goal": _stored_value(stored, pid, week_start, "velo_goal"),
            "assessment": _stored_value(stored, pid, week_start, "assessment"),
            "max_pr": running_max_pr(pid, week_start),
            "change_avg": change_avg,
            "change_max": change_max,
        })
    return pd.DataFrame(rows, columns=cols)
