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
from app.data import seasons
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


def _ensure_column(conn, table, col, coldef) -> None:
    """Additive, idempotent migration: ADD COLUMN only when it's missing (MySQL
    has no portable ADD COLUMN IF NOT EXISTS, so gate on information_schema)."""
    exists = conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = :t AND column_name = :c"),
        {"t": table, "c": col}).scalar()
    if not exists:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {coldef}"))


def ensure_tables(engine=None) -> None:
    """Idempotently create cauldron_scoring/cauldron_teams/cauldron_daily, and
    migrate cauldron_teams to carry the (additive) is_captain flag."""
    engine = engine or get_engine()
    with engine.begin() as conn:
        for ddl in _DDL.values():
            conn.execute(text(ddl))
        _ensure_column(conn, TEAMS_TABLE, "is_captain",
                       "is_captain TINYINT(1) NOT NULL DEFAULT 0")


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
    ensure_tables()
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


def read_daily(play_date=None, player_id=None, start=None, end=None) -> pd.DataFrame:
    """cauldron_daily rows, optionally narrowed to a single play_date, a
    player_id, and/or an inclusive [start, end] play_date window (the weekly
    scoreboard passes the Mon..Sun window)."""
    ensure_tables()
    clauses, params = [], {}
    if play_date is not None:
        clauses.append("play_date = :d")
        params["d"] = play_date
    if player_id is not None:
        clauses.append("player_id = :p")
        params["p"] = int(player_id)
    if start is not None:
        clauses.append("play_date >= :start")
        params["start"] = start
    if end is not None:
        clauses.append("play_date <= :end")
        params["end"] = end
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


def set_captain(player_id, cycle_id, updated_by=None) -> None:
    """Mark `player_id` as the captain of their team for `cycle_id`, clearing
    any prior captain on that same team (one captain per team). No-op if the
    player isn't assigned to a team in this cycle."""
    ensure_tables()
    with get_engine().begin() as conn:
        row = conn.execute(text(
            f"SELECT team FROM {TEAMS_TABLE} WHERE player_id = :p AND cycle_id = :c"),
            {"p": int(player_id), "c": cycle_id}).fetchone()
        if row is None or row[0] is None:
            return
        conn.execute(text(
            f"UPDATE {TEAMS_TABLE} "
            f"SET is_captain = CASE WHEN player_id = :p THEN 1 ELSE 0 END, "
            f"    updated_by = CASE WHEN player_id = :p THEN :u ELSE updated_by END, "
            f"    updated_at = CASE WHEN player_id = :p THEN :now ELSE updated_at END "
            f"WHERE cycle_id = :c AND team = :team"),
            {"p": int(player_id), "c": cycle_id, "team": row[0],
             "u": _clean(updated_by), "now": _now()})


def read_teams(cycle_id) -> pd.DataFrame:
    """All cauldron_teams rows for one competition cycle (carries is_captain)."""
    ensure_tables()
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


def _metrics_from_df(df) -> dict:
    """Raw AUTO-metric values for ONE pitcher-day, from an already-loaded pitch
    frame (that pitcher's GAMES pitches for a single day). Pure compute -- the
    single seam shared by `compute_player_day` (one pitcher) and
    `compute_players_day` (batched), so both produce identical results by
    construction. Caller guarantees `df` is non-empty and holds exactly one
    pitcher's pitches.

    Reuses `app.data.pitching`'s pure transforms wherever they already compute a
    metric. A metric whose denominator is 0 for the day (no off-speed pitches,
    no balls in play, etc.) resolves to `None`, never 0 or NaN -- a
    scoreless/data-starved day must not read as "met the bar."
    """
    metrics: dict[str, float | None] = {}

    # strike_pct: strikes / all pitches. df is non-empty (caller guarantees), so
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


@cached
def compute_player_day(pitcher_id, play_date) -> dict:
    """One pitcher's raw AUTO-metric values for one calendar day, computed
    straight from GAMES (`pitching_caps.range_pitches_for(pid, date, date)` --
    start==end gets the sibling-id union + Date scoping for free). Returns `{}`
    if the pitcher threw no tracked GAMES pitches that day. Delegates the metric
    math to `_metrics_from_df` (shared with the batched `compute_players_day`)."""
    df = pitching_caps.range_pitches_for(pitcher_id, play_date, play_date)
    return _metrics_from_df(df) if not df.empty else {}


