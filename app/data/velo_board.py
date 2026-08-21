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
OVERRIDES_TABLE = "velo_board_overrides"

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


_OVERRIDES_DDL = f"""
    CREATE TABLE IF NOT EXISTS {OVERRIDES_TABLE} (
        pitcher_id    BIGINT NOT NULL,
        season_label  VARCHAR(16) NOT NULL,
        season_max    FLOAT,
        season_avg    FLOAT,
        updated_by    INT,
        updated_at    DATETIME,
        PRIMARY KEY (pitcher_id, season_label)
    )"""


def ensure_tables(engine=None) -> None:
    """Idempotently create velo_board_entries + velo_board_overrides."""
    engine = engine or get_engine()
    with engine.begin() as conn:
        conn.execute(text(_DDL))
        conn.execute(text(_OVERRIDES_DDL))


def read_overrides(season_label) -> pd.DataFrame:
    """Coach velo corrections for a season (season_max/season_avg overrides)."""
    ensure_tables()
    return query_df(
        f"SELECT * FROM {OVERRIDES_TABLE} WHERE season_label = :s",
        {"s": season_label})


def set_override(pitcher_id, season_label, season_max=None, season_avg=None,
                 updated_by=None) -> None:
    """Upsert a coach velo correction for (pitcher, season). A field left None
    means 'no override for that field' -- board_rows keeps the computed value."""
    ensure_tables()
    sql = text(f"""
        INSERT INTO {OVERRIDES_TABLE}
            (pitcher_id, season_label, season_max, season_avg, updated_by, updated_at)
        VALUES (:pitcher_id, :season_label, :season_max, :season_avg, :updated_by, :updated_at)
        ON DUPLICATE KEY UPDATE season_max = VALUES(season_max),
            season_avg = VALUES(season_avg), updated_by = VALUES(updated_by),
            updated_at = VALUES(updated_at)
    """)
    with get_engine().begin() as conn:
        conn.execute(sql, {
            "pitcher_id": int(pitcher_id),
            "season_label": season_label,
            "season_max": _clean(season_max),
            "season_avg": _clean(season_avg),
            "updated_by": _clean(updated_by),
            "updated_at": _now(),
        })


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


def default_week_for(season_label) -> str:
    """The most-recent sensible week inside `season_label`: today's week if the
    season is still in progress (today falls within its bounds), else the
    season's final week (today is past a completed season's end, or -- edge
    case -- before its start).

    Shared by the velo board and the Cauldron: both open on this week, and both
    snap the week picker to it when the Season selector changes, so the two
    controls can't drift into a week that isn't in the selected season."""
    start, end = season_bounds(season_label)
    today = date.today().isoformat()
    anchor = min(today, end)
    if anchor < start:
        anchor = start
    return week_start_for(anchor)


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


_VELO_OUTLIER_MARGIN = 8.0   # mph above a pitcher's own median = a bad reading
_VELO_OUTLIER_MIN_N = 5      # need this many readings to trust the median


def _clip_velo_outliers(df, col="rel_speed"):
    """Drop implausible Fastball/Sinker readings for ONE pitcher: any RelSpeed
    more than `_VELO_OUTLIER_MARGIN` mph above that pitcher's OWN median velo.
    Catches sensor/calibration glitches (e.g. a bullpen 99.98 for a pitcher who
    otherwise tops out ~93) without penalizing a genuinely hard thrower -- their
    median is high too, so their real velos stay under the ceiling. Skipped when
    there are too few readings to trust the median (a sparse sample might be all
    legitimate)."""
    if df is None or df.empty or col not in df.columns:
        return df
    vals = df[col].dropna()
    if len(vals) < _VELO_OUTLIER_MIN_N:
        return df
    ceiling = float(vals.median()) + _VELO_OUTLIER_MARGIN
    return df[df[col] <= ceiling]


