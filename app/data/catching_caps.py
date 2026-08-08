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
    idp["g"] = int(game_id)
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
def lmu_catchers() -> pd.DataFrame:
    """One row per LMU catcher (name deduped; canonical id = most-tracked id
    within the window), scoped to the same ~12-month recent-data window
    pitching_caps.lmu_pitchers uses (shared clause: GAMES/PitcherTeam is the
    same table/column for both slices, so the window is identical).

    Mirrors catching.wh_lmu_catchers's dedup logic, but over GAMES/CatcherId
    instead of fact_tm_game_pitch/catcher_id -- windowed for the same reason:
    GAMES holds full CAPS history back to 2022, so an unscoped version would
    surface retired alumni the warehouse (current-season-only) never has.

    Also guarded by `_NUMERIC_GAME_ID_CLAUSE`: a catcher can have in-window
    rows that are ALL legacy composite-GameID (pre-CAPS-migration) games --
    such a "ghost" would be listed here but every numeric-GameID-guarded data
    function (games_for_catcher, framing_season_tiles) returns empty for
    them, producing a blank dashboard (confirmed live for CatcherId 801901,
    "Ayers, Robbie"). Restricting to numeric-GameID rows keeps the dropdown
    consistent with what the data functions can actually show.
    """
    df = query_df(
        f"""
        SELECT CatcherId, Catcher FROM (
          SELECT CatcherId, Catcher,
                 ROW_NUMBER() OVER (PARTITION BY Catcher
                                    ORDER BY COUNT(*) DESC, CatcherId) AS rn
            FROM GAMES
           WHERE PitcherTeam = :team AND CatcherId IS NOT NULL
             AND {pitching_caps._RECENT_WINDOW_CLAUSE}
             AND {_NUMERIC_GAME_ID_CLAUSE}
           GROUP BY CatcherId, Catcher
        ) t WHERE rn = 1 ORDER BY Catcher
        """,
        {"team": LMU_PITCHER_TEAM},
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

    Restricted to numeric GameIDs (see `_NUMERIC_GAME_ID_CLAUSE`): GAMES also
    holds pre-CAPS-migration scrimmage rows under composite string GameIDs
    that predate the warehouse's synced season -- excluding them reproduces
    the oracle's season boundary exactly and guards the int-cast below from a
    legacy string GameID (mirroring pitching_caps.games_for_pitcher).
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
         WHERE CatcherId IN ({ph}) AND {_NUMERIC_GAME_ID_CLAUSE}{date_clause}
        """,
        idp,
    )
    if df.empty:
        return pd.DataFrame(columns=["game_id", "game_date", "GameLabel"])
    df["game_id"] = df["game_id"].astype(int)
    df = df.sort_values(["game_date", "game_id"], ascending=[False, False]).reset_index(drop=True)
    lmu_home = df["home_team_id"] == LMU_TEAM_ID
    opp = df["away_team"].where(lmu_home, df["home_team"])
    loc = pd.Series("vs", index=df.index).where(lmu_home, "@")
    df["GameLabel"] = (df["game_date"].astype(str) + " " + loc + " " + opp.fillna("?"))
    return df[["game_id", "game_date", "GameLabel"]].reset_index(drop=True)


# ============================ SEASON TILES ===================================

def _compute_season_rollup(catcher_id) -> dict:
    """Phase 4 catching season rollup: the framing sidebar tiles (games,
    pitches, net strikes, steal%) as an SQL aggregate over GAMES (sibling-id
    union, numeric-GameID-guarded), plus catcher_id/name. Mirrors catching's
    warehouse version exactly (same keys/format/InZone box). This is the rebuild
    source AND the compute fallback for framing_season_tiles."""
    from app.data.catching import _pct
    cid = int(catcher_id)
    ph, idp = _in_clause(_sibling_catcher_ids(cid))
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
         WHERE CatcherId IN ({ph}) AND {_NUMERIC_GAME_ID_CLAUSE}
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


def framing_season_tiles(catcher_id) -> dict:
    """Season sidebar tiles, read from the 1-row precalc catching rollup with a
    compute fallback (Phase 4). Return shape unchanged."""
    from app.data import precalc  # lazy: precalc imports catching_caps for rebuild
    row = precalc.read_catching_season(int(catcher_id))
    r = row if row is not None else _compute_season_rollup(catcher_id)
    return {k: r[k] for k in ("games", "pitches", "net_strikes", "steal_pct")}
