"""Bullpen (Trackman pitching-practice) data access + transforms.

Source = the legacy `BULLPEN` table (raw Trackman practice export, PascalCase
columns). Stale (ends 2025-04-14; feed dead) — repopulated later from an SFTP
drop; this module reads whatever the table currently holds. LMU-only.
"""
from __future__ import annotations

import pandas as pd

from app.db import query_df

LMU_BULLPEN_TEAMS = ("LOY_MAR", "LOY_LIO")

# Strike zone (ft, plate-center coords) + a one-ball edge buffer.
_SZ = dict(x0=-0.83, x1=0.83, y0=1.5, y1=3.5)
_EDGE = 0.24  # one-ball buffer (ft); provisional

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


def lmu_bullpen_pitchers(start=None, end=None) -> pd.DataFrame:
    """LMU pitchers present in BULLPEN, newest-session first.

    When both `start` and `end` are given, only pitchers with a bullpen
    session in [start, end] are returned (scopes the Pitcher dropdown to the
    selected date range). No args = unscoped, unchanged behavior.
    """
    clause, params = _teams_clause()
    where = f"{clause} AND PitcherId IS NOT NULL"
    if start is not None and end is not None:
        where += " AND DATE(Date) BETWEEN :start AND :end"
        params = {**params, "start": str(start), "end": str(end)}
    return query_df(
        f"""
        SELECT PitcherId AS pitcher_id, MAX(Pitcher) AS pitcher,
               COUNT(DISTINCT Date) AS sessions, MAX(Date) AS last_date
          FROM BULLPEN
         WHERE {where}
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


def strike_pct(df) -> float | None:
    """% of located pitches inside the strike zone + one-ball edge buffer."""
    if df is None or df.empty:
        return None
    d = df.dropna(subset=["plate_loc_side", "plate_loc_height"])
    if d.empty:
        return None
    inx = d["plate_loc_side"].between(_SZ["x0"] - _EDGE, _SZ["x1"] + _EDGE)
    iny = d["plate_loc_height"].between(_SZ["y0"] - _EDGE, _SZ["y1"] + _EDGE)
    return round(100.0 * float((inx & iny).mean()), 1)


def avg_fb_velo(df) -> float | None:
    if df is None or df.empty or "tagged_pitch_type" not in df.columns:
        return None
    fb = df[df["tagged_pitch_type"] == "Fastball"]["rel_speed"].dropna()
    return round(float(fb.mean()), 1) if not fb.empty else None


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


def pitcher_name(pitcher_id) -> str | None:
    """Display name ('Last, First') for a BULLPEN PitcherId, or None."""
    df = query_df("SELECT MAX(Pitcher) AS n FROM BULLPEN WHERE PitcherId = :pid",
                  {"pid": int(pitcher_id)})
    v = df.iloc[0]["n"] if not df.empty else None
    return None if v is None or pd.isna(v) else str(v)


def session_options(pitcher_id, start, end) -> pd.DataFrame:
    """Session dates (newest first) with pitch counts, within [start, end]."""
    df = query_df(
        """
        SELECT DATE(Date) AS date, COUNT(*) AS pitches
          FROM BULLPEN
         WHERE PitcherId = :pid AND DATE(Date) BETWEEN :start AND :end
         GROUP BY DATE(Date)
         ORDER BY date DESC
        """,
        {"pid": int(pitcher_id), "start": str(start), "end": str(end)},
    )
    if not df.empty:
        df["date"] = df["date"].astype(str)
    return df


def bullpen_session_summary(pitcher_id, start, end) -> dict:
    """Sidebar tiles: Sessions, Pitches, Strike %, Avg FB Velo, plus last_date."""
    df = query_df(
        """
        SELECT DATE(Date) AS date, TaggedPitchType AS tagged_pitch_type,
               RelSpeed AS rel_speed, PlateLocSide AS plate_loc_side,
               PlateLocHeight AS plate_loc_height
          FROM BULLPEN
         WHERE PitcherId = :pid AND DATE(Date) BETWEEN :start AND :end
        """,
        {"pid": int(pitcher_id), "start": str(start), "end": str(end)},
    )
    if df.empty:
        return {"sessions": 0, "pitches": 0, "strike_pct": None,
                "avg_fb_velo": None, "last_date": "—"}
    return {
        "sessions": int(df["date"].nunique()),
        "pitches": int(len(df)),
        "strike_pct": strike_pct(df),
        "avg_fb_velo": avg_fb_velo(df),
        "last_date": str(df["date"].max()),
    }


def trend_by_session(pitcher_id, start, end) -> pd.DataFrame:
    """Per (date, pitch_type) trend aggregates within [start, end].

    `loc_spread` = RMS distance of (PlateLocSide, PlateLocHeight) from the
    group's mean location — a command-CONSISTENCY proxy (lower = tighter),
    NOT true command (bullpens have no intended-target column). None when a
    group has <2 located pitches.
    """
    cols = ["date", "tagged_pitch_type", "pitches", "velo_avg", "velo_max",
            "spin_avg", "eff_avg", "ivb_avg", "hb_avg", "loc_spread"]
    df = query_df(
        """
        SELECT DATE(Date) AS date, TaggedPitchType AS tagged_pitch_type,
               RelSpeed AS rel_speed, SpinRate AS spin_rate,
               SpinAxis3dSpinEfficiency AS spin_eff,
               InducedVertBreak AS ind_vert_break, HorzBreak AS horz_break,
               PlateLocSide AS plate_loc_side, PlateLocHeight AS plate_loc_height
          FROM BULLPEN
         WHERE PitcherId = :pid AND DATE(Date) BETWEEN :start AND :end
           AND TaggedPitchType IS NOT NULL
        """,
        {"pid": int(pitcher_id), "start": str(start), "end": str(end)},
    )
    if df.empty:
        return pd.DataFrame(columns=cols)
    df["date"] = df["date"].astype(str)
    rows = []
    for (d, pt), sub in df.groupby(["date", "tagged_pitch_type"]):
        loc = sub[["plate_loc_side", "plate_loc_height"]].dropna()
        if len(loc) >= 2:
            cx, cy = loc["plate_loc_side"].mean(), loc["plate_loc_height"].mean()
            spread = round(float((((loc["plate_loc_side"] - cx) ** 2 +
                                   (loc["plate_loc_height"] - cy) ** 2).mean()) ** 0.5), 2)
        else:
            spread = None
        rows.append({
            "date": d, "tagged_pitch_type": pt, "pitches": int(len(sub)),
            "velo_avg": _r1(sub["rel_speed"].mean()), "velo_max": _r1(sub["rel_speed"].max()),
            "spin_avg": _r1(sub["spin_rate"].mean()), "eff_avg": _r1(sub["spin_eff"].mean()),
            "ivb_avg": _r1(sub["ind_vert_break"].mean()), "hb_avg": _r1(sub["horz_break"].mean()),
            "loc_spread": spread,
        })
    return (pd.DataFrame(rows, columns=cols)
            .sort_values(["tagged_pitch_type", "date"]).reset_index(drop=True))