def _leaderboard_per_pitcher(season_label) -> pd.DataFrame:
    """Reference (per-pitcher) leaderboard implementation, kept as the parity
    oracle `_leaderboard_batched` is verified against (scratchpad/
    parity_leaderboard.py). NOT the hot path -- `leaderboard` calls the batched
    version. One row per rostered pitcher (`pitching_caps.lmu_pitchers`), sorted
    by `season_max` descending (None/NaN last):

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

        season_rows = _clip_velo_outliers(_velo_rows(pid, start=s, end=e))
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


_LEADERBOARD_COLS = ["pitcher_name", "season_max", "season_max_date", "season_avg",
                     "last_velo", "last_date", "versus", "trend"]


def _leaderboard_batched(season_label) -> pd.DataFrame:
    """BATCHED equivalent of `leaderboard`: identical output, but reads all
    rostered pitchers' Fastball/Sinker velo in TWO queries (one GAMES pull over
    the season window, one all-history BULLPEN pull) instead of ~5 round-trips
    per pitcher. All per-pitcher aggregation happens in pandas.

    Parity note -- everything `leaderboard` needs is season-bounded, so a single
    season-window GAMES pull suffices: season_max/avg/max_date are over the
    season's pitches; the last in-season GAME appearance (avg velo, date,
    opponent-from-HomeTeamForeignID) comes from those same rows; and the trend
    diff is season-label-partitioned, and a given academic year's two derived
    labels (Fall YYYY / Spring YYYY+1) both fall entirely inside the season
    bounds -- so the diff computed over just the window equals the full-history
    diff `velo_trend` would produce. BULLPEN is pulled unbounded because the
    no-game fallback (`_last_bullpen_velo`) uses the most recent session ever;
    it's date-filtered in pandas for the season pool."""
    from app.data import pitching_caps as PC

    roster = PC.lmu_pitchers(season_label)
    if roster.empty:
        return pd.DataFrame(columns=_LEADERBOARD_COLS)
    s, e = season_bounds(season_label)
    s_str, e_str = str(s), str(e)

    # sibling_id -> canonical (rostered) pitcher_id, over every rostered pitcher.
    sib_to_canon: dict[int, int] = {}
    canon: list[tuple[int, str]] = []
    for _, r in roster.iterrows():
        pid = int(r["PitcherId"])
        canon.append((pid, r["Pitcher"]))
        for sid in PC._sibling_pitcher_ids(pid):
            sib_to_canon[int(sid)] = pid
    all_sibs = sorted(sib_to_canon)
    if not all_sibs:
        return pd.DataFrame(columns=_LEADERBOARD_COLS)

    ph, base = PC._in_clause(all_sibs)
    gp = dict(base, s=s_str, e=e_str)
    games = query_df(
        f"SELECT PitcherId AS pid, RelSpeed AS rel_speed, Date AS dt, GameID AS gid, "
        f"HomeTeam AS home_team, AwayTeam AS away_team, HomeTeamForeignID AS home_fid "
        f"FROM GAMES WHERE PitcherId IN ({ph}) "
        f"AND TaggedPitchType IN ({_VELO_PITCH_TYPES}) AND Date BETWEEN :s AND :e", gp)
    bull = query_df(
        f"SELECT PitcherId AS pid, RelSpeed AS rel_speed, DATE(Date) AS dt "
        f"FROM BULLPEN WHERE PitcherId IN ({ph}) "
        f"AND TaggedPitchType IN ({_VELO_PITCH_TYPES})", base)

    if not games.empty:
        games = games.copy()
        games["canon"] = games["pid"].astype(int).map(sib_to_canon)
        games["dt"] = games["dt"].astype(str)
    if not bull.empty:
        bull = bull.copy()
        bull["canon"] = bull["pid"].astype(int).map(sib_to_canon)
        bull["dt"] = bull["dt"].astype(str)

    empty_pool = pd.DataFrame(columns=["rel_speed", "dt"])
    rows = []
    for pid, name in canon:
        g = games[games["canon"] == pid] if not games.empty else games
        b_all = bull[bull["canon"] == pid] if not bull.empty else bull
        b_season = (b_all[(b_all["dt"] >= s_str) & (b_all["dt"] <= e_str)]
                    if not b_all.empty else b_all)

        # Season velo pool: every Fastball/Sinker pitch (games + season bullpen),
        # games first so idxmax ties break to a game exactly like `_velo_rows`.
        pool = pd.concat([
            g[["rel_speed", "dt"]] if not g.empty else empty_pool,
            b_season[["rel_speed", "dt"]] if not b_season.empty else empty_pool,
        ], ignore_index=True).dropna(subset=["rel_speed"]).reset_index(drop=True)
        pool = _clip_velo_outliers(pool)   # drop calibration-glitch readings
        if pool.empty:
            season_max = season_avg = season_max_date = None
        else:
            season_max = float(pool["rel_speed"].max())
            season_avg = float(pool["rel_speed"].mean())
            season_max_date = str(pool.loc[pool["rel_speed"].idxmax(), "dt"])

        # Per-game (appearance) avg velo + opponent, from the same season games.
        if not g.empty:
            appr = g.groupby("gid").agg(
                avg_velo=("rel_speed", "mean"), game_date=("dt", "first"),
                home_team=("home_team", "first"), away_team=("away_team", "first"),
                home_fid=("home_fid", "first")).reset_index()
        else:
            appr = pd.DataFrame(columns=["gid", "avg_velo", "game_date",
                                         "home_team", "away_team", "home_fid"])

        if not appr.empty:
            appr = appr.sort_values("game_date", kind="mergesort").reset_index(drop=True)
            last = appr.iloc[-1]
            last_velo = float(last["avg_velo"])
            last_date = str(last["game_date"])
            fid = last["home_fid"]
            lmu_home = bool(pd.notna(fid) and int(fid) == PC.LMU_TEAM_ID)
            versus = last["away_team"] if lmu_home else last["home_team"]
            appr["slabel"] = appr["game_date"].apply(PC._season_label)
            vc = appr.groupby("slabel")["avg_velo"].diff().iloc[-1]
            trend = float(vc) if pd.notna(vc) else None
        else:
            # No in-season game -> most recent bullpen session (any date).
            bb = b_all.dropna(subset=["rel_speed", "dt"]) if not b_all.empty else b_all
            if bb is None or bb.empty:
                last_velo = last_date = None
            else:
                ld = bb["dt"].max()
                last_velo = float(bb.loc[bb["dt"] == ld, "rel_speed"].mean())
                last_date = str(ld)
            versus = None
            trend = None

        rows.append({
            "pitcher_name": name, "season_max": season_max,
            "season_max_date": season_max_date, "season_avg": season_avg,
            "last_velo": last_velo, "last_date": last_date,
            "versus": versus, "trend": trend,
        })

    df = pd.DataFrame(rows, columns=_LEADERBOARD_COLS)
    return df.sort_values(
        "season_max", ascending=False, na_position="last", kind="mergesort"
    ).reset_index(drop=True)


