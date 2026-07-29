"""Bullpen (Trackman pitching-practice) data access + transforms.

Source = the legacy `BULLPEN` table (raw Trackman practice export, PascalCase
columns). Stale (ends 2025-04-14; feed dead) — repopulated later from an SFTP
drop; this module reads whatever the table currently holds. LMU-only.
"""
from __future__ import annotations

import pandas as pd

from app.db import query_df

LMU_BULLPEN_TEAMS = ("LOY_MAR", "LOY_LIO")

# BULLPEN PascalCase -> our snake_case.
_COLMAP = {
    "PitchNo": "pitch_no", "TaggedPitchType": "tagged_pitch_type",
    "RelSpeed": "rel_speed", "SpinRate": "spin_rate",
    "SpinAxis3dSpinEfficiency": "spin_eff", "Tilt": "tilt",
    "InducedVertBreak": "ind_vert_break", "HorzBreak": "horz_break",
    "VertBreak": "vert_break", "RelHeight": "rel_height", "RelSide": "rel_side",
    "Extension": "extension", "PlateLocSide": "plate_loc_side",
    "PlateLocHeight": "plate_loc_height",
}


def _teams_clause():
    marks = ", ".join(f":t{i}" for i in range(len(LMU_BULLPEN_TEAMS)))
    params = {f"t{i}": v for i, v in enumerate(LMU_BULLPEN_TEAMS)}
    return f"PitcherTeam IN ({marks})", params


def lmu_bullpen_pitchers() -> pd.DataFrame:
    """LMU pitchers present in BULLPEN, newest-session first."""
    clause, params = _teams_clause()
    return query_df(
        f"""
        SELECT PitcherId AS pitcher_id, MAX(Pitcher) AS pitcher,
               COUNT(DISTINCT Date) AS sessions, MAX(Date) AS last_date
          FROM BULLPEN
         WHERE {clause} AND PitcherId IS NOT NULL
         GROUP BY PitcherId
         ORDER BY last_date DESC, pitcher
        """,
        params,
    )


def sessions_for(pitcher_trackman_id: int) -> pd.DataFrame:
    """A pitcher's bullpen dates (newest first) with pitch counts."""
    df = query_df(
        """
        SELECT DATE(Date) AS date, COUNT(*) AS pitches
          FROM BULLPEN
         WHERE PitcherId = :pid
         GROUP BY DATE(Date)
         ORDER BY date DESC
        """,
        {"pid": int(pitcher_trackman_id)},
    )
    if not df.empty:
        df["date"] = df["date"].astype(str)
    return df


def session_pitches(pitcher_trackman_id: int, date) -> pd.DataFrame:
    """One session's per-pitch rows, normalized to snake_case (ordered by pitch)."""
    df = query_df(
        """
        SELECT * FROM BULLPEN
         WHERE PitcherId = :pid AND DATE(Date) = :d
         ORDER BY PitchNo
        """,
        {"pid": int(pitcher_trackman_id), "d": str(date)},
    )
    if df.empty:
        return pd.DataFrame(columns=list(_COLMAP.values()))
    keep = {k: v for k, v in _COLMAP.items() if k in df.columns}
    return df[list(keep)].rename(columns=keep).reset_index(drop=True)


def _r1(x):
    return None if x is None or pd.isna(x) else round(float(x), 1)


def summary_by_pitch_type(df: pd.DataFrame) -> list[dict]:
    """Per-pitch-type aggregates for the Stats-by-pitch-type table."""
    if df is None or df.empty:
        return []
    rows = []
    for pt, sub in df.groupby("tagged_pitch_type"):
        rows.append({
            "pitch": pt, "qty": int(len(sub)),
            "velo_min": _r1(sub["rel_speed"].min()),
            "velo_max": _r1(sub["rel_speed"].max()),
            "velo_avg": _r1(sub["rel_speed"].mean()),
            "spin_min": _r1(sub["spin_rate"].min()),
            "spin_max": _r1(sub["spin_rate"].max()),
            "spin_avg": _r1(sub["spin_rate"].mean()),
            "ivb_avg": _r1(sub["ind_vert_break"].mean()),
            "hb_avg": _r1(sub["horz_break"].mean()),
            "vert_avg": _r1(sub["vert_break"].mean()),
            "rel_h_avg": _r1(sub["rel_height"].mean()),
            "rel_side_avg": _r1(sub["rel_side"].mean()),
            "ext_avg": _r1(sub["extension"].mean()),
            "_c": len(sub),
        })
    rows.sort(key=lambda r: r["_c"], reverse=True)
    for r in rows:
        del r["_c"]
    return rows


def bullpen_data_max_date():
    """Most recent bullpen date in the table (for the 'data through' note)."""
    df = query_df("SELECT MAX(DATE(Date)) AS d FROM BULLPEN")
    v = df.iloc[0]["d"] if not df.empty else None
    return None if v is None or pd.isna(v) else str(v)
