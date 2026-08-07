"""Pitcher data access on CAPS GAMES (replaces pitching.py's warehouse reads
for the QUERY layer only). Transforms + figures are imported from
`app.data.pitching` UNCHANGED -- they consume snake_case fact-style columns,
so `_PITCH_SELECT` aliases GAMES's CamelCase columns to those exact names.

Pitcher identity = RAW `GAMES.PitcherId` (== a player's trackman_id), unlike
the warehouse's surrogate pitcher_id. LMU pitchers: PitcherTeam='LOY_LIO'.
`app.data.pitching` remains the parity oracle (see tests/test_pitching_caps.py)
until Phase 3 removes its warehouse queries.
"""
from __future__ import annotations

import pandas as pd

from app.db import query_df

LMU_TEAM_ID = 78  # GAMES.HomeTeamForeignID/AwayTeamForeignID for LMU.
LMU_PITCHER_TEAM = "LOY_LIO"  # GAMES.PitcherTeam code for LMU (same as the fact table's).

# GAMES CamelCase -> the exact snake_case names app.data.pitching's transforms
# read, so those transforms run unchanged over a GAMES-sourced frame. Includes
# PlateLocHeight (paired with PlateLocSide) even though it isn't in the plan's
# aliasing list verbatim -- pitching.py's fig_location/fig_heatmap read
# plate_loc_height alongside plate_loc_side, and this module's loaders are the
# only place that can supply it.
_PITCH_SELECT = """
    PitchCall AS pitch_call, RelSpeed AS rel_speed, PlateLocSide AS plate_loc_side,
    PlateLocHeight AS plate_loc_height, InducedVertBreak AS induced_vert_break,
    HorzBreak AS horz_break, VertApprAngle AS vert_appr_angle,
    TaggedHitType AS tagged_hit_type, TaggedPitchType AS tagged_pitch_type,
    AutoPitchType AS auto_pitch_type, PlayResult AS play_result, KorBB AS korbb,
    Balls AS balls, Strikes AS strikes, Inning AS inning, PAofInning AS pa_of_inning,
    PitchofPA AS pitch_of_pa, PitchNo AS pitch_no, OutsOnPlay AS outs_on_play,
    RunsScored AS runs_scored, BatterSide AS batter_side, SpinRate AS spin_rate,
    RelHeight AS rel_height, RelSide AS rel_side, Extension AS extension,
    ExitSpeed AS exit_speed, Zone AS izt_zone, GameID AS game_id,
    PitcherId AS pitcher_id, `Top.Bottom` AS top_bottom
"""


def _in_clause(ids) -> tuple[str, dict]:
    """Build a parameterized `IN (...)` fragment + params dict for a list of ids."""
    ph = ", ".join(f":id{i}" for i in range(len(ids)))
    return ph, {f"id{i}": int(v) for i, v in enumerate(ids)}


def _add_batters_faced(df: pd.DataFrame) -> pd.DataFrame:
    """Synthesize `batters_faced`, the warehouse's running-PA counter.

    GAMES has no such column, but `pitching.game_overall_line` reads
    `df["batters_faced"].max()`, which is just the count of distinct PAs
    (inning, pa_of_inning) in the frame. Since a pitcher's pitches for one PA
    are contiguous in pitch order, numbering PA-groups in order of first
    appearance (pandas `ngroup(sort=False)`) gives each row its PA's ordinal
    position -- a monotonically non-decreasing running counter whose max
    equals the total distinct-PA count, exactly like the warehouse counter
    `game_overall_line` reads. Mirrors `pitching._pa_count`'s group key
    (inning, pa_of_inning only -- no game_id), so behavior matches exactly on
    the single-game frames these loaders are actually read through.
    """
    if df.empty:
        df = df.copy()
        df["batters_faced"] = pd.Series(dtype="int64")
        return df
    df = df.sort_values("pitch_no").reset_index(drop=True)
    df["batters_faced"] = df.groupby(["inning", "pa_of_inning"], sort=False).ngroup() + 1
    return df


def _sibling_pitcher_ids(pitcher_id) -> list[int]:
    """All LMU GAMES.PitcherId values sharing this id's Pitcher name."""
    name = query_df(
        "SELECT Pitcher FROM GAMES WHERE PitcherId = :p AND PitcherTeam = :t LIMIT 1",
        {"p": int(pitcher_id), "t": LMU_PITCHER_TEAM},
    )
    if name.empty:
        return [int(pitcher_id)]
    ids = query_df(
        "SELECT DISTINCT PitcherId FROM GAMES WHERE Pitcher = :n AND PitcherTeam = :t "
        "AND PitcherId IS NOT NULL",
        {"n": str(name.iloc[0]["Pitcher"]), "t": LMU_PITCHER_TEAM},
    )
    return [int(x) for x in ids["PitcherId"]] or [int(pitcher_id)]


