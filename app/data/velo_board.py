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
from app.data.seasons import season_bounds
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


def _velo_rows(pitcher_id, start=None, end=None) -> pd.DataFrame:
    """Fastball/Sinker (rel_speed, dt) rows from GAMES + BULLPEN for one raw
    trackman pitcher_id, optionally bounded by [start, end] (either open-
    ended). Unions Trackman sibling ids (`pitching_caps._sibling_pitcher_ids`)
    the same way `_pitcher_velo_appearances`/`velo_trend` do -- Trackman
    splits one pitcher across ids, so a direct `PitcherId = :p` match would
    under-count season totals relative to last_velo/trend in the same
    leaderboard row. GAMES and BULLPEN share the same raw trackman id space,
    so the GAMES-derived sibling set applies to both halves. Keeps `dt`
    alongside each value (unlike `_velo_series`) so callers can locate e.g.
    the date a max occurred."""
    from app.data import pitching_caps  # lazy: avoid import cost when unused

    ph, idp = pitching_caps._in_clause(pitching_caps._sibling_pitcher_ids(int(pitcher_id)))
    g_clause = f"PitcherId IN ({ph}) AND TaggedPitchType IN ({_VELO_PITCH_TYPES})"
    b_clause = g_clause
    params = dict(idp)
    if start is not None:
        g_clause += " AND Date >= :s"
        b_clause += " AND DATE(Date) >= :s"
        params["s"] = str(start)
    if end is not None:
        g_clause += " AND Date <= :e"
        b_clause += " AND DATE(Date) <= :e"
        params["e"] = str(end)
    games = query_df(f"SELECT RelSpeed AS rel_speed, Date AS dt FROM GAMES WHERE {g_clause}", params)
    bullpen = query_df(f"SELECT RelSpeed AS rel_speed, DATE(Date) AS dt FROM BULLPEN WHERE {b_clause}", params)
    return pd.concat([games, bullpen], ignore_index=True).dropna(subset=["rel_speed"]).reset_index(drop=True)


def _velo_series(pitcher_id, start=None, end=None) -> pd.Series:
    """Fastball/Sinker RelSpeed values from GAMES + BULLPEN for one raw
    trackman pitcher_id, optionally bounded by [start, end]. Thin wrapper
    over `_velo_rows` that drops the date column."""
    return _velo_rows(pitcher_id, start=start, end=end)["rel_speed"]


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
    """One row per rostered pitcher for the coach grid: velo_avg/velo_max/
    max_pr/velo_goal/assessment, and change_avg/change_max vs. the pitcher's
    previous STORED week.

    Weekly rows are stored SNAPSHOTS a coach can override: when a stored
    (pitcher_id, season_label, week_start) row already exists, its stored
    velo_avg/velo_max/max_pr/velo_goal/assessment win outright -- even if a
    column within that row is NULL -- so a saved override sticks instead of
    being silently overwritten by a recomputed Trackman value on re-render.
    Only when NO stored row exists yet does velo_avg/velo_max/max_pr prefill
    live from Trackman (`weekly_velo`/`running_max_pr`), same as before.
    change_avg/change_max are always COMPUTED off whichever velo_avg/
    velo_max is being shown (stored or prefilled) vs. the pitcher's previous
    STORED week -- there's no stored snapshot of them to defer to.

    Deliberately NOT @cached: unlike weekly_velo/running_max_pr (pure
    Trackman reads), this merges live coach-edited `read_entries` data --
    caching it would serve stale values right after a coach saves the grid
    (Task 5's save-then-redraw flow)."""
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
        this_week_stored = not stored.empty and not stored[
            (stored["pitcher_id"] == pid) & (stored["week_start"] == week_start)].empty
        if this_week_stored:
            velo_avg = _stored_value(stored, pid, week_start, "velo_avg")
            velo_max = _stored_value(stored, pid, week_start, "velo_max")
            max_pr = _stored_value(stored, pid, week_start, "max_pr")
        else:
            wv = weekly_velo(pid, week_start)
            velo_avg, velo_max = wv["velo_avg"], wv["velo_max"]
            max_pr = running_max_pr(pid, week_start)

        prev = _previous_stored_velo(stored, pid, week_start)
        change_avg = (velo_avg - prev["velo_avg"]
                      if velo_avg is not None and prev["velo_avg"] is not None else None)
        change_max = (velo_max - prev["velo_max"]
                       if velo_max is not None and prev["velo_max"] is not None else None)
        rows.append({
            "pitcher_id": pid,
            "pitcher_name": r["Pitcher"],
            "velo_avg": velo_avg,
            "velo_max": velo_max,
            "velo_goal": _stored_value(stored, pid, week_start, "velo_goal"),
            "assessment": _stored_value(stored, pid, week_start, "assessment"),
            "max_pr": max_pr,
            "change_avg": change_avg,
            "change_max": change_max,
        })
    return pd.DataFrame(rows, columns=cols)


# =========================== PLAYER LEADERBOARD ==============================
#
# Player-facing view: one row per rostered pitcher, ranked by their season-best
# velo. Unlike grid_rows, this has no coach-edited columns to go stale, so it's
# safe to @cached like the other pure-Trackman reads above.

