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


# --- Pipeline (goal 3): LMU-aware + upload-folder-pruned selection -----------

def test_dir_within_window_year_month_day():
    import datetime as dt
    from app.ingest import games
    cut = dt.date(2026, 9, 10)
    assert games._dir_within_window("/v3/2026", cut) is True         # year open
    assert games._dir_within_window("/v3/2026/09", cut) is True      # month open
    assert games._dir_within_window("/v3/2026/09/15", cut) is True   # after cutoff
    assert games._dir_within_window("/v3/2026/09/05", cut) is False  # before cutoff
    assert games._dir_within_window("/v3/2025", cut) is False        # old year
    assert games._dir_within_window("/v3/2026/09/15/CSV", cut) is True  # non-date leaf


def test_is_lmu_game_by_foreign_id_or_team_code():
    from app.ingest import games
    assert games.is_lmu_game(pd.DataFrame({"HomeTeamForeignID": [78], "AwayTeamForeignID": [12]}))
    assert games.is_lmu_game(pd.DataFrame({"AwayTeamForeignID": [78]}))
    assert games.is_lmu_game(pd.DataFrame({"PitcherTeam": ["LOY_LIO"], "BatterTeam": ["X"]}))
    assert not games.is_lmu_game(pd.DataFrame({"HomeTeamForeignID": [12], "AwayTeamForeignID": [34]}))
    assert not games.is_lmu_game(pd.DataFrame({"PitcherTeam": ["SAN_TOR"]}))


class _Entry:
    def __init__(self, name, is_dir):
        import stat as _s
        self.filename = name
        self.st_mode = _s.S_IFDIR if is_dir else _s.S_IFREG


class _FakeSFTP:
    def __init__(self, tree):
        self.tree = tree

    def listdir_attr(self, path):
        return [_Entry(n, d) for (n, d) in self.tree.get(path, [])]


_TREE = {
    "/v3": [("2026", True)],
    "/v3/2026": [("09", True)],
    "/v3/2026/09": [("15", True), ("05", True)],
    "/v3/2026/09/15": [("CSV", True)],
    "/v3/2026/09/15/CSV": [("20260914-LMU-1.csv", False),
                           ("20260914-Other-1.csv", False)],
    # in-window LMU + non-LMU games
    "/v3/2026/09/05": [("CSV", True)],   # out-of-window: must be pruned (not walked)
    "/v3/2026/09/05/CSV": [("20260904-LMU-2.csv", False)],
}


def _fake_read(sftp, path):
    if "Other" in path:
        return pd.DataFrame({"PitchUID": ["o1"], "Date": ["2026-09-14"],
                             "HomeTeamForeignID": [12], "AwayTeamForeignID": [34]})
    n = path.rsplit("/", 1)[-1]  # distinct UIDs per file so no cross-file dedup
    return pd.DataFrame({"PitchUID": [f"{n}-a", f"{n}-b"], "Date": ["2026-09-14", "2026-09-14"],
                         "HomeTeamForeignID": [78, 78], "AwayTeamForeignID": [12, 12]})


def test_load_games_window_prune_and_lmu_filter(monkeypatch):
    import datetime as dt
    from app.ingest import games
    monkeypatch.setattr(games, "_today", lambda: dt.date(2026, 9, 16))
    monkeypatch.setattr(games, "existing_keys", lambda *a, **k: set())
    monkeypatch.setattr(games, "_read_csv_from_sftp", _fake_read)
    sftp = _FakeSFTP(_TREE)

    # since_days=3 (cutoff 2026-09-13): only /v3/2026/09/15 in window; 09/05 pruned.
    r = games.load_games(engine=None, sftp=sftp, dry_run=True, since_days=3, lmu_only=True)
    assert r.files == 2                 # both files under 09/15/CSV; 09/05 pruned
    assert r.inserted == 2             # the LMU game's 2 rows
    assert r.skipped_non_lmu == 1      # the Other (non-LMU) game

    # since_days=None: full walk reaches the pruned 09/05 folder too.
    r_all = games.load_games(engine=None, sftp=sftp, dry_run=True, since_days=None, lmu_only=True)
    assert r_all.files == 3
