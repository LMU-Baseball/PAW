"""GAMES (Trackman regular/scrimmage game) CSV parsing (pure, no network/DB).

``parse_game_csv`` renames the raw Trackman v3 game-export CSV's columns to
their GAMES DB table names via ``CSV_TO_GAMES`` (the only name difference is
``'Top/Bottom' -> 'Top.Bottom'``; every other CSV column already matches its
GAMES column name 1:1) and selects the columns present in ``GAMES_COLS``.

``GAMES_COLS`` is the 167-name intersection of the CSV's mapped columns and
the 175-column GAMES table; GAMES's other 8 columns (AreaNum/InZone/Zone/
AreaOfZone/Stuff/Runners/QC/PathQ) are derived/loader-set and simply absent
from this parser's output (NULL on insert). ``PitchUID`` is preserved
unchanged so a later loader can dedup on it.

The loader (``iter_game_files`` / ``load_games``) walks the Trackman SFTP
``/v3`` tree, parses each game-export CSV, dedups against already-loaded
PitchUIDs, and inserts the rest (insert-only; never DELETE/DROP).
``existing_keys``/``chunked_insert`` are imported as module attributes (not
called via ``common.``) so tests can monkeypatch them.
"""
from __future__ import annotations

import posixpath
import re
import stat

import pandas as pd

from app.ingest.common import LoadResult, chunked_insert, existing_keys

# Game CSV basenames look like "20260416-CypressCollege-1.csv": 8 digits
# (the game date) then a dash.
_GAME_FILENAME_RE = re.compile(r"^\d{8}-.*\.csv$")