@cached
def leaderboard(season_label) -> pd.DataFrame:
    """One row per rostered pitcher, ranked by season-best Fastball/Sinker velo
    (see `_leaderboard_per_pitcher` for the full column contract). Reads via the
    BATCHED path (`_leaderboard_batched`) -- two queries total instead of ~5 per
    pitcher; verified byte-identical to the per-pitcher oracle."""
    return _leaderboard_batched(season_label)


_BOARD_COLS = ["pitcher_id", "pitcher_name", "season_max", "season_max_date",
               "season_avg", "last_velo", "last_date", "versus", "trend",
               "velo_goal", "assessment"]


def board_rows(season_label, week_start) -> pd.DataFrame:
    """One row per rostered pitcher for the UNIFIED velo table: the leaderboard
    columns -- with any coach season_max/season_avg override applied (and rows
    re-ranked by the effective season_max) -- plus this week's velo_goal /
    assessment. `pitcher_id` rides along (hidden) for save-mapping. Raw values
    (numeric velos, ISO dates, numeric trend); the view formats read-only cells.

    Overrides are applied HERE, not inside the @cached `leaderboard`, so a
    coach's correction shows immediately (this function isn't cached) without
    touching the leaderboard cache or its byte-parity oracle."""
    from app.data import pitching_caps  # lazy

    roster = pitching_caps.lmu_pitchers(season_label)
    if roster.empty:
        return pd.DataFrame(columns=_BOARD_COLS)

    lb = leaderboard(season_label)
    lb_by_name = {r["pitcher_name"]: r for _, r in lb.iterrows()} if not lb.empty else {}

    entries = read_entries(season_label, week_start)
    goal_by_id = (dict(zip(entries["pitcher_id"].astype(int), entries["velo_goal"]))
                  if not entries.empty else {})
    assess_by_id = (dict(zip(entries["pitcher_id"].astype(int), entries["assessment"]))
                    if not entries.empty else {})

    overrides = read_overrides(season_label)
    ovr_max = (dict(zip(overrides["pitcher_id"].astype(int), overrides["season_max"]))
               if not overrides.empty else {})
    ovr_avg = (dict(zip(overrides["pitcher_id"].astype(int), overrides["season_avg"]))
               if not overrides.empty else {})

    rows = []
    for _, r in roster.iterrows():
        pid = int(r["PitcherId"])
        name = r["Pitcher"]
        lbr = lb_by_name.get(name, {})

        def _lb(k):
            v = lbr.get(k) if hasattr(lbr, "get") else None
            return _clean(v)

        om, oa = _clean(ovr_max.get(pid)), _clean(ovr_avg.get(pid))
        rows.append({
            "pitcher_id": pid,
            "pitcher_name": name,
            "season_max": om if om is not None else _lb("season_max"),
            "season_max_date": _lb("season_max_date"),
            "season_avg": oa if oa is not None else _lb("season_avg"),
            "last_velo": _lb("last_velo"),
            "last_date": _lb("last_date"),
            "versus": _lb("versus"),
            "trend": _lb("trend"),
            "velo_goal": _clean(goal_by_id.get(pid)),
            "assessment": _clean(assess_by_id.get(pid)),
        })
    df = pd.DataFrame(rows, columns=_BOARD_COLS)
    return df.sort_values("season_max", ascending=False, na_position="last",
                          kind="mergesort").reset_index(drop=True)
