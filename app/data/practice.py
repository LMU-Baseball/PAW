"""HitTrax practice analytics data layer.

Ports loaders/transforms from BRADhaskell/lmu-baseball-practice-analytics
`dashboard/app.py` onto PAW's shared analytics MySQL (MYSQL_* → same RDS that
holds the Trackman warehouse). Tables: practice_plays, practice_sessions,
player_stats_summary.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from app.db import query_df

HIT_TYPE_MAP = {0: "Miss/Foul", 1: "Ground Ball", 2: "Line Drive", 3: "Fly Ball"}

SESSION_TYPE_MAP = {
    1: "Hitting", 4: "Baseline", 5: "HitLab", 7: "Quality Hit Game",
    8: "Unknown", 11: "Game", 12: "Entertainment", 16: "Drill",
}

SWING_DECISION_LABEL = "Swing Decision"
SWING_DECISION_START = pd.Timestamp("2026-03-31")
SWING_DECISION_END = pd.Timestamp("2026-06-01")

# College strike zone (feet) — catcher's view
SZ_X0, SZ_X1 = -0.708, 0.708
SZ_Y0, SZ_Y1 = 1.5, 3.5


def current_season_start() -> str:
    today = date.today()
    year = today.year if today.month >= 8 else today.year - 1
    return f"{year}-08-01"


def date_bounds() -> tuple:
    df = query_df(
        "SELECT MIN(session_date) AS min_d, MAX(session_date) AS max_d "
        "FROM practice_sessions WHERE session_date IS NOT NULL"
    )
    if df.empty:
        return date(2023, 1, 1), date.today()
    mn, mx = df.iloc[0]["min_d"], df.iloc[0]["max_d"]
    return (mn if pd.notna(mn) else date(2023, 1, 1),
            mx if pd.notna(mx) else date.today())


def _test_clause(col: str, exclude_test: bool) -> str:
    if not exclude_test:
        return ""
    return f" AND ({col} IS NULL OR {col} NOT LIKE '%%Test%%')"


def load_player_stats(exclude_test: bool = True) -> pd.DataFrame:
    season_start = current_season_start()
    where = f"WHERE player_id IS NOT NULL AND last_practice_date >= '{season_start}'"
    where += _test_clause("player_name", exclude_test)
    df = query_df(f"""
        SELECT player_id, player_name, total_plays, total_sessions,
               avg_exit_velocity, max_exit_velocity,
               avg_distance, max_distance,
               hard_hit_rate, fly_ball_rate, line_drive_rate,
               last_practice_date
          FROM player_stats_summary
          {where}
         ORDER BY total_plays DESC
    """)
    for col in ("total_plays", "total_sessions", "avg_exit_velocity",
                "max_exit_velocity", "avg_distance", "max_distance",
                "hard_hit_rate", "fly_ball_rate", "line_drive_rate"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def load_sessions(exclude_test: bool = True) -> pd.DataFrame:
    where = "WHERE session_date IS NOT NULL" + _test_clause("user_name", exclude_test)
    return query_df(f"""
        SELECT session_id, session_date,
               user_name AS player_name, player_id,
               avg_exit_velocity, max_exit_velocity,
               avg_distance, max_distance,
               total_plays, at_bats, hit_count, batting_avg,
               hard_hit_count, ground_ball_pct, fly_ball_pct, line_drive_pct,
               session_type, session_tag
          FROM practice_sessions
          {where}
         ORDER BY session_date DESC
    """)


def load_plays(exclude_test: bool = True) -> pd.DataFrame:
    where = "WHERE play_timestamp IS NOT NULL" + _test_clause("player_name", exclude_test)
    return query_df(f"""
        SELECT player_name, player_id,
               DATE(play_timestamp) AS play_date,
               exit_velocity, distance_feet, horizontal_angle,
               hit_type, launch_angle, session_id, result
          FROM practice_plays
          {where}
         ORDER BY play_timestamp
    """)


def load_pitch_coords(exclude_test: bool = True) -> pd.DataFrame:
    """Pitch location rows for heatmaps / swing decision (from Swing Decision start)."""
    sd = SWING_DECISION_START.strftime("%Y-%m-%d")
    where = (
        "WHERE pp.pitch_location_x IS NOT NULL AND pp.pitch_location_y IS NOT NULL"
        " AND pp.pitch_location_y BETWEEN 0.5 AND 5.5"
        " AND ABS(pp.pitch_location_x) < 3.0"
        f" AND DATE(pp.play_timestamp) >= '{sd}'"
    )
    where += _test_clause("pp.player_name", exclude_test)
    try:
        df = query_df(f"""
            SELECT pp.player_name, pp.player_id, pp.hand,
                   pp.pitch_location_x AS px, pp.pitch_location_y AS py,
                   pp.result, pp.exit_velocity, pp.distance_feet, pp.zone_section,
                   pp.play_timestamp, pp.session_id,
                   DATE(pp.play_timestamp) AS play_date,
                   ps.session_type, ps.session_tag
              FROM practice_plays pp
              LEFT JOIN practice_sessions ps ON pp.session_id = ps.session_id
              {where}
             ORDER BY pp.play_timestamp
        """)
    except Exception:
        return pd.DataFrame(columns=[
            "player_name", "player_id", "hand", "px", "py", "result",
            "exit_velocity", "distance_feet", "zone_section",
            "play_timestamp", "session_id", "play_date", "session_type", "session_tag",
        ])
    if not df.empty:
        df["session_display"] = df.apply(_session_display, axis=1)
        df["is_contact"] = df["result"] != -4
    return df


def _session_display(r) -> str:
    code = r.get("session_type")
    label = SESSION_TYPE_MAP.get(int(code), f"Type {code}") if pd.notna(code) else "Unknown"
    tag = r.get("session_tag")
    if tag is not None and not (isinstance(tag, float) and pd.isna(tag)) and str(tag).strip():
        return f"{label} — {tag}"
    return label


def trim_to_first_contact(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    d = df.sort_values(["player_name", "session_id", "play_timestamp"]).copy()
    d["_is_contact"] = d["result"] != -4
    d["_cumsum"] = d.groupby(["player_name", "session_id"])["_is_contact"].cumsum()
    return d[d["_cumsum"] >= 1].drop(columns=["_is_contact", "_cumsum"])


def apply_filters(
    pitch_df: pd.DataFrame,
    *,
    player: str | None,
    start: date | None,
    end: date | None,
    session: str | None,
) -> pd.DataFrame:
    """Filter pitch-coord rows by player / date / session display or Swing Decision."""
    if pitch_df.empty:
        return pitch_df.copy()
    d = pitch_df.copy()
    if player and player != "All Players":
        d = d[d["player_name"] == player]
    if start and end:
        dates = pd.to_datetime(d["play_date"])
        d = d[dates.between(pd.Timestamp(start), pd.Timestamp(end))]
    if session == SWING_DECISION_LABEL:
        dates = pd.to_datetime(d["play_date"])
        d = d[dates.between(SWING_DECISION_START, SWING_DECISION_END)]
    elif session and session not in ("All session types", "All Sessions", None, ""):
        d = d[d["session_display"] == session]
    if not d.empty and "is_contact" not in d.columns:
        d["is_contact"] = d["result"] != -4
    return d


def player_names(pitch_df: pd.DataFrame) -> list[str]:
    if pitch_df.empty:
        return []
    return sorted(n for n in pitch_df["player_name"].dropna().unique())


def session_options(pitch_df: pd.DataFrame) -> list[str]:
    opts = ["All session types", SWING_DECISION_LABEL]
    if pitch_df.empty or "session_display" not in pitch_df.columns:
        return opts
    extras = sorted(s for s in pitch_df["session_display"].dropna().unique() if s)
    for s in extras:
        if s not in opts:
            opts.append(s)
    return opts


def preset_date_range(preset: str) -> tuple[date, date]:
    today = date.today()
    days = {
        "Past Week": 7, "Past Month": 30, "Past 3 Months": 90,
        "Past Year": 365,
    }.get(preset)
    if days is None:
        return SWING_DECISION_START.date(), today
    return today - timedelta(days=days), today


# ============================ METRICS / CHARTS DATA ========================

def contact_summary(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"pitches": 0, "contacts": 0, "contact_pct": None,
                "in_zone": 0, "in_zone_contact_pct": None}
    n = len(df)
    contacts = int(df["is_contact"].sum()) if "is_contact" in df.columns else 0
    in_zone = df[(df["px"].between(SZ_X0, SZ_X1)) & (df["py"].between(SZ_Y0, SZ_Y1))]
    iz_n = len(in_zone)
    iz_c = int(in_zone["is_contact"].sum()) if iz_n and "is_contact" in in_zone.columns else 0
    return {
        "pitches": n,
        "contacts": contacts,
        "contact_pct": round(100.0 * contacts / n, 1) if n else None,
        "in_zone": iz_n,
        "in_zone_contact_pct": round(100.0 * iz_c / iz_n, 1) if iz_n else None,
    }


def swing_decision_score(df: pd.DataFrame) -> dict:
    """In-zone (1-9) contact% minus chase (10-13) contact%."""
    if df.empty or "zone_section" not in df.columns:
        return {"in_zone_pct": None, "chase_pct": None, "score": None}
    d = df[df["zone_section"] > 0].copy()
    if d.empty:
        return {"in_zone_pct": None, "chase_pct": None, "score": None}
    iz = d[d["zone_section"].between(1, 9)]
    ch = d[d["zone_section"].between(10, 13)]

    def _pct(sub):
        if sub.empty:
            return None
        return round(100.0 * int(sub["is_contact"].sum()) / len(sub), 1)

    izp, chp = _pct(iz), _pct(ch)
    score = None if izp is None or chp is None else round(izp - chp, 1)
    return {"in_zone_pct": izp, "chase_pct": chp, "score": score}


def zone_contact_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "zone_section" not in df.columns:
        return pd.DataFrame(columns=["Zone", "Pitches", "Contacts", "Contact%", "Avg EV"])
    d = df[df["zone_section"] > 0].copy()
    rows = []
    for z in sorted(d["zone_section"].dropna().unique()):
        sub = d[d["zone_section"] == z]
        n = len(sub)
        c = int(sub["is_contact"].sum())
        ev = sub.loc[sub["is_contact"], "exit_velocity"].dropna()
        rows.append({
            "Zone": int(z), "Pitches": n, "Contacts": c,
            "Contact%": round(100.0 * c / n, 1) if n else None,
            "Avg EV": round(float(ev.mean()), 1) if len(ev) else None,
        })
    return pd.DataFrame(rows)


def heatmap_metric(df: pd.DataFrame, metric: str = "contact", bins: int = 20):
    """(z, x_edges, y_edges) grid for a Plotly heatmap. metric: contact|ev|distance.
    z[y][x]; NaN where no pitches in a bin."""
    xedges = np.linspace(-2, 2, bins + 1)
    yedges = np.linspace(0.5, 5.0, bins + 1)
    if df.empty:
        return np.full((bins, bins), np.nan), xedges, yedges
    d = df.dropna(subset=["px", "py"]).copy()
    if metric == "contact":
        d["_c"] = d["result"] != -4
        counts, _, _ = np.histogram2d(d["px"], d["py"], bins=[xedges, yedges])
        made, _, _ = np.histogram2d(d.loc[d["_c"], "px"], d.loc[d["_c"], "py"],
                                    bins=[xedges, yedges])
        with np.errstate(divide="ignore", invalid="ignore"):
            z = np.where(counts > 0, 100.0 * made / counts, np.nan)
    else:
        col = "exit_velocity" if metric == "ev" else "distance_feet"
        sub = d[d[col].notna()]
        counts, _, _ = np.histogram2d(sub["px"], sub["py"], bins=[xedges, yedges])
        sums, _, _ = np.histogram2d(sub["px"], sub["py"], bins=[xedges, yedges],
                                    weights=sub[col])
        with np.errstate(divide="ignore", invalid="ignore"):
            z = np.where(counts > 0, sums / counts, np.nan)
    return z.T, xedges, yedges


def heatmap_contact_rate(df: pd.DataFrame, bins: int = 20):
    """Back-compat wrapper: contact-rate grid."""
    return heatmap_metric(df, "contact", bins)


def swing_decision_trend(df: pd.DataFrame) -> pd.DataFrame:
    """Per-date swing-decision score (in-zone 1-9 contact% - chase 10-13 contact%).
    Only dates where the score is computable. PROVISIONAL."""
    cols = ["play_date", "in_zone_pct", "chase_pct", "score"]
    if df.empty or "play_date" not in df.columns:
        return pd.DataFrame(columns=cols)
    rows = []
    for d, sub in df.groupby("play_date"):
        s = swing_decision_score(sub)
        if s["score"] is not None:
            rows.append({"play_date": d, "in_zone_pct": s["in_zone_pct"],
                         "chase_pct": s["chase_pct"], "score": s["score"]})
    return pd.DataFrame(rows, columns=cols).sort_values("play_date").reset_index(drop=True)


def spray_points(plays: pd.DataFrame) -> pd.DataFrame:
    """Batted-ball landing points from horizontal_angle + distance_feet.
    x = dist*sin(angle) (neg=left field), y = dist*cos(angle). Batted balls only
    (hit_type 1/2/3). PROVISIONAL."""
    cols = ["x", "y", "hit_type_label"]
    if plays.empty or "horizontal_angle" not in plays.columns:
        return pd.DataFrame(columns=cols)
    d = plays[plays["hit_type"].isin([1, 2, 3])].dropna(
        subset=["horizontal_angle", "distance_feet"]).copy()
    if d.empty:
        return pd.DataFrame(columns=cols)
    ang = np.radians(d["horizontal_angle"].astype(float))
    d["x"] = d["distance_feet"].astype(float) * np.sin(ang)
    d["y"] = d["distance_feet"].astype(float) * np.cos(ang)
    d["hit_type_label"] = d["hit_type"].map(HIT_TYPE_MAP)
    return d[cols].reset_index(drop=True)


def hit_type_counts(plays: pd.DataFrame) -> pd.DataFrame:
    if plays.empty or "hit_type" not in plays.columns:
        return pd.DataFrame(columns=["Hit Type", "Count"])
    s = plays["hit_type"].map(HIT_TYPE_MAP).fillna("Other").value_counts()
    return pd.DataFrame({"Hit Type": s.index, "Count": s.values})
