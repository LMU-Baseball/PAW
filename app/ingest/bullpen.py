"""BULLPEN (Trackman practice-pitching) CSV parsing + SFTP loader.

Pure parsing (no network, no DB) lives in ``parse_bullpen_csv``/``dedup_key``
-- selects the CSV columns that map 1:1 into the BULLPEN DB table (identical
names) and computes a per-row dedup key.

The loader (``iter_practice_pitching_files`` / ``load_bullpen``) walks the
Trackman SFTP ``/practice`` tree, parses each ``Pitching_*.csv`` file, dedups
against already-loaded PlayIDs, and inserts the rest (insert-only; never
DELETE/DROP). ``existing_keys``/``chunked_insert`` are imported as module
attributes (not called via ``common.``) so tests can monkeypatch them.
"""
from __future__ import annotations

import posixpath
import stat

import pandas as pd

from app.ingest.common import LoadResult, chunked_insert, existing_keys

# The 68 CSV columns that map 1:1 (identical names) into the 79-column
# BULLPEN DB table. The remaining 11 BULLPEN columns are derived/loader-set
# and are simply absent from the parser's output (NULL on insert).
BULLPEN_COLS: list[str] = [
    "PitchNo", "Date", "Time", "Pitcher", "PitcherId", "PitcherThrows",
    "PitcherTeam", "PitcherSet", "TaggedPitchType", "PitchSession", "Flag",
    "RelSpeed", "VertRelAngle", "HorzRelAngle", "SpinRate", "SpinAxis",
    "Tilt", "RelHeight", "RelSide", "Extension", "VertBreak",
    "InducedVertBreak", "HorzBreak", "PlateLocHeight", "PlateLocSide",
    "ZoneSpeed", "VertApprAngle", "HorzApprAngle", "ZoneTime", "pfxx",
    "pfxz", "x0", "y0", "z0", "vx0", "vy0", "vz0", "ax0", "ay0", "az0",
    "PlayID", "CalibrationId", "EffVelocity", "PracticeType", "Device",
    "Direction", "BatterId", "Batter", "HitSpinRate", "HitType",
    "ExitSpeed", "BatterSide", "Angle", "PositionAt110X", "PositionAt110Y",
    "PositionAt110Z", "Distance", "LastTrackedDistance", "HangTime",
    "Bearing", "ContactPositionX", "ContactPositionY", "ContactPositionZ",
    "SpinAxis3dTransverseAngle", "SpinAxis3dLongitudinalAngle",
    "SpinAxis3dActiveSpinRate", "SpinAxis3dSpinEfficiency", "SpinAxis3dTilt",
]


def parse_bullpen_csv(df: pd.DataFrame, *, source_file: str) -> pd.DataFrame:
    """Select the BULLPEN-mapped columns from a raw Trackman practice CSV.

    Drops any CSV columns not in ``BULLPEN_COLS``. Adds nothing extra (no
    ``source_file`` column -- ``source_file`` is accepted for interface
    symmetry with the loader but not otherwise used by this pure parser).
    Filters no rows -- file-level filtering happens in the loader.
    """
    cols = [c for c in BULLPEN_COLS if c in df.columns]
    return df[cols].copy()


def dedup_key(row: dict) -> str:
    """Per-row dedup key: PlayID if present, else a composite key.

    ``str(row['PlayID'])`` when PlayID is truthy/non-empty; pandas NaN and
    empty-string PlayID count as "not present". Otherwise falls back to
    ``f"{PitcherId}|{Date}|{Time}|{PitchNo}"``.
    """
    play_id = row.get("PlayID")
    if isinstance(play_id, float) and pd.isna(play_id):
        play_id = None
    if play_id not in (None, ""):
        return str(play_id)
    return f"{row.get('PitcherId')}|{row.get('Date')}|{row.get('Time')}|{row.get('PitchNo')}"


def iter_practice_pitching_files(sftp, root: str = "/practice") -> list[str]:
    """Recursively walk `root` on `sftp`, returning full paths of files whose
    basename starts with ``Pitching_`` and ends with ``.csv``.

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
            elif entry.filename.startswith("Pitching_") and entry.filename.endswith(".csv"):
                found.append(path)
    return sorted(found)


def _read_csv_from_sftp(sftp, path: str) -> pd.DataFrame:
    """Open `path` on `sftp` and parse it as CSV via pandas.

    Kept as a small internal seam so tests can monkeypatch the read step
    (avoiding real network I/O) without faking a full SFTP file object.
    """
    with sftp.open(path) as f:
        return pd.read_csv(f)


def load_bullpen(engine, sftp, *, dry_run: bool = True, limit: int | None = None) -> LoadResult:
    """Walk the Trackman `/practice` tree for `Pitching_*.csv` files, parse
    each with `parse_bullpen_csv`, dedup rows against BULLPEN.PlayID (both
    already-loaded rows and within-run duplicates), and insert the new rows
    via `chunked_insert` (skipped entirely when `dry_run`).

    Insert-only: never DELETEs or DROPs existing rows. `date_min`/`date_max`
    are computed from the `Date` column of the rows selected for insert.
    """
    files = iter_practice_pitching_files(sftp)
    if limit is not None:
        files = files[:limit]

    already_loaded = existing_keys(engine, "BULLPEN", "PlayID")
    seen: set[str] = set()
    rows_to_insert: list[dict] = []
    skipped = 0

    for path in files:
        raw_df = _read_csv_from_sftp(sftp, path)
        parsed = parse_bullpen_csv(raw_df, source_file=path)
        for row in parsed.to_dict(orient="records"):
            key = dedup_key(row)
            if key in already_loaded or key in seen:
                skipped += 1
                continue
            seen.add(key)
            rows_to_insert.append(row)

    inserted = len(rows_to_insert)
    if not dry_run and rows_to_insert:
        chunked_insert(engine, "BULLPEN", rows_to_insert)

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
