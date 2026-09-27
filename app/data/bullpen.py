"""Bullpen (Trackman pitching-practice) data access + transforms.

Source = the legacy `BULLPEN` table (raw Trackman practice export, PascalCase
columns), repopulated from an SFTP drop; this module reads whatever the table
currently holds (as of 2026-08-23 it runs through 2026-05-13). LMU-only.

`Date` is stored as TEXT holding ISO `YYYY-MM-DD` — verified uniform across all
24,581 rows, no blanks and no other format. So WHERE clauses compare it as a
plain string rather than wrapping it in `DATE(...)`: identical results, but a
function call around the column would make MySQL ignore
`ix_bullpen_pitcherid_date`. `DATE(Date)` in a SELECT/GROUP BY list is fine and
stays — only filters care.
"""
from __future__ import annotations

import pandas as pd

from app.db import query_df

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


def lmu_bullpen_pitchers(start=None, end=None) -> pd.DataFrame:
    """LMU pitchers present in BULLPEN, newest-session first, ONE row per
    distinct display name.

    No `PitcherTeam` filter: BULLPEN is fed solely by LMU's own practice
    Trackman unit (unlike GAMES, which comes off a conference-shared SFTP),
    so every row is an LMU pitcher regardless of whether that session's
    `PitcherTeam` tag was set on the device. Relying on the tag used to
    silently drop untagged sessions from the dropdown entirely -- see the
    2026-09-14 bullpen (6 pitchers, all `PitcherTeam IS NULL`) that never
    showed up until this filter was removed.

    When both `start` and `end` are given, only pitchers with a bullpen
    session in [start, end] are returned (scopes the Pitcher dropdown to the
    selected date range). No args = unscoped, unchanged behavior.

    2026-09-27 (Brad: "I don't want multiple Matt Morenos to select from, I
    just want all of his bullpens under one name") -- GROUPs by `Pitcher`
    (the display name), not `PitcherId`: Trackman has logged roughly two
    dozen LMU pitchers under more than one PitcherId over time (most likely
    device re-pairings), and grouping by id gave each one its own dropdown
    row under the identical name. `pitcher_id` is `MIN(PitcherId)` of
    whichever ids have a matching row in this window -- just ONE
    representative id for the dropdown's `value`; every read that follows a
    selection re-expands it to the FULL set of that name's ids via
    `pitcher_ids_for`, so which one got picked here doesn't matter.
    `sessions`/`last_date` are summed/maxed across all of that name's ids,
    so the dropdown label itself already reflects the combined count."""
    where = "PitcherId IS NOT NULL"
    params: dict = {}
    if start is not None and end is not None:
        where += " AND `Date` BETWEEN :start AND :end"
        params = {"start": str(start), "end": str(end)}
    return query_df(
        f"""
        SELECT MIN(PitcherId) AS pitcher_id, Pitcher AS pitcher,
               COUNT(DISTINCT Date) AS sessions, MAX(Date) AS last_date
          FROM BULLPEN
         WHERE {where}
         GROUP BY Pitcher
         ORDER BY last_date DESC, pitcher
        """,
        params,
    )


def pitcher_ids_for(pitcher_id: int) -> list[int]:
    """Every BULLPEN PitcherId sharing `pitcher_id`'s exact display name --
    the full set of ids a pitcher selection must query across (see
    `lmu_bullpen_pitchers`'s 2026-09-27 docstring note for why more than one
    id can share one real player). Every read below that takes a single
    `pitcher_id` expands it through this first, so a coach never has to know
    or care which of a player's ids they happened to click. Falls back to
    `[pitcher_id]` alone when the id has no BULLPEN rows at all (e.g. a
    roster placeholder id, or a bad/stale id) -- never an empty list, so a
    caller's `WHERE PitcherId IN (...)` is never left with nothing to match
    against and silently returns everything-filtered-out instead of an
    honest empty result for a genuinely unknown id."""
    df = query_df(
        """
        SELECT DISTINCT PitcherId FROM BULLPEN
         WHERE Pitcher = (SELECT MAX(Pitcher) FROM BULLPEN WHERE PitcherId = :pid)
        """,
        {"pid": int(pitcher_id)},
    )
    ids = [int(x) for x in df["PitcherId"]] if not df.empty else []
    return ids if ids else [int(pitcher_id)]


def _in_clause(column: str, values: list[int], prefix: str) -> tuple[str, dict]:
    """`f"{column} IN (:prefix0, :prefix1, ...)"` + the matching params dict
    -- `pd.read_sql`/`query_df` has no list-bind support for a plain `text()`
    query, so a variable-length IN clause needs one named placeholder per
    value instead of a single `:pids` param."""
    keys = [f"{prefix}{i}" for i in range(len(values))]
    clause = f"{column} IN ({', '.join(':' + k for k in keys)})"
    return clause, dict(zip(keys, values))


def sessions_for(pitcher_trackman_id: int) -> pd.DataFrame:
    """A pitcher's bullpen dates (newest first) with pitch counts, across
    every BULLPEN PitcherId that shares their display name (see
    `pitcher_ids_for`)."""
    clause, params = _in_clause("PitcherId", pitcher_ids_for(pitcher_trackman_id), "pid")
    df = query_df(
        f"""
        SELECT DATE(Date) AS date, COUNT(*) AS pitches
          FROM BULLPEN
         WHERE {clause}
         GROUP BY DATE(Date)
         ORDER BY date DESC
        """,
        params,
    )
    if not df.empty:
        df["date"] = df["date"].astype(str)
    return df