# Maps each of the 167 raw Trackman game-CSV column names to its GAMES DB
# column name. Identity for every column except the one known difference.
CSV_TO_GAMES: dict[str, str] = {
    "PitchNo": "PitchNo",
    "Date": "Date",
    "Time": "Time",
    "PAofInning": "PAofInning",
    "PitchofPA": "PitchofPA",
    "Pitcher": "Pitcher",
    "PitcherId": "PitcherId",
    "PitcherThrows": "PitcherThrows",
    "PitcherTeam": "PitcherTeam",
    "Batter": "Batter",
    "BatterId": "BatterId",
    "BatterSide": "BatterSide",
    "BatterTeam": "BatterTeam",
    "PitcherSet": "PitcherSet",
    "Inning": "Inning",
    "Top/Bottom": "Top.Bottom",  # only CSV/GAMES name difference
    "Outs": "Outs",
    "Balls": "Balls",
    "Strikes": "Strikes",
    "TaggedPitchType": "TaggedPitchType",
    "AutoPitchType": "AutoPitchType",
    "PitchCall": "PitchCall",
    "KorBB": "KorBB",
    "TaggedHitType": "TaggedHitType",
    "PlayResult": "PlayResult",
    "OutsOnPlay": "OutsOnPlay",
    "RunsScored": "RunsScored",
    "Notes": "Notes",
    "RelSpeed": "RelSpeed",
    "VertRelAngle": "VertRelAngle",
    "HorzRelAngle": "HorzRelAngle",
    "SpinRate": "SpinRate",
    "SpinAxis": "SpinAxis",
    "Tilt": "Tilt",
    "RelHeight": "RelHeight",
    "RelSide": "RelSide",
    "Extension": "Extension",
    "VertBreak": "VertBreak",
    "InducedVertBreak": "InducedVertBreak",
    "HorzBreak": "HorzBreak",
    "PlateLocHeight": "PlateLocHeight",
    "PlateLocSide": "PlateLocSide",
    "ZoneSpeed": "ZoneSpeed",
    "VertApprAngle": "VertApprAngle",
    "HorzApprAngle": "HorzApprAngle",
    "ZoneTime": "ZoneTime",
    "ExitSpeed": "ExitSpeed",
    "Angle": "Angle",
    "Direction": "Direction",
    "HitSpinRate": "HitSpinRate",
    "PositionAt110X": "PositionAt110X",
    "PositionAt110Y": "PositionAt110Y",
    "PositionAt110Z": "PositionAt110Z",
    "Distance": "Distance",
    "LastTrackedDistance": "LastTrackedDistance",
    "Bearing": "Bearing",
    "HangTime": "HangTime",
    "pfxx": "pfxx",
    "pfxz": "pfxz",
    "x0": "x0",
    "y0": "y0",
    "z0": "z0",
    "vx0": "vx0",
    "vy0": "vy0",
    "vz0": "vz0",
    "ax0": "ax0",
    "ay0": "ay0",
    "az0": "az0",
    "HomeTeam": "HomeTeam",
    "AwayTeam": "AwayTeam",
    "Stadium": "Stadium",
    "Level": "Level",
    "League": "League",
    "GameID": "GameID",
    "PitchUID": "PitchUID",
    "EffectiveVelo": "EffectiveVelo",
    "MaxHeight": "MaxHeight",
    "MeasuredDuration": "MeasuredDuration",
    "SpeedDrop": "SpeedDrop",
    "PitchLastMeasuredX": "PitchLastMeasuredX",
    "PitchLastMeasuredY": "PitchLastMeasuredY",
    "PitchLastMeasuredZ": "PitchLastMeasuredZ",
    "ContactPositionX": "ContactPositionX",
    "ContactPositionY": "ContactPositionY",
    "ContactPositionZ": "ContactPositionZ",
    "GameUID": "GameUID",
    "UTCDate": "UTCDate",
    "UTCTime": "UTCTime",
    "LocalDateTime": "LocalDateTime",
    "UTCDateTime": "UTCDateTime",
    "AutoHitType": "AutoHitType",
    "System": "System",
    "HomeTeamForeignID": "HomeTeamForeignID",
    "AwayTeamForeignID": "AwayTeamForeignID",
    "GameForeignID": "GameForeignID",
    "Catcher": "Catcher",
    "CatcherId": "CatcherId",
    "CatcherThrows": "CatcherThrows",
    "CatcherTeam": "CatcherTeam",
    "PlayID": "PlayID",
    "PitchTrajectoryXc0": "PitchTrajectoryXc0",
    "PitchTrajectoryXc1": "PitchTrajectoryXc1",
    "PitchTrajectoryXc2": "PitchTrajectoryXc2",
    "PitchTrajectoryYc0": "PitchTrajectoryYc0",
    "PitchTrajectoryYc1": "PitchTrajectoryYc1",
    "PitchTrajectoryYc2": "PitchTrajectoryYc2",
    "PitchTrajectoryZc0": "PitchTrajectoryZc0",
    "PitchTrajectoryZc1": "PitchTrajectoryZc1",
    "PitchTrajectoryZc2": "PitchTrajectoryZc2",
    "HitSpinAxis": "HitSpinAxis",
    "HitTrajectoryXc0": "HitTrajectoryXc0",
    "HitTrajectoryXc1": "HitTrajectoryXc1",
    "HitTrajectoryXc2": "HitTrajectoryXc2",
    "HitTrajectoryXc3": "HitTrajectoryXc3",
    "HitTrajectoryXc4": "HitTrajectoryXc4",
    "HitTrajectoryXc5": "HitTrajectoryXc5",
    "HitTrajectoryXc6": "HitTrajectoryXc6",
    "HitTrajectoryXc7": "HitTrajectoryXc7",
    "HitTrajectoryXc8": "HitTrajectoryXc8",
    "HitTrajectoryYc0": "HitTrajectoryYc0",
    "HitTrajectoryYc1": "HitTrajectoryYc1",
    "HitTrajectoryYc2": "HitTrajectoryYc2",
    "HitTrajectoryYc3": "HitTrajectoryYc3",
    "HitTrajectoryYc4": "HitTrajectoryYc4",
    "HitTrajectoryYc5": "HitTrajectoryYc5",
    "HitTrajectoryYc6": "HitTrajectoryYc6",
    "HitTrajectoryYc7": "HitTrajectoryYc7",
    "HitTrajectoryYc8": "HitTrajectoryYc8",
    "HitTrajectoryZc0": "HitTrajectoryZc0",
    "HitTrajectoryZc1": "HitTrajectoryZc1",
    "HitTrajectoryZc2": "HitTrajectoryZc2",
    "HitTrajectoryZc3": "HitTrajectoryZc3",
    "HitTrajectoryZc4": "HitTrajectoryZc4",
    "HitTrajectoryZc5": "HitTrajectoryZc5",
    "HitTrajectoryZc6": "HitTrajectoryZc6",
    "HitTrajectoryZc7": "HitTrajectoryZc7",
    "HitTrajectoryZc8": "HitTrajectoryZc8",
    "ThrowSpeed": "ThrowSpeed",
    "PopTime": "PopTime",
    "ExchangeTime": "ExchangeTime",
    "TimeToBase": "TimeToBase",
    "CatchPositionX": "CatchPositionX",
    "CatchPositionY": "CatchPositionY",
    "CatchPositionZ": "CatchPositionZ",
    "ThrowPositionX": "ThrowPositionX",
    "ThrowPositionY": "ThrowPositionY",
    "ThrowPositionZ": "ThrowPositionZ",
    "BasePositionX": "BasePositionX",
    "BasePositionY": "BasePositionY",
    "BasePositionZ": "BasePositionZ",
    "ThrowTrajectoryXc0": "ThrowTrajectoryXc0",
    "ThrowTrajectoryXc1": "ThrowTrajectoryXc1",
    "ThrowTrajectoryXc2": "ThrowTrajectoryXc2",
    "ThrowTrajectoryYc0": "ThrowTrajectoryYc0",
    "ThrowTrajectoryYc1": "ThrowTrajectoryYc1",
    "ThrowTrajectoryYc2": "ThrowTrajectoryYc2",
    "ThrowTrajectoryZc0": "ThrowTrajectoryZc0",
    "ThrowTrajectoryZc1": "ThrowTrajectoryZc1",
    "ThrowTrajectoryZc2": "ThrowTrajectoryZc2",
    "PitchReleaseConfidence": "PitchReleaseConfidence",
    "PitchLocationConfidence": "PitchLocationConfidence",
    "PitchMovementConfidence": "PitchMovementConfidence",
    "HitLaunchConfidence": "HitLaunchConfidence",
    "HitLandingConfidence": "HitLandingConfidence",
    "CatcherThrowCatchConfidence": "CatcherThrowCatchConfidence",
    "CatcherThrowReleaseConfidence": "CatcherThrowReleaseConfidence",
    "CatcherThrowLocationConfidence": "CatcherThrowLocationConfidence",
}