@cached
def compute_players_day(pitcher_ids, play_date) -> dict:
    """BATCHED `compute_player_day`: one GAMES query for ALL `pitcher_ids` on
    `play_date` (sibling-union) instead of one round-trip per pitcher, then each
    pitcher's metrics computed in pandas via the SAME `_metrics_from_df`.

    Returns `{pitcher_id: metrics_dict}` for every id passed in; a pitcher with
    no tracked pitches that day maps to `{}` (exactly like `compute_player_day`).
    Parity with the per-pitcher path is guaranteed by construction: each
    pitcher's row slice (PitcherId in that pitcher's sibling set, Date ==
    play_date) is the same frame `range_pitches_for` would load, and both feed
    the identical `_metrics_from_df`. Sibling sets are name-based and disjoint
    across pitchers, so slicing by canonical id can't cross-contaminate."""
    ids = [int(p) for p in pitcher_ids]
    result: dict[int, dict] = {pid: {} for pid in ids}
    if not ids:
        return result

    sib_to_canon: dict[int, int] = {}
    for pid in ids:
        for sid in pitching_caps._sibling_pitcher_ids(pid):
            sib_to_canon[int(sid)] = pid
    all_sibs = sorted(sib_to_canon)
    if not all_sibs:
        return result

    ph, params = pitching_caps._in_clause(all_sibs)
    params["d"] = str(play_date)
    df = query_df(
        f"SELECT {pitching_caps._PITCH_SELECT} FROM GAMES "
        f"WHERE PitcherId IN ({ph}) AND Date BETWEEN :d AND :d "
        f"ORDER BY GameID, PitchNo", params)
    if df.empty:
        return result

    df = df.copy()
    df["_canon"] = df["pitcher_id"].astype(int).map(sib_to_canon)
    for canon, sub in df.groupby("_canon"):
        sub = sub.drop(columns=["_canon"])
        if not sub.empty:
            result[int(canon)] = _metrics_from_df(sub)
    return result


# ================================= SCORING ===================================

def score_value(metric, raw_value, scoring_row) -> int | None:
    """FIXED scoring: compare `raw_value` to `scoring_row`'s threshold per its
    direction ('gte' -> met if raw >= threshold; 'lte' -> met if raw <=
    threshold). Returns `int(points_met)` when met, else `int(points_missed)`.

    `None` if `raw_value` is `None`/NaN -- a scoreless/data-starved metric must
    never resolve to a score. `scoring_row` may be a dict or a `read_scoring()`
    DataFrame row (both support `row["col"]`). `metric` is unused by the FIXED
    formula itself (threshold/direction/points already fully describe it) --
    it's accepted so callers can pass it straight through without unpacking,
    and so a future non-FIXED scoring mode has a natural place to branch on it.
    min_sample gating is the CALLER's job (`score_day` knows the day's
    pitch/PA count; this function only ever sees the metric's already-computed
    raw value), not this function's.

    `None` also if `scoring_row` isn't a scoreable FIXED row -- a `direction`
    outside `('gte', 'lte')` (e.g. `None`, on a manual-metric row) or a `None`
    `threshold` has nothing to compare `raw_value` against, so this returns
    `None` instead of raising."""
    if raw_value is None:
        return None
    try:
        if pd.isna(raw_value):
            return None
    except (TypeError, ValueError):
        pass
    if scoring_row["direction"] not in ("gte", "lte") or scoring_row["threshold"] is None:
        return None
    met = (raw_value >= scoring_row["threshold"] if scoring_row["direction"] == "gte"
           else raw_value <= scoring_row["threshold"])
    return int(scoring_row["points_met"]) if met else int(scoring_row["points_missed"])


