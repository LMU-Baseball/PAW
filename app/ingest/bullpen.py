"""Pure parser for BULLPEN (Trackman practice-pitching) CSV exports.

No network, no DB -- selects the CSV columns that map 1:1 into the BULLPEN
DB table (identical names) and computes a per-row dedup key. File-level
filename filtering (e.g. only ``Pitching_*`` files) is the loader's job, not
this module's.
"""
from __future__ import annotations

import pandas as pd

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
