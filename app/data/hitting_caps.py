"""Hitting data layer on CAPS GAMES (replaces hitting_wh's warehouse reads).

GAMES stores columns under the legacy names the app/data/hitting.py transforms
expect, so no aliasing is needed -- SELECT the columns and hand to _finish.
"""
from __future__ import annotations
import pandas as pd
from app.db import query_df
from app.data.hitting_wh import _finish, _in_clause, _roster_lookup   # pure/param helpers, reused
from app.data.hitting import qab_frame
from app.data.roster_media import player_media

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


def games_for_batter(batter_id, start=None, end=None):
    ph, idp = _in_clause(_sibling_ids(batter_id))
    date_clause = ""
    if start is not None and end is not None:
        date_clause = " AND Date BETWEEN :start AND :end"; idp["start"]=str(start); idp["end"]=str(end)
    df = query_df(
        f"SELECT DISTINCT GameID AS game_id, Date AS game_date, HomeTeam, AwayTeam, "
        f"HomeTeamForeignID FROM GAMES WHERE BatterId IN ({ph}){date_clause}", idp)
    if df.empty:
        return pd.DataFrame(columns=["game_id", "game_date", "GameLabel"])
    df["game_id"] = df["game_id"].astype(int)
    # GameID is stored as text, so sort numerically in pandas rather than via SQL
    # ORDER BY (which would sort lexicographically). Same-date ties (doubleheaders)
    # break by game_id DESC: a deliberate, deterministic tiebreak -- the warehouse
    # oracle (wh_games_for_batter) has no secondary ORDER BY at all, so its
    # same-date order is DB-planner incidental/non-deterministic, not a contract
    # we should copy.
    df = df.sort_values(["game_date", "game_id"], ascending=[False, False]).reset_index(drop=True)
    lmu_home = df["HomeTeamForeignID"] == LMU_TEAM_ID
    df["loc"] = lmu_home.map({True: "vs", False: "@"})
    df["opp"] = df["AwayTeam"].where(lmu_home, df["HomeTeam"])
    df["GameLabel"] = [f"{pd.to_datetime(d).strftime('%m/%d/%y')} {l} {o}"
                       for d, l, o in zip(df["game_date"], df["loc"], df["opp"])]
    return df[["game_id", "game_date", "GameLabel"]]


def scoreboard(game_id):
    df = query_df(
        "SELECT Date, HomeTeam, AwayTeam, HomeTeamForeignID, GameType "
        "FROM GAMES WHERE GameID = :g LIMIT 1", {"g": int(game_id)})
    if df.empty:
        return {"date": "", "loc": "", "opp": "", "game_type": ""}
    r = df.iloc[0]
    lmu_home = r["HomeTeamForeignID"] == LMU_TEAM_ID
    opp = r["AwayTeam"] if lmu_home else r["HomeTeam"]
    return {"date": pd.to_datetime(r["Date"]).strftime("%m/%d/%y"),
            "loc": "vs" if lmu_home else "@",
            "opp": "" if pd.isna(opp) else str(opp),
            "game_type": "" if pd.isna(r["GameType"]) else str(r["GameType"])}


def player_profile(batter_id):
    blank = {"name": "", "bats": "", "class_year": "", "position": "",
             "photo": "", "jersey": ""}
    df = query_df(
        "SELECT Batter, BatterSide FROM GAMES WHERE BatterId = :b "
        "ORDER BY Date DESC LIMIT 1", {"b": int(batter_id)})
    if df.empty:
        return blank
    name = "" if pd.isna(df.iloc[0]["Batter"]) else str(df.iloc[0]["Batter"])
    bats = "" if pd.isna(df.iloc[0]["BatterSide"]) else str(df.iloc[0]["BatterSide"])
    cy, pos = _roster_lookup(name)
    media = player_media(int(batter_id))  # scraped headshot + jersey (blanks if none)
    return {"name": name, "bats": bats, "class_year": cy, "position": pos,
            "photo": media["photo_url"], "jersey": media["jersey"]}