# The 167 GAMES columns this parser targets (every CSV_TO_GAMES value; all
# 167 raw CSV columns had a GAMES match, so none were dropped). GAMES's
# remaining 8 columns (AreaNum/InZone/Zone/AreaOfZone/Stuff/Runners/QC/
# PathQ) are derived/loader-set and are simply absent here (NULL on insert).
GAMES_COLS: list[str] = [
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
    "CatcherThrowLocationConfidence",
]


def parse_game_csv(df: pd.DataFrame, *, source_file: str) -> pd.DataFrame:
    """Rename a raw Trackman game-export CSV's columns to GAMES names and
    select the columns present in ``GAMES_COLS``.

    Renames via ``CSV_TO_GAMES`` first (so ``Top/Bottom`` becomes
    ``Top.Bottom``), then selects whichever ``GAMES_COLS`` are present in
    the renamed frame -- dropping any extra/unexpected columns. Returns a
    copy; filters no rows. ``PitchUID`` is preserved unchanged so a later
    loader can dedup on it. ``source_file`` is accepted for interface
    symmetry with the eventual loader but not otherwise used by this pure
    parser.
    """
    renamed = df.rename(columns=CSV_TO_GAMES)
    cols = [c for c in GAMES_COLS if c in renamed.columns]
    return renamed[cols].copy()