def game_pitches(game_id, pitcher_id) -> pd.DataFrame:
    """A single raw pitcher_id's pitches in one game (no sibling union)."""
    df = query_df(
        f"SELECT {_PITCH_SELECT} FROM GAMES WHERE GameID = :g AND PitcherId = :p "
        f"ORDER BY PitchNo",
        {"g": int(game_id), "p": int(pitcher_id)},
    )
    return _add_batters_faced(df)


def game_pitches_for(game_id, pitcher_id) -> pd.DataFrame:
    """A pitcher's pitches in a game, unioning split Trackman ids (dashboard/report use)."""
    ph, idp = _in_clause(_sibling_pitcher_ids(pitcher_id))
    idp["g"] = int(game_id)
    df = query_df(
        f"SELECT {_PITCH_SELECT} FROM GAMES WHERE GameID = :g AND PitcherId IN ({ph}) "
        f"ORDER BY PitchNo",
        idp,
    )
    return _add_batters_faced(df)


def range_pitches_for(pitcher_id, start, end) -> pd.DataFrame:
    """All of a pitcher's pitches across in-range games (sibling-id union)."""
    ph, idp = _in_clause(_sibling_pitcher_ids(pitcher_id))
    idp["start"] = str(start)
    idp["end"] = str(end)
    df = query_df(
        f"SELECT {_PITCH_SELECT} FROM GAMES WHERE PitcherId IN ({ph}) "
        f"AND Date BETWEEN :start AND :end "
        f"ORDER BY GameID, PitchNo",
        idp,
    )
    return _add_batters_faced(df)


def _season_label(date_str) -> str:
    """'Spring 2026' / 'Fall 2025' from a GAMES.Date -- GAMES has no
    season_label column, so derive it with the same Jan-Jun/Jul-Dec half-year
    split app.dashboards.date_range.season_block uses, matching the live
    dim_tm_game.season_label format verified against the warehouse ('Fall
    2025', 'Spring 2026')."""
    if date_str is None or (isinstance(date_str, float) and pd.isna(date_str)):
        return ""
    d = pd.to_datetime(date_str)
    return f"{'Spring' if d.month <= 6 else 'Fall'} {d.year}"


def game_context(game_id) -> dict:
    dim = query_df(
        "SELECT Date, GameType, HomeTeam, AwayTeam, HomeTeamForeignID "
        "FROM GAMES WHERE GameID = :g LIMIT 1",
        {"g": int(game_id)},
    )
    if dim.empty:
        raise KeyError(f"No GAMES row for game_id={game_id}")
    row = dim.iloc[0]

    # Final score: sum RunsScored by batting half. Top => away bats, Bottom => home.
    runs = query_df(
        "SELECT `Top.Bottom` AS top_bottom, COALESCE(SUM(RunsScored), 0) AS runs "
        "FROM GAMES WHERE GameID = :g GROUP BY `Top.Bottom`",
        {"g": int(game_id)},
    ).set_index("top_bottom")["runs"].to_dict()
    away_runs = int(runs.get("Top", 0))
    home_runs = int(runs.get("Bottom", 0))

    lmu_is_home = bool(row["HomeTeamForeignID"] == LMU_TEAM_ID)
    return {
        "game_date": row["Date"],
        "season_label": _season_label(row["Date"]),
        "game_type": None if pd.isna(row["GameType"]) else row["GameType"],
        "home_team": row["HomeTeam"],
        "away_team": row["AwayTeam"],
        "lmu_runs": home_runs if lmu_is_home else away_runs,
        "opp_runs": away_runs if lmu_is_home else home_runs,
        "lmu_is_home": lmu_is_home,
    }


