"""Catcher pitch-level data access on CAPS GAMES (replaces catching.py's
warehouse reads for the QUERY layer only). Transforms are imported from
`app.data.catching` UNCHANGED -- they consume snake_case fact-style columns,
so `_CATCHER_SELECT` aliases GAMES's CamelCase columns to those exact names.

Catcher identity = RAW `GAMES.CatcherId` (== a player's trackman_id), unlike
the warehouse's surrogate catcher_id. LMU catchers: rows where
PitcherTeam='LOY_LIO' (the catcher is on the pitching team -- same rule as
the oracle). `app.data.catching` remains the parity oracle (see
tests/test_catching_caps.py) until Phase 3 removes its warehouse queries.
"""
from __future__ import annotations

import pandas as pd

from app.data import pitching_caps
from app.data.pitching_caps import _NUMERIC_GAME_ID_CLAUSE
from app.data.cache import cached
from app.db import query_df

LMU_TEAM_ID = 78  # GAMES.HomeTeamForeignID/AwayTeamForeignID for LMU.
LMU_PITCHER_TEAM = "LOY_LIO"  # GAMES.PitcherTeam code for LMU (catcher is on the pitching team).

# GAMES CamelCase -> the exact snake_case names app.data.catching's transforms
# read, so those transforms run unchanged over a GAMES-sourced frame.
# `catcher_id` carries the RAW id -- the transforms only ever read it, never
# map it. `game_date` (aliased from Date) is read by caught_stealing_trend.
_CATCHER_SELECT = """
    PlateLocSide AS plate_loc_side, PlateLocHeight AS plate_loc_height,
    TaggedPitchType AS tagged_pitch_type, PitchCall AS pitch_call,
    BatterSide AS batter_side, PitcherThrows AS pitcher_throws,
    PlayResult AS play_result, PopTime AS pop_time, ExchangeTime AS exchange_time,
    ThrowSpeed AS throw_speed, CatcherId AS catcher_id, GameID AS game_id,
    Date AS game_date, Inning AS inning, Pitcher AS pitcher_name
"""


def _in_clause(ids) -> tuple[str, dict]:
    """Build a parameterized `IN (...)` fragment + params dict for a list of ids."""
    ph = ", ".join(f":id{i}" for i in range(len(ids)))
    return ph, {f"id{i}": int(v) for i, v in enumerate(ids)}


@cached
def _sibling_catcher_ids(catcher_id) -> list[int]:
    """All LMU GAMES.CatcherId values sharing this id's Catcher name."""
    name = query_df(
        "SELECT Catcher FROM GAMES WHERE CatcherId = :c AND PitcherTeam = :t LIMIT 1",
        {"c": int(catcher_id), "t": LMU_PITCHER_TEAM},
    )
    if name.empty:
        return [int(catcher_id)]
    ids = query_df(
        "SELECT DISTINCT CatcherId FROM GAMES WHERE Catcher = :n AND PitcherTeam = :t "
        "AND CatcherId IS NOT NULL",
        {"n": str(name.iloc[0]["Catcher"]), "t": LMU_PITCHER_TEAM},
    )
    return [int(x) for x in ids["CatcherId"]] or [int(catcher_id)]


@cached
def game_pitches_for(game_id, catcher_id) -> pd.DataFrame:
    """A catcher's pitches in a game, unioning split Trackman ids (sibling union)."""
    ph, idp = _in_clause(_sibling_catcher_ids(catcher_id))
    # GameID is an opaque TEXT key (numeric surrogate for warehouse-backfilled
    # games, composite string like "20250517-704EddieDField-1" for legacy/cron
    # games), so it is passed through as a string -- never int()'d.
    idp["g"] = str(game_id)
    return query_df(
        f"SELECT {_CATCHER_SELECT} FROM GAMES WHERE GameID = :g AND CatcherId IN ({ph}) "
        f"ORDER BY PitchNo",
        idp,
    )


@cached
def range_pitches_for(catcher_id, start, end) -> pd.DataFrame:
    """All of a catcher's pitches across in-range games (sibling-id union).

    Guarded by `_NUMERIC_GAME_ID_CLAUSE` so a custom pre-2025 range can't pull
    in pre-CAPS-migration composite-GameID scrimmage rows, mirroring
    pitching_caps.range_pitches_for.
    """
    ph, idp = _in_clause(_sibling_catcher_ids(catcher_id))
    idp["start"] = str(start)
    idp["end"] = str(end)
    return query_df(
        f"SELECT {_CATCHER_SELECT} FROM GAMES WHERE CatcherId IN ({ph}) "
        f"AND Date BETWEEN :start AND :end AND {_NUMERIC_GAME_ID_CLAUSE} "
        f"ORDER BY GameID, PitchNo",
        idp,
    )


