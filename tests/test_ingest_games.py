"""Tests for app.ingest.games (pure GAMES CSV parser + column map)."""
from pathlib import Path

import pandas as pd

from app.ingest.games import CSV_TO_GAMES, GAMES_COLS, parse_game_csv

FIXTURE = Path(__file__).parent / "fixtures" / "ingest" / "game_sample.csv"

# The exact 175 GAMES DB table column names (brief's GAMES_columns.txt,
# captured once from the schema -- not queried live here). The parser's
# output columns must all be members of this set -- NOT equal to it, since
# GAMES also has 8 derived columns (AreaNum/InZone/Zone/AreaOfZone/Stuff/
# Runners/QC/PathQ) absent from the CSV.
GAMES_TABLE_COLS = {
    "PitchNo", "Date", "Time", "PAofInning", "PitchofPA", "Pitcher",
    "PitcherId", "PitcherThrows", "PitcherTeam", "Batter", "BatterId",
    "BatterSide", "BatterTeam", "PitcherSet", "Inning", "Top.Bottom", "Outs",
    "Balls", "Strikes", "TaggedPitchType", "AutoPitchType", "PitchCall",
    "KorBB", "TaggedHitType", "PlayResult", "OutsOnPlay", "RunsScored",
    "Notes", "RelSpeed", "VertRelAngle", "HorzRelAngle", "SpinRate",
    "SpinAxis", "Tilt", "RelHeight", "RelSide", "Extension", "VertBreak",
    "InducedVertBreak", "HorzBreak", "PlateLocHeight", "PlateLocSide",
    "ZoneSpeed", "VertApprAngle", "HorzApprAngle", "ZoneTime", "ExitSpeed",
    "Angle", "Direction", "HitSpinRate", "PositionAt110X", "PositionAt110Y",
    "PositionAt110Z", "Distance", "LastTrackedDistance", "Bearing",
    "HangTime", "pfxx", "pfxz", "x0", "y0", "z0", "vx0", "vy0", "vz0", "ax0",
    "ay0", "az0", "HomeTeam", "AwayTeam", "Stadium", "Level", "League",
    "GameID", "PitchUID", "EffectiveVelo", "MaxHeight", "MeasuredDuration",
    "SpeedDrop", "PitchLastMeasuredX", "PitchLastMeasuredY",
    "PitchLastMeasuredZ", "ContactPositionX", "ContactPositionY",
    "ContactPositionZ", "GameUID", "UTCDate", "UTCTime", "LocalDateTime",
    "UTCDateTime", "AutoHitType", "System", "HomeTeamForeignID",
    "AwayTeamForeignID", "GameForeignID", "Catcher", "CatcherId",
    "CatcherThrows", "CatcherTeam", "PlayID", "PitchTrajectoryXc0",
    "PitchTrajectoryXc1", "PitchTrajectoryXc2", "PitchTrajectoryYc0",
    "PitchTrajectoryYc1", "PitchTrajectoryYc2", "PitchTrajectoryZc0",
    "PitchTrajectoryZc1", "PitchTrajectoryZc2", "HitSpinAxis",
    "HitTrajectoryXc0", "HitTrajectoryXc1", "HitTrajectoryXc2",
    "HitTrajectoryXc3", "HitTrajectoryXc4", "HitTrajectoryXc5",
    "HitTrajectoryXc6", "HitTrajectoryXc7", "HitTrajectoryXc8",
    "HitTrajectoryYc0", "HitTrajectoryYc1", "HitTrajectoryYc2",
    "HitTrajectoryYc3", "HitTrajectoryYc4", "HitTrajectoryYc5",
    "HitTrajectoryYc6", "HitTrajectoryYc7", "HitTrajectoryYc8",
    "HitTrajectoryZc0", "HitTrajectoryZc1", "HitTrajectoryZc2",
    "HitTrajectoryZc3", "HitTrajectoryZc4", "HitTrajectoryZc5",
    "HitTrajectoryZc6", "HitTrajectoryZc7", "HitTrajectoryZc8",
    "ThrowSpeed", "PopTime", "ExchangeTime", "TimeToBase", "CatchPositionX",
    "CatchPositionY", "CatchPositionZ", "ThrowPositionX", "ThrowPositionY",
    "ThrowPositionZ", "BasePositionX", "BasePositionY", "BasePositionZ",
    "ThrowTrajectoryXc0", "ThrowTrajectoryXc1", "ThrowTrajectoryXc2",
    "ThrowTrajectoryYc0", "ThrowTrajectoryYc1", "ThrowTrajectoryYc2",
    "ThrowTrajectoryZc0", "ThrowTrajectoryZc1", "ThrowTrajectoryZc2",
    "PitchReleaseConfidence", "PitchLocationConfidence",
    "PitchMovementConfidence", "HitLaunchConfidence", "HitLandingConfidence",
    "CatcherThrowCatchConfidence", "CatcherThrowReleaseConfidence",
    "CatcherThrowLocationConfidence", "AreaNum", "InZone", "Zone",
    "AreaOfZone", "Stuff", "Runners", "QC", "PathQ",
}


def test_games_table_cols_is_175_names():
    assert len(GAMES_TABLE_COLS) == 175


def test_csv_to_games_maps_top_bottom():
    assert CSV_TO_GAMES["Top/Bottom"] == "Top.Bottom"


def test_games_cols_are_all_in_the_games_table_set():
    assert set(GAMES_COLS).issubset(GAMES_TABLE_COLS)


def test_parse_game_csv_returns_30_rows():
    df = pd.read_csv(FIXTURE)
    out = parse_game_csv(df, source_file="game_sample.csv")
    assert len(out) == 30


def test_parse_game_csv_renames_top_bottom():
    df = pd.read_csv(FIXTURE)
    out = parse_game_csv(df, source_file="game_sample.csv")
    assert "Top.Bottom" in out.columns
    assert "Top/Bottom" not in out.columns


def test_parse_game_csv_contains_expected_columns():
    df = pd.read_csv(FIXTURE)
    out = parse_game_csv(df, source_file="game_sample.csv")
    for col in ("PitchUID", "GameID", "PitchNo", "TaggedPitchType", "AutoPitchType"):
        assert col in out.columns


def test_parse_game_csv_every_output_column_is_a_games_column():
    df = pd.read_csv(FIXTURE)
    out = parse_game_csv(df, source_file="game_sample.csv")
    for col in out.columns:
        assert col in GAMES_TABLE_COLS


def test_parse_game_csv_drops_columns_not_in_games_cols():
    df = pd.read_csv(FIXTURE)
    df["NotARealGamesColumn"] = "x"
    out = parse_game_csv(df, source_file="game_sample.csv")
    assert "NotARealGamesColumn" not in out.columns


def test_parse_game_csv_returns_a_copy_not_a_view():
    df = pd.read_csv(FIXTURE)
    out = parse_game_csv(df, source_file="game_sample.csv")
    out["PitchNo"] = 999999
    assert (df["PitchNo"] != 999999).any()