# ============================ VELO VIEWS ===================================
#
# The warehouse's vw_pitcher_appearance_velo aggregates AVG/MAX/MIN(rel_speed)
# + COUNT(*) per (game, pitcher) FILTERED TO TaggedPitchType IN ('Fastball',
# 'Sinker') ONLY (verified from the live view definition) -- off-speed pitches
# don't count toward "velo". vw_pitcher_recent_outings joins that to the
# active-players roster; vw_pitcher_velo_trend adds a per-pitcher,
# per-season LAG for velo_change. GAMES has no roster/status table, so caps
# substitutes the LMU-pitcher filter (PitcherTeam='LOY_LIO', via
# _sibling_pitcher_ids) for "active roster". This is a PROVISIONAL,
# coach-confirmable difference: a pitcher who is on the historical LMU roster
# but not currently "active" would still show up here, where the warehouse
# view would have excluded them. No current fixture pitcher is affected.

_VELO_APPEARANCE_COLS = [
    "game_id", "game_date", "game_type", "home_team_name", "away_team_name",
    "appearance_avg_velo", "appearance_max_velo", "appearance_min_velo",
    "pitch_count",
]


def _pitcher_velo_appearances(pitcher_id) -> pd.DataFrame:
    """Per-appearance (game) Fastball/Sinker velo aggregates, sibling-id union.

    Mirrors the warehouse's vw_pitcher_appearance_velo. Adds `season_label`
    (derived, since GAMES has none) for velo_trend's season-partitioned LAG.
    """
    ph, idp = _in_clause(_sibling_pitcher_ids(pitcher_id))
    df = query_df(
        f"""
        SELECT GameID AS game_id, Date AS game_date, GameType AS game_type,
               HomeTeam AS home_team_name, AwayTeam AS away_team_name,
               AVG(RelSpeed) AS appearance_avg_velo,
               MAX(RelSpeed) AS appearance_max_velo,
               MIN(RelSpeed) AS appearance_min_velo,
               COUNT(*) AS pitch_count
          FROM GAMES
         WHERE PitcherId IN ({ph}) AND TaggedPitchType IN ('Fastball', 'Sinker')
         GROUP BY GameID, Date, GameType, HomeTeam, AwayTeam
        """,
        idp,
    )
    if df.empty:
        return df
    df["season_label"] = df["game_date"].apply(_season_label)
    return df


def recent_outings(pitcher_id, game_id, n: int = 5) -> pd.DataFrame:
    """This outing + prior ones, newest first, up to n rows.

    Mirrors `pitching.recent_outings`'s shape/behavior: pulls every
    Fastball/Sinker appearance for the pitcher, orders newest-first, then
    (if `game_id` is one of them) drops appearances after that game's date,
    and caps at `n` rows.
    """
    cols = ["game_id", "game_date", "season_label", "game_type",
            "home_team_name", "away_team_name", "appearance_avg_velo",
            "appearance_max_velo", "appearance_min_velo", "pitch_count"]
    df = _pitcher_velo_appearances(pitcher_id)
    if df.empty:
        return pd.DataFrame(columns=cols)
    df = df.sort_values("game_date", ascending=False, kind="mergesort").reset_index(drop=True)
    this_date = df.loc[df["game_id"] == int(game_id), "game_date"]
    if not this_date.empty:
        df = df[df["game_date"] <= this_date.iloc[0]]
    return df[cols].head(n).reset_index(drop=True)


def velo_trend(pitcher_id) -> pd.DataFrame:
    """Chronological avg/max velo per appearance, with velo_change vs the
    pitcher's previous appearance IN THE SAME SEASON (matches the oracle's
    `PARTITION BY pitcher_id, season_label ORDER BY game_date` LAG -- the
    first appearance of a season has a null velo_change)."""
    cols = ["game_date", "avg_velo", "max_velo", "pitch_count", "velo_change"]
    df = _pitcher_velo_appearances(pitcher_id)
    if df.empty:
        return pd.DataFrame(columns=cols)
    df = df.sort_values("game_date", kind="mergesort").reset_index(drop=True)
    df = df.rename(columns={
        "appearance_avg_velo": "avg_velo",
        "appearance_max_velo": "max_velo",
    })
    df["velo_change"] = df.groupby("season_label")["avg_velo"].diff()
    return df[cols]


def report_data_version(pitcher_id) -> str:
    """MAX(game_date) of the pitcher's Fastball/Sinker appearances, or 'none'.

    Cache-busting token for the postgame report (see
    `pitching.report_data_version`): new Fastball/Sinker data -> new max date
    -> new key -> rebuild; unchanged pitcher -> same key -> serve the cache.
    """
    df = _pitcher_velo_appearances(pitcher_id)
    if df.empty:
        return "none"
    v = df["game_date"].max()
    return "none" if v is None or pd.isna(v) else str(v)
