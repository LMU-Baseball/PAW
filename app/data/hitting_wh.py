"""Warehouse hitting data layer.

Queries the modern Trackman warehouse (fact_tm_game_pitch / dim_tm_game / tm_team)
and returns DataFrames whose columns are aliased to the LEGACY names the transforms
in app/data/hitting.py expect, so those transforms are reused unchanged. Adds a
computed attack `Zone` and NaN `QC`/`PathQ`/`Angle` (columns the warehouse lacks).
Canonical id = batter_tm_id (== a player's current_user.trackman_id). LMU = team 78.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.db import query_df
from app.data.hitting import _add_pitch_category, qab_frame

LMU_TEAM_ID = 78
LMU_BATTER_TEAM = "LOY_LIO"

# fact -> legacy alias list, shared by game + season loaders.
_PITCH_SELECT = """
    plate_loc_side AS PlateLocSide, plate_loc_height AS PlateLocHeight,
    pitch_call AS PitchCall, play_result AS PlayResult, korbb AS KorBB,
    tagged_hit_type AS TaggedHitType, tagged_pitch_type AS TaggedPitchType,
    exit_speed AS ExitSpeed, distance AS Distance, bearing AS Bearing,
    hang_time AS HangTime, inning AS Inning, pa_of_inning AS PAofInning,
    pitch_of_pa AS PitchofPA, pitch_no AS PitchNo, balls AS Balls,
    strikes AS Strikes, runs_scored AS RunsScored, outs_on_play AS OutsOnPlay,
    batter_side AS BatterSide, pitcher_name AS Pitcher, game_id AS GameID
"""


def attack_zone(side_ft, height_ft) -> str:
    """Heart/Shadow/Chase/Waste from plate coords (inches; zone-box boundaries)."""
    if side_ft is None or height_ft is None or pd.isna(side_ft) or pd.isna(height_ft):
        return "Waste"
    x = abs(float(side_ft) * 12)
    y = abs(float(height_ft) * 12 - 30)
    if x <= 7.25 and y <= 8.75:
        return "Heart"
    if x <= 13.5 and y <= 15.125:
        return "Shadow"
    if x <= 20.5 and y <= 25.5:
        return "Chase"
    return "Waste"


def _finish(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["Zone"] = [attack_zone(s, h)
                  for s, h in zip(df["PlateLocSide"], df["PlateLocHeight"])]
    for c in ("QC", "PathQ", "Angle"):
        df[c] = np.nan
    return _add_pitch_category(df)


def wh_lmu_hitters() -> pd.DataFrame:
    return query_df(
        """
        SELECT DISTINCT batter_name AS Batter, batter_tm_id AS BatterId
          FROM fact_tm_game_pitch
         WHERE batter_team = :team AND batter_tm_id IS NOT NULL
         ORDER BY batter_name
        """,
        {"team": LMU_BATTER_TEAM},
    )


def wh_games_for_batter(batter_tm_id) -> pd.DataFrame:
    df = query_df(
        """
        SELECT g.game_id, g.game_date, g.home_team_id,
               CASE WHEN g.home_team_id = :lmu THEN 'vs' ELSE '@' END AS loc,
               t.team_name AS opp
          FROM (SELECT DISTINCT game_id FROM fact_tm_game_pitch
                 WHERE batter_tm_id = :b) bg
          JOIN dim_tm_game g ON g.game_id = bg.game_id
          JOIN tm_team t ON t.team_id = CASE WHEN g.home_team_id = :lmu
                                             THEN g.away_team_id ELSE g.home_team_id END
         ORDER BY g.game_date DESC
        """,
        {"b": int(batter_tm_id), "lmu": LMU_TEAM_ID},
    )
    if df.empty:
        return pd.DataFrame(columns=["game_id", "game_date", "GameLabel"])
    df["GameLabel"] = [f"{pd.to_datetime(d).strftime('%m/%d/%y')} {l} {o}"
                       for d, l, o in zip(df["game_date"], df["loc"], df["opp"])]
    return df[["game_id", "game_date", "GameLabel"]]


def wh_game_pitches(game_id, batter_tm_id) -> pd.DataFrame:
    df = query_df(
        f"""
        SELECT {_PITCH_SELECT}
          FROM fact_tm_game_pitch
         WHERE game_id = :g AND batter_tm_id = :b
         ORDER BY pitch_no
        """,
        {"g": int(game_id), "b": int(batter_tm_id)},
    )
    return _finish(df)


def wh_season_pitches(batter_tm_id) -> pd.DataFrame:
    df = query_df(
        f"""
        SELECT {_PITCH_SELECT}
          FROM fact_tm_game_pitch
         WHERE batter_tm_id = :b
         ORDER BY game_id, pitch_no
        """,
        {"b": int(batter_tm_id)},
    )
    return _finish(df)


def wh_season_qab_rate(batter_tm_id) -> float | None:
    df = wh_season_pitches(batter_tm_id)
    if df.empty:
        return None
    q = qab_frame(df)
    total = len(q)
    return round(q["QAB"].sum() / total, 3) if total else None


def _roster_lookup(name_last_first: str) -> tuple[str, str]:
    """Best-effort class_year/position from roster_players (name is 'First Last')."""
    if "," not in name_last_first:
        return "", ""
    last, first = (p.strip() for p in name_last_first.split(",", 1))
    df = query_df(
        """
        SELECT class_year, position FROM roster_players
         WHERE season LIKE '2025%' AND player_name = :n LIMIT 1
        """,
        {"n": f"{first} {last}"},
    )
    if df.empty:
        return "", ""
    r = df.iloc[0]
    cy = "" if pd.isna(r["class_year"]) else str(r["class_year"])
    pos = "" if pd.isna(r["position"]) else str(r["position"])
    return cy, pos


def wh_player_profile(batter_tm_id) -> dict:
    blank = {"name": "", "bats": "", "class_year": "", "position": "",
             "photo": "", "jersey": ""}
    df = query_df(
        """
        SELECT batter_name, batter_side FROM fact_tm_game_pitch
         WHERE batter_tm_id = :b ORDER BY game_id DESC LIMIT 1
        """,
        {"b": int(batter_tm_id)},
    )
    if df.empty:
        return blank
    name = "" if pd.isna(df.iloc[0]["batter_name"]) else str(df.iloc[0]["batter_name"])
    bats = "" if pd.isna(df.iloc[0]["batter_side"]) else str(df.iloc[0]["batter_side"])
    cy, pos = _roster_lookup(name)
    return {"name": name, "bats": bats, "class_year": cy, "position": pos,
            "photo": "", "jersey": ""}


def wh_scoreboard(game_id) -> dict:
    df = query_df(
        """
        SELECT g.game_date, g.game_type, g.home_team_id, t.team_name AS opp
          FROM dim_tm_game g
          JOIN tm_team t ON t.team_id = CASE WHEN g.home_team_id = :lmu
                                             THEN g.away_team_id ELSE g.home_team_id END
         WHERE g.game_id = :g
        """,
        {"g": int(game_id), "lmu": LMU_TEAM_ID},
    )
    if df.empty:
        return {"date": "", "loc": "", "opp": "", "game_type": ""}
    r = df.iloc[0]
    return {"date": pd.to_datetime(r["game_date"]).strftime("%m/%d/%y"),
            "loc": "vs" if r["home_team_id"] == LMU_TEAM_ID else "@",
            "opp": "" if pd.isna(r["opp"]) else str(r["opp"]),
            "game_type": "" if pd.isna(r["game_type"]) else str(r["game_type"])}
