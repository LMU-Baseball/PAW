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
    Date AS game_date
"""


def _in_clause(ids) -> tuple[str, dict]:
    """Build a parameterized `IN (...)` fragment + params dict for a list of ids."""
    ph = ", ".join(f":id{i}" for i in range(len(ids)))
    return ph, {f"id{i}": int(v) for i, v in enumerate(ids)}


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


def game_pitches_for(game_id, catcher_id) -> pd.DataFrame:
    """A catcher's pitches in a game, unioning split Trackman ids (sibling union)."""
    ph, idp = _in_clause(_sibling_catcher_ids(catcher_id))
    idp["g"] = int(game_id)
    return query_df(
        f"SELECT {_CATCHER_SELECT} FROM GAMES WHERE GameID = :g AND CatcherId IN ({ph}) "
        f"ORDER BY PitchNo",
        idp,
    )


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