def score_day(play_date, season=None) -> int:
    """Auto-score one calendar day for every rostered pitcher
    (`pitching_caps.lmu_pitchers(season or seasons.current_season())`):
    compute each pitcher's raw AUTO metrics (`compute_player_day`), score them
    against the coach's tuned config (`read_scoring()`), and upsert the
    results as `source='auto'` rows via `upsert_daily`.

    NEVER overwrites a coach's `source='manual'` row for the same (player,
    play_date, metric) -- existing rows for the day are read up front
    (`read_daily(play_date)`) and any (player_id, metric) already stored with
    `source='manual'` is skipped outright, before scoring is even attempted.

    Metrics configured `is_manual` (no threshold/direction to score against)
    and metrics with a `None` raw value (denominator was 0 for the day, or the
    pitcher threw no tracked pitches) are skipped -- no row is written for
    either. min_sample gating beyond that is NOT implemented here: a coach
    hasn't yet specified how sample size should be counted per metric (pitches
    vs. PAs vs. balls in play differ per metric), so every day with a non-None
    raw value scores, regardless of how few pitches/PAs it's built on.

    Returns the number of rows written (upserted)."""
    scoring = read_scoring()
    if scoring.empty:
        return 0
    scoring_by_metric = {row["metric"]: row for _, row in scoring.iterrows()}

    roster = pitching_caps.lmu_pitchers(season or seasons.current_season())
    if roster.empty:
        return 0
    pids = [int(r["PitcherId"]) for _, r in roster.iterrows()]
    metrics_by_pid = compute_players_day(pids, play_date)  # one batched query

    existing = read_daily(play_date)
    manual_keys = set()
    if not existing.empty:
        manual = existing[existing["source"] == "manual"]
        manual_keys = set(zip(manual["player_id"].astype(int), manual["metric"]))

    rows = []
    for pid in pids:
        metrics = metrics_by_pid.get(pid, {})
        for metric, raw_value in metrics.items():
            scoring_row = scoring_by_metric.get(metric)
            if scoring_row is None or bool(scoring_row.get("is_manual")):
                continue  # no FIXED config to score against (manual metric)
            if (pid, metric) in manual_keys:
                continue  # a coach's manual entry always wins
            points = score_value(metric, raw_value, scoring_row)
            if points is None:
                continue  # raw_value was None -- nothing to score
            rows.append({
                "player_id": pid,
                "play_date": play_date,
                "metric": metric,
                "raw_value": raw_value,
                "points": points,
                "source": "auto",
            })

    upsert_daily(rows)
    return len(rows)


# ============================== AGGREGATION ==================================

def player_totals(cycle_id, start=None, end=None) -> pd.DataFrame:
    """Points summed per player from `cauldron_daily`, for players rostered
    onto a team in `cycle_id` (`read_teams`), optionally bounded to
    `play_date` in `[start, end]` (either end open, both inclusive). A
    rostered player with no scored days yet still appears, with `total` = 0.

    Cols: `player_id, total`."""
    cols = ["player_id", "total"]
    teams = read_teams(cycle_id)
    if teams.empty:
        return pd.DataFrame(columns=cols)

    clauses, params = [], {}
    if start is not None:
        clauses.append("play_date >= :start")
        params["start"] = str(start)
    if end is not None:
        clauses.append("play_date <= :end")
        params["end"] = str(end)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    daily = query_df(f"SELECT player_id, points FROM {DAILY_TABLE}{where}", params)

    player_ids = teams["player_id"].astype(int)
    result = pd.DataFrame({"player_id": player_ids})
    if daily.empty:
        result["total"] = 0
        return result.reset_index(drop=True)

    totals = daily.groupby("player_id")["points"].sum()
    result["total"] = result["player_id"].map(totals).fillna(0).astype(int)
    return result.reset_index(drop=True)


def team_totals(cycle_id) -> pd.DataFrame:
    """Points summed per TEAM for one competition cycle: `cauldron_daily`
    joined to `cauldron_teams` (cycle_id-scoped) on player_id. A team with
    rostered players but zero points scored yet still appears, with `total` =
    0.

    Cols: `team, total`."""
    cols = ["team", "total"]
    teams = read_teams(cycle_id)
    if teams.empty:
        return pd.DataFrame(columns=cols)

    daily = query_df(f"SELECT player_id, points FROM {DAILY_TABLE}")
    merged = teams[["player_id", "team"]].merge(daily, on="player_id", how="left")
    result = merged.groupby("team", as_index=False)["points"].sum()
    result = result.rename(columns={"points": "total"})
    result["total"] = result["total"].fillna(0).astype(int)
    return result[cols]
