"""Hitting data layer on CAPS GAMES (replaces hitting_wh's warehouse reads).

GAMES stores columns under the legacy names the app/data/hitting.py transforms
expect, so no aliasing is needed -- SELECT the columns and hand to _finish.
"""
from __future__ import annotations
from app.db import query_df
from app.data.hitting_wh import _finish, _in_clause   # pure/param helpers, reused
from app.data.hitting import qab_frame

LMU_BATTER_TEAM = "LOY_LIO"
LMU_TEAM_ID = 78

# GAMES columns the transforms consume (already correctly named).
_PITCH_COLS = (
    "PlateLocSide, PlateLocHeight, PitchCall, PlayResult, KorBB, TaggedHitType, "
    "TaggedPitchType, ExitSpeed, Distance, Bearing, HangTime, Inning, PAofInning, "
    "PitchofPA, PitchNo, Balls, Strikes, RunsScored, OutsOnPlay, BatterSide, "
    "Pitcher, GameID, Angle"
)

def _sibling_ids(batter_id):
    name = query_df(
        "SELECT Batter FROM GAMES WHERE BatterId = :b AND BatterTeam = :t LIMIT 1",
        {"b": int(batter_id), "t": LMU_BATTER_TEAM})
    if name.empty:
        return [int(batter_id)]
    ids = query_df(
        "SELECT DISTINCT BatterId FROM GAMES WHERE Batter = :n AND BatterTeam = :t "
        "AND BatterId IS NOT NULL",
        {"n": str(name.iloc[0]["Batter"]), "t": LMU_BATTER_TEAM})
    return [int(x) for x in ids["BatterId"]] or [int(batter_id)]

def game_pitches(game_id, batter_id):
    ph, idp = _in_clause(_sibling_ids(batter_id))
    df = query_df(
        f"SELECT {_PITCH_COLS} FROM GAMES WHERE GameID = :g AND BatterId IN ({ph}) "
        f"ORDER BY PitchNo", {"g": int(game_id), **idp})
    return _finish(df)

def season_pitches(batter_id):
    ph, idp = _in_clause(_sibling_ids(batter_id))
    df = query_df(
        f"SELECT {_PITCH_COLS} FROM GAMES WHERE BatterId IN ({ph}) "
        f"ORDER BY GameID, PitchNo", idp)
    return _finish(df)

def range_pitches(batter_id, start, end):
    ph, idp = _in_clause(_sibling_ids(batter_id))
    idp["start"] = str(start); idp["end"] = str(end)
    df = query_df(
        f"SELECT {_PITCH_COLS} FROM GAMES WHERE BatterId IN ({ph}) "
        f"AND Date BETWEEN :start AND :end ORDER BY GameID, PitchNo", idp)
    return _finish(df)