def _last_bullpen_velo(pitcher_id) -> dict:
    """{"last_velo", "last_date"}: the most recent BULLPEN session's avg
    Fastball/Sinker RelSpeed + that session's date, for a pitcher who threw no
    qualifying game this season. Both None if the pitcher has no bullpen
    history. Fastball/Sinker (not bullpen.py's Fastball-only avg_fb_velo) to
    stay consistent with this module's velo definition."""
    df = query_df(
        f"SELECT DATE(Date) AS dt, RelSpeed AS rel_speed FROM BULLPEN "
        f"WHERE PitcherId = :p AND TaggedPitchType IN ({_VELO_PITCH_TYPES})",
        {"p": int(pitcher_id)},
    )
    df = df.dropna(subset=["rel_speed", "dt"])
    if df.empty:
        return {"last_velo": None, "last_date": None}
    last_date = df["dt"].max()
    return {"last_velo": float(df.loc[df["dt"] == last_date, "rel_speed"].mean()),
            "last_date": str(last_date)}


@cached
def leaderboard(season_label) -> pd.DataFrame:
    """One row per rostered pitcher (`pitching_caps.lmu_pitchers`), sorted by
    `season_max` descending (None/NaN last):

        pitcher_name, season_max, season_max_date, season_avg,
        last_velo, last_date, versus, trend

    `season_max`/`season_avg`/`season_max_date`: max/mean/date-of-max of the
    season's Fastball/Sinker RelSpeed (GAMES + BULLPEN, season-bounded).

    `last_velo`/`last_date`/`versus`: the pitcher's most recent in-season GAME
    appearance (`pitching_caps._pitcher_velo_appearances`) -- avg velo, date,
    and opponent. Opponent is identified the same way `game_context` does (via
    `HomeTeamForeignID == LMU_TEAM_ID`, NOT by name-matching a "LMU" string),
    so it works regardless of how LMU's team name is spelled in a given row.
    If the pitcher has no game this season, falls back to their most recent
    BULLPEN session (`_last_bullpen_velo`) with `versus` = None.

    `trend`: `pitching_caps.velo_trend` velo_change (signed float) from the
    pitcher's most recent appearance WITHIN this season -- filtered to the
    season's [s, e] Date bounds before taking the last row, so a past-season
    leaderboard doesn't reach into a later season's most recent appearance.
    None if unknown (e.g. no appearance in this season, or the season's first
    appearance -- velo_trend's LAG has nothing to diff against).
    """
    from app.data import pitching_caps  # lazy: avoid import cost when unused

    cols = ["pitcher_name", "season_max", "season_max_date", "season_avg",
            "last_velo", "last_date", "versus", "trend"]
    roster = pitching_caps.lmu_pitchers(season_label)
    if roster.empty:
        return pd.DataFrame(columns=cols)

    s, e = season_bounds(season_label)
    rows = []
    for _, r in roster.iterrows():
        pid = int(r["PitcherId"])

        season_rows = _velo_rows(pid, start=s, end=e)
        if season_rows.empty:
            season_max = season_avg = season_max_date = None
        else:
            season_max = float(season_rows["rel_speed"].max())
            season_avg = float(season_rows["rel_speed"].mean())
            season_max_date = str(season_rows.loc[season_rows["rel_speed"].idxmax(), "dt"])

        # NOTE: filter by the season's [s, e] Date bounds, not by matching
        # `apps["season_label"]` -- that column is pitching_caps's derived
        # half-year label ("Spring 2026"/"Fall 2025"), a different format
        # from the academic-year `season_label` this function receives
        # ("2025/2026"), so a direct string match would never hit.
        apps = pitching_caps._pitcher_velo_appearances(pid)
        season_apps = apps[(apps["game_date"] >= s) & (apps["game_date"] <= e)] if not apps.empty else apps
        if not season_apps.empty:
            season_apps = season_apps.sort_values("game_date", ascending=False, kind="mergesort")
            last_row = season_apps.iloc[0]
            last_velo = float(last_row["appearance_avg_velo"])
            last_date = str(last_row["game_date"])
            ctx = pitching_caps.game_context(last_row["game_id"])
            versus = ctx["away_team"] if ctx["lmu_is_home"] else ctx["home_team"]
        else:
            bp = _last_bullpen_velo(pid)
            last_velo, last_date, versus = bp["last_velo"], bp["last_date"], None

        # Season-scope the trend to [s, e] before taking the last row --
        # velo_trend is all-time/chronological, so on a PAST season's
        # leaderboard the unfiltered `.iloc[-1]` would reach into a LATER
        # season's most recent appearance instead of this season's.
        vt = pitching_caps.velo_trend(pid)
        vt_season = vt[(vt["game_date"] >= s) & (vt["game_date"] <= e)] if not vt.empty else vt
        trend = (float(vt_season.iloc[-1]["velo_change"])
                 if not vt_season.empty and not pd.isna(vt_season.iloc[-1]["velo_change"]) else None)


        rows.append({
            "pitcher_name": r["Pitcher"],
            "season_max": season_max,
            "season_max_date": season_max_date,
            "season_avg": season_avg,
            "last_velo": last_velo,
            "last_date": last_date,
            "versus": versus,
            "trend": trend,
        })

    df = pd.DataFrame(rows, columns=cols)
    return df.sort_values(
        "season_max", ascending=False, na_position="last", kind="mergesort"
    ).reset_index(drop=True)