def dedup_key(row: dict) -> str:
    """Per-row dedup key: PitchUID if present, else a composite key.

    ``str(row['PitchUID'])`` when PitchUID is truthy/non-empty; pandas NaN
    and empty-string PitchUID count as "not present" (a missing PitchUID
    must NOT become the literal string "nan"/"None" -- every such row would
    otherwise collapse onto one dedup key and get dropped). Falls back to
    ``f"{GameUID}|{PitchNo}"``, using GameID instead of GameUID when GameUID
    is itself missing (mirrors `bullpen.dedup_key`'s PlayID/composite
    pattern).
    """
    pitch_uid = row.get("PitchUID")
    if isinstance(pitch_uid, float) and pd.isna(pitch_uid):
        pitch_uid = None
    if pitch_uid not in (None, ""):
        return str(pitch_uid)

    game_uid = row.get("GameUID")
    if isinstance(game_uid, float) and pd.isna(game_uid):
        game_uid = None
    if game_uid in (None, ""):
        game_uid = row.get("GameID")

    return f"{game_uid}|{row.get('PitchNo')}"


def iter_game_files(sftp, root: str = "/v3") -> list[str]:
    """Recursively walk `root` on `sftp`, returning full paths of files whose
    basename matches a game-export CSV name (8 digits, a dash, then anything,
    e.g. ``20260416-CypressCollege-1.csv``) AND whose immediate parent
    directory is named ``CSV`` (the real Trackman tree is
    ``/v3/YYYY/MM/DD/CSV/YYYYMMDD-Opponent-N_unverified.csv``; sibling
    directories at the ``DD`` level may hold other export formats with
    similarly-named files, which must be excluded).

    Sorted for deterministic ordering (helps `date_min`/`date_max` reasoning
    and makes tests reproducible).
    """
    found: list[str] = []
    stack = [root]
    while stack:
        current = stack.pop()
        for entry in sftp.listdir_attr(current):
            path = posixpath.join(current, entry.filename)
            if stat.S_ISDIR(entry.st_mode):
                stack.append(path)
            elif (
                _GAME_FILENAME_RE.match(entry.filename)
                and posixpath.basename(current) == "CSV"
            ):
                found.append(path)
    return sorted(found)


def _read_csv_from_sftp(sftp, path: str) -> pd.DataFrame:
    """Open `path` on `sftp` and parse it as CSV via pandas.

    Kept as a small internal seam so tests can monkeypatch the read step
    (avoiding real network I/O) without faking a full SFTP file object.
    """
    with sftp.open(path) as f:
        return pd.read_csv(f)


def load_games(engine, sftp, *, dry_run: bool = True, limit: int | None = None) -> LoadResult:
    """Walk the Trackman `/v3` tree for game-export CSV files, parse each with
    `parse_game_csv`, dedup rows against GAMES.PitchUID (both already-loaded
    rows and within-run duplicates), and insert the new rows via
    `chunked_insert` (skipped entirely when `dry_run`).

    Insert-only: never DELETEs or DROPs existing rows. `date_min`/`date_max`
    are computed from the `Date` column of the rows selected for insert.
    """
    files = iter_game_files(sftp)
    if limit is not None:
        files = files[:limit]

    already_loaded = existing_keys(engine, "GAMES", "PitchUID")
    seen: set[str] = set()
    rows_to_insert: list[dict] = []
    skipped = 0

    for path in files:
        raw_df = _read_csv_from_sftp(sftp, path)
        parsed = parse_game_csv(raw_df, source_file=path)
        for row in parsed.to_dict(orient="records"):
            key = dedup_key(row)
            if key in already_loaded or key in seen:
                skipped += 1
                continue
            seen.add(key)
            rows_to_insert.append(row)

    inserted = len(rows_to_insert)
    if not dry_run and rows_to_insert:
        chunked_insert(engine, "GAMES", rows_to_insert)

    dates = [r.get("Date") for r in rows_to_insert if pd.notna(r.get("Date")) and r.get("Date") != ""]
    date_min = min(dates) if dates else None
    date_max = max(dates) if dates else None

    return LoadResult(
        inserted=inserted,
        skipped=skipped,
        files=len(files),
        date_min=date_min,
        date_max=date_max,
        dry_run=dry_run,
    )