def session_pitches(pitcher_trackman_id: int, date) -> pd.DataFrame:
    """One session's per-pitch rows, normalized to snake_case (ordered by
    pitch), across every BULLPEN PitcherId that shares this pitcher's
    display name (see `pitcher_ids_for`) -- a device re-pairing mid-season
    could in principle put the same real session date under either id."""
    clause, params = _in_clause("PitcherId", pitcher_ids_for(pitcher_trackman_id), "pid")
    params["d"] = str(date)
    df = query_df(
        f"""
        SELECT * FROM BULLPEN
         WHERE {clause} AND `Date` = :d
         ORDER BY PitchNo
        """,
        params,
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


_POCKET_ROWS = ("Low", "Mid", "High")
_POCKET_COLS = ("Left", "Center", "Right")


def pocket_label(plate_loc_side, plate_loc_height) -> str | None:
    """Which of the 9 rulebook-zone cells (row x col, catcher's-view left/
    right -- same PlateLocSide sign convention `charts.location_fig` plots
    directly, no handedness flip) a location falls in, e.g. "High-Left".
    Buckets against `_SZ`'s thirds, clamped at the edges, so every located
    pitch gets a cell even well outside the box (a pitch two feet outside
    still reads "Mid-Right", not a dead end) -- None only for a missing
    location, matching `strike_pct`'s own null handling."""
    if plate_loc_side is None or plate_loc_height is None or pd.isna(plate_loc_side) or pd.isna(plate_loc_height):
        return None
    x, y = float(plate_loc_side), float(plate_loc_height)
    x_third = (_SZ["x1"] - _SZ["x0"]) / 3.0
    y_third = (_SZ["y1"] - _SZ["y0"]) / 3.0
    col = 0 if x < _SZ["x0"] + x_third else (2 if x > _SZ["x1"] - x_third else 1)
    row = 0 if y < _SZ["y0"] + y_third else (2 if y > _SZ["y1"] - y_third else 1)
    return f"{_POCKET_ROWS[row]}-{_POCKET_COLS[col]}"


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
    """Session dates (newest first) with pitch counts, within [start, end],
    across every BULLPEN PitcherId that shares this pitcher's display name
    (see `pitcher_ids_for`)."""
    clause, params = _in_clause("PitcherId", pitcher_ids_for(pitcher_id), "pid")
    params["start"], params["end"] = str(start), str(end)
    df = query_df(
        f"""
        SELECT DATE(Date) AS date, COUNT(*) AS pitches
          FROM BULLPEN
         WHERE {clause} AND `Date` BETWEEN :start AND :end
         GROUP BY DATE(Date)
         ORDER BY date DESC
        """,
        params,
    )
    if not df.empty:
        df["date"] = df["date"].astype(str)
    return df


def bullpen_session_summary(pitcher_id, start, end) -> dict:
    """Sidebar tiles: Sessions, Pitches, Strike %, Avg FB Velo, plus
    last_date -- across every BULLPEN PitcherId that shares this pitcher's
    display name (see `pitcher_ids_for`)."""
    clause, params = _in_clause("PitcherId", pitcher_ids_for(pitcher_id), "pid")
    params["start"], params["end"] = str(start), str(end)
    df = query_df(
        f"""
        SELECT DATE(Date) AS date, TaggedPitchType AS tagged_pitch_type,
               RelSpeed AS rel_speed, PlateLocSide AS plate_loc_side,
               PlateLocHeight AS plate_loc_height
          FROM BULLPEN
         WHERE {clause} AND `Date` BETWEEN :start AND :end
        """,
        params,
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
    group has <2 located pitches. Retained for potential future use even
    though it's no longer surfaced in the Development Trends UI.

    `strike_pct` reuses the same zone-based `strike_pct()` definition as the
    report header KPI and sidebar tile, for consistency across the app.
    """
    cols = ["date", "tagged_pitch_type", "pitches", "velo_avg", "velo_max",
            "spin_avg", "eff_avg", "ivb_avg", "hb_avg", "loc_spread", "strike_pct"]
    clause, params = _in_clause("PitcherId", pitcher_ids_for(pitcher_id), "pid")
    params["start"], params["end"] = str(start), str(end)
    df = query_df(
        f"""
        SELECT DATE(Date) AS date, TaggedPitchType AS tagged_pitch_type,
               RelSpeed AS rel_speed, SpinRate AS spin_rate,
               SpinAxis3dSpinEfficiency AS spin_eff,
               InducedVertBreak AS ind_vert_break, HorzBreak AS horz_break,
               PlateLocSide AS plate_loc_side, PlateLocHeight AS plate_loc_height
          FROM BULLPEN
         WHERE {clause} AND `Date` BETWEEN :start AND :end
           AND TaggedPitchType IS NOT NULL
        """,
        params,
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
            "strike_pct": strike_pct(sub),
        })
    return (pd.DataFrame(rows, columns=cols)
            .sort_values(["tagged_pitch_type", "date"]).reset_index(drop=True))