def game_pitches_season(catcher_id) -> pd.DataFrame:
    """All season pitches for a catcher (sibling-id union), numeric-GameID guarded."""
    ph, idp = _in_clause(_sibling_catcher_ids(catcher_id))
    return query_df(
        f"SELECT {_CATCHER_SELECT} FROM GAMES WHERE CatcherId IN ({ph}) "
        f"AND {_NUMERIC_GAME_ID_CLAUSE} ORDER BY GameID, PitchNo",
        idp,
    )


def game_context(game_id) -> dict:
    """Reuse pitching_caps's game context (already on GAMES)."""
    return pitching_caps.game_context(game_id)


# ======================= IDENTITY + ROSTER ==================================
#
# Catcher identity here is RAW GAMES.CatcherId (== a player's trackman_id),
# unlike catching.py's warehouse surrogate catcher_id. GAMES.Catcher is
# verified live as "Last, First" (e.g. "Lyall, Jake") -- the SAME format
# catching.catcher_name already builds from tm_player, so (unlike the
# pitching slice's First/Last reorder) catcher_name here reads GAMES.Catcher
# as-is, with no reformatting.

@cached
def lmu_catchers(season=None, start=None, end=None) -> pd.DataFrame:
    """One row per LMU catcher (name deduped; canonical id = most-tracked id),
    scoped to the given academic-year season (default = current_season()).

    Season date-bounds (not a numeric-GameID filter, and no ~12-month recent
    window) do the scoping now, so legacy composite-GameID seasons are listable
    too -- picking a PAST season from the dropdown surfaces that season's
    catchers, whose games are ALL composite-GameID and were previously hidden.
    The COUNT(*) DESC dedup tiebreak is computed over the season's rows only.
    Mirrors hitting_caps.lmu_hitters(season) exactly.

    When both `start` and `end` are given, they replace the season's date
    bounds (the coach's date-range dropdown nests inside the season, so this
    narrows the roster to catchers with data in that window).
    """
    from app.data import seasons
    s, e = seasons.season_bounds(season or seasons.current_season())
    if start is not None and end is not None:
        s, e = str(start), str(end)
    df = query_df(
        f"""
        SELECT CatcherId, Catcher FROM (
          SELECT CatcherId, Catcher,
                 ROW_NUMBER() OVER (PARTITION BY Catcher
                                    ORDER BY COUNT(*) DESC, CatcherId) AS rn
            FROM GAMES
           WHERE PitcherTeam = :team AND CatcherId IS NOT NULL
             AND Date BETWEEN :s AND :e
           GROUP BY CatcherId, Catcher
        ) t WHERE rn = 1 ORDER BY Catcher
        """,
        {"team": LMU_PITCHER_TEAM, "s": s, "e": e},
    )
    if not df.empty:
        df["CatcherId"] = df["CatcherId"].astype(int)
    return df


def catcher_name(catcher_id) -> str:
    """"Last, First" straight from GAMES.Catcher -- matches
    catching.catcher_name's format exactly (also "Last, First", built from
    tm_player there), so no reordering is needed (unlike pitcher_name)."""
    df = query_df(
        "SELECT Catcher FROM GAMES WHERE CatcherId = :c LIMIT 1",
        {"c": int(catcher_id)},
    )
    if df.empty:
        return str(catcher_id)
    return str(df.iloc[0]["Catcher"])


def catcher_tm_id_for(catcher_id):
    """Identity: GAMES.CatcherId already IS the raw trackman id. Kept for API
    compat with the report/dashboard/video's role-gating code."""
    return int(catcher_id)


@cached
def catcher_profile(catcher_id) -> dict:
    """Name + position 'C' + jersey/photo (roster_media, by raw id directly --
    no catcher_tm_id_for mapping needed, unlike the oracle)."""
    from app.data import roster_media
    name = catcher_name(catcher_id)
    media = roster_media.player_media(int(catcher_id))
    return {"name": name, "class_year": "", "position": "C",
            "throws": "", "jersey": media.get("jersey", ""),
            "photo": media.get("photo_url", "")}


@cached
def games_for_catcher(catcher_id, start=None, end=None) -> pd.DataFrame:
    """A catcher's games, newest first. GameLabel = 'YYYY-MM-DD vs/@ OPP'.
    Optional start/end (inclusive) bound game_date. Sibling-id union, matching
    catching.games_for_catcher's shape/format exactly.

    GameID is treated as an OPAQUE STRING (no numeric-only guard, no int cast),
    so legacy composite-GameID games (and future cron-loaded ones) appear too.
    Scoping is by Date only; sort is by Date desc with a GameID-string desc
    tiebreak for same-date doubleheaders (deterministic). Mirrors
    hitting_caps.games_for_batter.
    """
    ph, idp = _in_clause(_sibling_catcher_ids(catcher_id))
    date_clause = ""
    if start is not None and end is not None:
        date_clause = " AND Date BETWEEN :start AND :end"
        idp["start"] = str(start)
        idp["end"] = str(end)
    df = query_df(
        f"""
        SELECT DISTINCT GameID AS game_id, Date AS game_date,
               HomeTeam AS home_team, AwayTeam AS away_team,
               HomeTeamForeignID AS home_team_id
          FROM GAMES
         WHERE CatcherId IN ({ph}){date_clause}
        """,
        idp,
    )
    if df.empty:
        return pd.DataFrame(columns=["game_id", "game_date", "GameLabel"])
    df["game_id"] = df["game_id"].astype(str)
    df = df.sort_values(["game_date", "game_id"], ascending=[False, False]).reset_index(drop=True)
    lmu_home = df["home_team_id"] == LMU_TEAM_ID
    opp = df["away_team"].where(lmu_home, df["home_team"])
    loc = pd.Series("vs", index=df.index).where(lmu_home, "@")
    df["GameLabel"] = (df["game_date"].astype(str) + " " + loc + " " + opp.fillna("?"))
    return df[["game_id", "game_date", "GameLabel"]].reset_index(drop=True)


