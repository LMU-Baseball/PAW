"""Pitcher data access + transforms for the postgame report.

Reads the modern Trackman warehouse: fact_tm_game_pitch (pitch grain),
dim_tm_game (game context), tm_player (names), and pitcher views. Keys are
warehouse game_id (int) + pitcher_id (bigint). Percentages returned NUMERIC.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.db import query_df

LMU_TEAMS = ("LOY_LIO", "LMU")
PITCH_TYPE_COL = "tagged_pitch_type"


def pitch_type(df: pd.DataFrame) -> pd.Series:
    """Tagged pitch type, falling back to auto_pitch_type when null/empty."""
    tagged = df[PITCH_TYPE_COL].replace("", np.nan)
    return tagged.fillna(df["auto_pitch_type"]).fillna("Undefined")


# ============================ QUERIES =====================================

def game_pitches(game_id: int, pitcher_id: int) -> pd.DataFrame:
    return query_df(
        """
        SELECT *
          FROM fact_tm_game_pitch
         WHERE game_id = :gid AND pitcher_id = :pid
         ORDER BY pitch_no
        """,
        {"gid": game_id, "pid": pitcher_id},
    )


def game_context(game_id: int) -> dict:
    # NOTE: tm_team has no `name` column — the actual columns are
    # team_id/school_name/team_name/nickname (verified against the live
    # warehouse schema). vw_pitcher_appearance_velo joins on `team_name` the
    # same way, so we mirror that here for a short, display-friendly label.
    dim = query_df(
        """
        SELECT g.game_date, g.season_label, g.game_type,
               ht.team_name AS home_team, at.team_name AS away_team,
               g.home_team_id, g.away_team_id
          FROM dim_tm_game g
          LEFT JOIN tm_team ht ON ht.team_id = g.home_team_id
          LEFT JOIN tm_team at ON at.team_id = g.away_team_id
         WHERE g.game_id = :gid
        """,
        {"gid": game_id},
    )
    if dim.empty:
        raise KeyError(f"No dim_tm_game row for game_id={game_id}")
    row = dim.iloc[0]

    # Final score: sum runs_scored by batting half. Top => away bats, Bottom => home.
    runs = query_df(
        """
        SELECT top_bottom, COALESCE(SUM(runs_scored), 0) AS runs
          FROM fact_tm_game_pitch
         WHERE game_id = :gid
         GROUP BY top_bottom
        """,
        {"gid": game_id},
    ).set_index("top_bottom")["runs"].to_dict()
    away_runs = int(runs.get("Top", 0))
    home_runs = int(runs.get("Bottom", 0))

    lmu_is_home = str(row["home_team"]).upper().startswith("LMU") or \
        str(row["home_team"]) in LMU_TEAMS
    return {
        "game_date": row["game_date"],
        "season_label": row["season_label"],
        "game_type": row["game_type"],
        "home_team": row["home_team"],
        "away_team": row["away_team"],
        "lmu_runs": home_runs if lmu_is_home else away_runs,
        "opp_runs": away_runs if lmu_is_home else home_runs,
        "lmu_is_home": bool(lmu_is_home),
    }


def recent_outings(pitcher_id: int, game_id: int, n: int = 5) -> pd.DataFrame:
    """This outing + prior ones, newest first, up to n rows."""
    df = query_df(
        """
        SELECT game_id, game_date, season_label, game_type,
               home_team_name, away_team_name,
               appearance_avg_velo, appearance_max_velo, appearance_min_velo,
               pitch_count
          FROM vw_pitcher_recent_outings
         WHERE pitcher_id = :pid
         ORDER BY game_date DESC
        """,
        {"pid": pitcher_id},
    )
    if df.empty:
        return df
    this_date = df.loc[df["game_id"] == game_id, "game_date"]
    if not this_date.empty:
        df = df[df["game_date"] <= this_date.iloc[0]]
    return df.head(n).reset_index(drop=True)


def velo_trend(pitcher_id: int) -> pd.DataFrame:
    return query_df(
        """
        SELECT game_date, avg_velo, max_velo, pitch_count, velo_change
          FROM vw_pitcher_velo_trend
         WHERE pitcher_id = :pid
         ORDER BY game_date
        """,
        {"pid": pitcher_id},
    )


def pitcher_name(pitcher_id: int) -> str:
    df = query_df(
        "SELECT first_name, last_name FROM tm_player WHERE player_id = :pid",
        {"pid": pitcher_id},
    )
    if df.empty:
        return f"Pitcher {pitcher_id}"
    r = df.iloc[0]
    return f"{r['first_name']} {r['last_name']}".strip()


def pitcher_tm_id_for(pitcher_id: int) -> int | None:
    """Raw Trackman id for a warehouse pitcher_id (for role gating)."""
    df = query_df(
        """
        SELECT pitcher_tm_id
          FROM fact_tm_game_pitch
         WHERE pitcher_id = :pid AND pitcher_tm_id IS NOT NULL
         LIMIT 1
        """,
        {"pid": pitcher_id},
    )
    return None if df.empty else int(df.iloc[0]["pitcher_tm_id"])