# ============================ SEASON TILES ===================================

def _rollup_over(catcher_id, start, end) -> dict:
    """The catching framing rollup (games, pitches, net strikes, steal%) for one
    catcher over an arbitrary [start, end] date window, as a single SQL
    aggregate over GAMES (sibling-id union). Single source of truth for the
    framing-tile math: `_compute_season_rollup` calls this with a season's
    bounds; `framing_season_tiles`'s range path calls it with the caller's
    date-range bounds directly -- same function, different window."""
    from app.data.catching import _pct
    cid = int(catcher_id)
    ph, idp = _in_clause(_sibling_catcher_ids(cid))
    idp["s"] = start; idp["e"] = end
    df = query_df(
        f"""
        SELECT COUNT(DISTINCT GameID) AS games,
               COUNT(*) AS pitches,
               SUM(PitchCall='StrikeCalled'
                   AND NOT (ABS(PlateLocSide*12) <= 10
                            AND ABS(PlateLocHeight*12 - 30) <= 13)) AS stolen,
               SUM(PitchCall='BallCalled'
                   AND (ABS(PlateLocSide*12) <= 10
                        AND ABS(PlateLocHeight*12 - 30) <= 13)) AS lost,
               SUM(PlateLocSide IS NOT NULL
                   AND PlateLocHeight IS NOT NULL) AS valid_loc
          FROM GAMES
         WHERE CatcherId IN ({ph}) AND Date BETWEEN :s AND :e
        """,
        idp,
    )
    tiles = {"games": "—", "pitches": "—", "net_strikes": "—", "steal_pct": "—"}
    if not df.empty:
        r = df.iloc[0]
        stolen = int(r["stolen"] or 0)
        lost = int(r["lost"] or 0)
        valid_loc = int(r["valid_loc"] or 0)
        steal = _pct(lost, valid_loc)
        tiles = {
            "games": str(int(r["games"] or 0)),
            "pitches": str(int(r["pitches"] or 0)),
            "net_strikes": str(stolen - lost),
            "steal_pct": "—" if steal is None else f"{steal}%",
        }
    return {"catcher_id": cid, "catcher_name": catcher_name(cid), **tiles}


def _compute_season_rollup(catcher_id, season=None) -> dict:
    """Catching season rollup: the framing sidebar tiles (games, pitches, net
    strikes, steal%) plus catcher_id/name. Thin wrapper over `_rollup_over`
    with the season's date bounds -- the single source of truth for the tile
    math lives there now. This is the rebuild source AND the compute fallback
    for framing_season_tiles.

    Scoped to the academic-year `season` (default current_season()) via
    Date-bounds -- which for the current season equals the old numeric-GameID
    guard (that season is the numeric-backfilled one) but also lets a PAST
    season's composite-GameID rows aggregate when the Season dropdown selects
    it."""
    from app.data import seasons
    season = season or seasons.current_season()
    s, e = seasons.season_bounds(season)
    return {**_rollup_over(catcher_id, s, e), "season_label": season}


def framing_season_tiles(catcher_id, season=None, start=None, end=None) -> dict:
    """Season sidebar tiles, scoped to a date range.

    When `start`/`end` are omitted, or given but equal to `season`'s bounds
    (the default "This Season" view), read the 1-row precalc catching rollup
    with a compute fallback -- this fast path is unchanged (the precalc table
    holds one row per (catcher, season), so ANY season is a ~0.2s single-row
    read). A genuine sub-range (the coach narrowed the calendar/preset)
    computes on the fly via `_rollup_over` so the sidebar tiles track the
    selected date range. Return shape unchanged."""
    from app.data import seasons, precalc  # lazy: precalc imports catching_caps
    season = season or seasons.current_season()
    if start and end:
        s_b, e_b = seasons.season_bounds(season)
        if str(start) != s_b or str(end) != e_b:
            r = _rollup_over(catcher_id, start, end)
            return {k: r[k] for k in ("games", "pitches", "net_strikes", "steal_pct")}
    row = precalc.read_catching_season(int(catcher_id), season)
    r = row if row is not None else _compute_season_rollup(catcher_id, season)
    return {k: r[k] for k in ("games", "pitches", "net_strikes", "steal_pct")}
