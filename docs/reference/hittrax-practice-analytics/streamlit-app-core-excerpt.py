"""Excerpt from BRADhaskell/lmu-baseball-practice-analytics dashboard/app.py
Captured 2026-07-23 for PAW hitting-practice port reference.
Contains: constants, loaders, PDF helpers start, trim_to_first_contact.
UI sidebar/tabs intentionally omitted (ported into app/dashboards/hitting_practice/).
"""
#!/usr/bin/env python3
"""
LMU Baseball Practice Analytics Dashboard
Streamlit prototype for stakeholder review — Sprint 2
"""

import base64
import datetime
import io
import os
import pathlib

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import create_engine

# ─────────────────────────────────────────
# Page Configuration
# ─────────────────────────────────────────
_logo_path = pathlib.Path(__file__).parent / "lmu_logo.png"
_page_icon = str(_logo_path) if _logo_path.exists() else "⚾"
_logo_b64 = base64.b64encode(_logo_path.read_bytes()).decode() if _logo_path.exists() else None
st.set_page_config(
    page_title="LMU Baseball Analytics",
    page_icon=_page_icon,
    layout="wide",
    initial_sidebar_state="expanded",
)

HIT_TYPE_MAP = {0: "Miss/Foul", 1: "Ground Ball", 2: "Line Drive", 3: "Fly Ball"}

# HitTrax session_type numeric codes → human-readable labels
SESSION_TYPE_MAP = {
    1:  "Hitting",
    4:  "Baseline",
    5:  "HitLab",
    7:  "Quality Hit Game",
    8:  "Unknown",
    11: "Game",
    12: "Entertainment",
    16: "Drill",
}

# Swing Decision drill date window (coach-confirmed: all sessions in this range)
SWING_DECISION_LABEL = "Swing Decision"
SWING_DECISION_START = pd.Timestamp("2026-03-31")
SWING_DECISION_END   = pd.Timestamp("2026-06-01")

LMU_BLUE = "#00447c"
LMU_CRIMSON = "#9b1b30"


# ─────────────────────────────────────────
# Database Connection
# ─────────────────────────────────────────
@st.cache_resource
def get_engine():
    # Streamlit Cloud: credentials come from st.secrets
    # Local dev: credentials come from .env file
    load_dotenv()
    try:
        host = st.secrets["MYSQL_HOST"]
        port = st.secrets.get("MYSQL_PORT", "3306")
        db = st.secrets["MYSQL_DB"]
        user = st.secrets["MYSQL_USER"]
        password = st.secrets["MYSQL_PASSWORD"]
    except (KeyError, FileNotFoundError):
        host = os.getenv("MYSQL_HOST")
        port = os.getenv("MYSQL_PORT", "3306")
        db = os.getenv("MYSQL_DB")
        user = os.getenv("MYSQL_USER")
        password = os.getenv("MYSQL_PASSWORD")
    return create_engine(
        f"mysql+pymysql://{user}:{password}@{host}:{port}/{db}",
        pool_pre_ping=True,
    )


def current_season_start() -> str:
    """Return the start date of the current baseball season as 'YYYY-08-01'.

    Seasons run August → May, so:
      - Aug–Dec: season started August of this year
      - Jan–Jul: season started August of last year
    """
    from datetime import date
    today = date.today()
    year = today.year if today.month >= 8 else today.year - 1
    return f"{year}-08-01"


@st.cache_data(ttl=3600)
def load_date_bounds() -> tuple:
    """Return (min_date, max_date) across all sessions for sidebar date picker bounds."""
    engine = get_engine()
    row = pd.read_sql(
        "SELECT MIN(session_date) AS min_d, MAX(session_date) AS max_d "
        "FROM practice_sessions WHERE session_date IS NOT NULL",
        engine,
    ).iloc[0]
    return row["min_d"], row["max_d"]


@st.cache_data(ttl=3600)
def load_player_stats(exclude_test: bool = True) -> pd.DataFrame:
    """Only include players active in the current season (Aug 1 of season-start year onward)."""
    engine = get_engine()
    season_start = current_season_start()
    where = f"WHERE player_id IS NOT NULL AND last_practice_date >= '{season_start}'"
    if exclude_test:
        where += " AND (player_name IS NULL OR player_name NOT LIKE '%%Test%%')"
    df = pd.read_sql(f"""
        SELECT
            player_id, player_name, total_plays, total_sessions,
            avg_exit_velocity, max_exit_velocity,
            avg_distance, max_distance,
            hard_hit_rate, fly_ball_rate, line_drive_rate,
            last_practice_date
        FROM player_stats_summary
        {where}
        ORDER BY total_plays DESC
    """, engine)
    numeric_cols = [
        "total_plays", "total_sessions",
        "avg_exit_velocity", "max_exit_velocity",
        "avg_distance", "max_distance",
        "hard_hit_rate", "fly_ball_rate", "line_drive_rate",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


@st.cache_data(ttl=3600)
def load_plays(exclude_test: bool = True) -> pd.DataFrame:
    engine = get_engine()
    where = "WHERE play_timestamp IS NOT NULL"
    if exclude_test:
        where += " AND (player_name IS NULL OR player_name NOT LIKE '%%Test%%')"
    return pd.read_sql(f"""
        SELECT
            player_name, player_id,
            DATE(play_timestamp) as play_date,
            exit_velocity, distance_feet,
            hit_type, launch_angle, session_id
        FROM practice_plays
        {where}
        ORDER BY play_timestamp
    """, engine)


@st.cache_data(ttl=3600)
def load_sessions(exclude_test: bool = True) -> pd.DataFrame:
    engine = get_engine()
    where = "WHERE session_date IS NOT NULL"
    if exclude_test:
        where += " AND (user_name IS NULL OR user_name NOT LIKE '%%Test%%')"
    return pd.read_sql(f"""
        SELECT
            session_id, session_date,
            user_name as player_name, player_id,
            avg_exit_velocity, max_exit_velocity,
            avg_distance, max_distance,
            total_plays, at_bats, hit_count, batting_avg,
            hard_hit_count, ground_ball_pct, fly_ball_pct, line_drive_pct
        FROM practice_sessions
        {where}
        ORDER BY session_date DESC
    """, engine)


@st.cache_data(ttl=3600)
def load_pitch_coords(exclude_test: bool = True) -> pd.DataFrame:
    """Load pitch location data for the swing decision heat map.

    Contact classification:
      - result = -4  → non-contact pitch (take or untracked swing-miss)
      - result = NULL → unclassified contact (all have EV > 0 in this dataset)
      - result in (-8,-3,0,1,2,3,4) → confirmed contact
    result = -5 (swing & miss) is absent from this dataset.
    """
    engine = get_engine()
    _sd_start = SWING_DECISION_START.strftime("%Y-%m-%d")
    where = (
        "WHERE pp.pitch_location_x IS NOT NULL AND pp.pitch_location_y IS NOT NULL"
        " AND pp.pitch_location_y BETWEEN 0.5 AND 5.5"
        " AND ABS(pp.pitch_location_x) < 3.0"
        f" AND DATE(pp.play_timestamp) >= '{_sd_start}'"
    )
    if exclude_test:
        where += " AND (pp.player_name IS NULL OR pp.player_name NOT LIKE '%%Test%%')"
    try:
        df = pd.read_sql(f"""
            SELECT
                pp.player_name, pp.player_id,
                pp.hand,
                pp.pitch_location_x  AS px,
                pp.pitch_location_y  AS py,
                pp.result,
                pp.exit_velocity,
                pp.distance_feet,
                pp.zone_section,
                pp.play_timestamp,
                pp.session_id,
                DATE(pp.play_timestamp) AS play_date,
                ps.session_type,
                ps.session_tag
            FROM practice_plays pp
            LEFT JOIN practice_sessions ps ON pp.session_id = ps.session_id
            {where}
            ORDER BY pp.play_timestamp
        """, engine)
        return df
    except Exception as e:
        st.error(f"Database error loading pitch data: {e}")
        return pd.DataFrame(columns=[
            "player_name", "player_id", "hand", "px", "py", "result",
            "exit_velocity", "distance_feet", "zone_section",
            "play_timestamp", "session_id", "play_date", "session_type", "session_tag",
        ])


def generate_pitch_zone_pdf(
    filt: pd.DataFrame,
    player_label: str,
    hand_label: str,
    date_label: str,
    session_label: str = "All session types",
    show_misses: bool = True,
) -> bytes:
    """Render all 3 pitch zone heat maps into a single landscape PDF page."""
    X_MIN, X_MAX = -2.0, 2.0
    Y_MIN, Y_MAX = 0.5, 5.0
    N_BINS = 20
    MIN_PITCHES = 1
    SZ_X1, SZ_X2, SZ_Y1, SZ_Y2 = -0.708, 0.708, 1.5, 3.5

    x_edges = np.linspace(X_MIN, X_MAX, N_BINS + 1)
    y_edges = np.linspace(Y_MIN, Y_MAX, N_BINS + 1)

    total_h, _, _ = np.histogram2d(filt["px"], filt["py"], bins=[x_edges, y_edges])

    # Contact histogram (used for both contact rate and the show_misses mask)
    contact_h, _, _ = np.histogram2d(
        filt.loc[filt["is_contact"], "px"],
        filt.loc[filt["is_contact"], "py"],
        bins=[x_edges, y_edges],
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        z_contact = np.where(total_h >= MIN_PITCHES, contact_h / total_h * 100, np.nan)

    # Avg exit velocity
    ev_filt = filt[filt["is_contact"] & filt["exit_velocity"].notna()]
    ev_sum_h, _, _ = np.histogram2d(
        ev_filt["px"], ev_filt["py"], bins=[x_edges, y_edges],
        weights=ev_filt["exit_velocity"],
    )
    ev_cnt_h, _, _ = np.histogram2d(ev_filt["px"], ev_filt["py"], bins=[x_edges, y_edges])
    with np.errstate(divide="ignore", invalid="ignore"):
        z_ev = np.where(ev_cnt_h >= MIN_PITCHES, ev_sum_h / ev_cnt_h, np.nan)

    # Pitch count
    z_count = np.where(total_h >= MIN_PITCHES, total_h, np.nan)

    # When Show Misses is off, hide zones with no contact (mirrors dashboard behaviour)
    if not show_misses:
        no_contact = contact_h == 0
        z_contact = np.where(no_contact, np.nan, z_contact)
        z_ev      = np.where(no_contact, np.nan, z_ev)
        z_count   = np.where(no_contact, np.nan, z_count)

    panels = [
        ("Contact Rate (%)",        z_contact, "RdYlBu_r", 0,    100,  "Contact %"),
        ("Avg Exit Velocity (mph)", z_ev,      "RdYlBu_r", 50,   105,  "mph"),
        ("Pitch Count",             z_count,   "Blues",    None, None, "Pitches"),
    ]

    fig, axes = plt.subplots(1, 3, figsize=(18, 7))

    # Report header
    header_lines = [
        f"LMU Baseball — Pitch Zone Report",
        f"Player: {player_label}   |   Handedness: {hand_label}   |   Session type: {session_label}",
        f"Date range: {date_label}   |   Generated: {datetime.date.today().strftime('%B %d, %Y')}",
    ]
    fig.suptitle("\n".join(header_lines), fontsize=11, fontweight="bold",
                 x=0.5, y=1.04, ha="center", va="bottom")

    for ax, (title, z_mat, cmap, vmin, vmax, cbar_label) in zip(axes, panels):
        im = ax.pcolormesh(
            x_edges, y_edges, z_mat.T,
            cmap=cmap, vmin=vmin, vmax=vmax, shading="flat",
        )
        plt.colorbar(im, ax=ax, label=cbar_label, fraction=0.046, pad=0.04)

        # Strike zone rectangle
        ax.add_patch(mpatches.Rectangle(
            (SZ_X1, SZ_Y1), SZ_X2 - SZ_X1, SZ_Y2 - SZ_Y1,
            linewidth=2, edgecolor="black", facecolor="none",
        ))
        # Home plate marker
        ax.add_patch(mpatches.Rectangle(
            (-0.708, 0.0), 1.416, 0.15,
            linewidth=1, edgecolor="gray", facecolor="lightgray", alpha=0.5,
        ))

        ax.set_xlim(X_MIN, X_MAX)
        ax.set_ylim(0.0, Y_MAX)
        ax.set_aspect("equal")
        ax.set_title(title, fontsize=12, fontweight="bold", pad=8)
        ax.set_xlabel("Horizontal Position (ft)\n← Inside to RHB    Outside to RHB →", fontsize=8)
        ax.set_ylabel("Height above plate (ft)", fontsize=8)
        ax.axvline(0, color="gray", linewidth=0.5, alpha=0.4)
        ax.tick_params(labelsize=8)

    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="pdf", bbox_inches="tight", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def generate_swing_frequency_pdf(
    contact_scatter: pd.DataFrame,
    zone_compare: pd.DataFrame,
    player_label: str,
    zone_label: str,
    hand_label: str,
    date_label: str,
    kpis: dict | None = None,
    sd_trend: pd.DataFrame | None = None,
) -> bytes:
    """Render Swing Frequency charts (dual-axis line + zone bar) into a PDF."""
    fig, (ax_line, ax_trend, ax_bar) = plt.subplots(3, 1, figsize=(14, 20))
    fig.subplots_adjust(hspace=0.55, top=0.76, bottom=0.05)

    header = "\n".join([
        "LMU Baseball — Swing Frequency Report",
        f"Player: {player_label}   |   Zone: {zone_label}   |   Handedness: {hand_label}",
        f"Date range: {date_label}   |   Generated: {datetime.date.today().strftime('%B %d, %Y')}",
    ])
    fig.suptitle(header, fontsize=11, fontweight="bold", x=0.5, y=0.98, ha="center", va="top")

    # ── KPI summary bar ──────────────────────────────────────────────────────
    if kpis:
        kpi_line1 = (
            f"Total Pitches: {kpis.get('total_pitches', '—')}   |   "
            f"Contacts: {kpis.get('total_contacts', '—')}   |   "
            f"Contact Rate: {kpis.get('contact_rate', '—')}%   |   "
            f"Avg Exit Velocity: {kpis.get('avg_ev', '—')} mph"
        )
        kpi_line2 = (
            f"In-Zone Contact Rate (Zones 1–9): {kpis.get('iz_rate', '—')}%   |   "
            f"Chase Contact Rate (Zones 10–13): {kpis.get('ch_rate', '—')}%   |   "
            f"Swing Decision Score: {kpis.get('swing_dec_score', '—'):+.1f}%"
            if isinstance(kpis.get('swing_dec_score'), (int, float))
            else f"In-Zone Contact Rate (Zones 1–9): {kpis.get('iz_rate', '—')}%   |   "
                 f"Chase Contact Rate (Zones 10–13): {kpis.get('ch_rate', '—')}%   |   "
                 f"Swing Decision Score: —"
        )
        fig.text(
            0.5, 0.885, kpi_line1,
            ha="center", va="center", fontsize=9,
            bbox=dict(boxstyle="round,pad=0.4", facecolor="#e8eef4", edgecolor="#00447c", linewidth=1),
        )
        fig.text(
            0.5, 0.855, kpi_line2,
            ha="center", va="center", fontsize=9, fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="#f0e8ea", edgecolor="#9b1b30", linewidth=1),
        )

    # ── Dual-axis line chart: EV (left) + Distance (right) by pitch # ────────
    ax_dist_twin = ax_line.twinx()

    ev_data   = contact_scatter[contact_scatter["exit_velocity"].notna()].sort_values("pitch_num")
    dist_data = contact_scatter[contact_scatter["distance_feet"].notna()].sort_values("pitch_num")

    lines = []
    if len(ev_data) > 0:
        l1, = ax_line.plot(
            ev_data["pitch_num"], ev_data["exit_velocity"],
            marker="o", color=LMU_CRIMSON, linewidth=2, label="Exit Velocity (mph)",
        )
        lines.append(l1)
        for _, row in ev_data.iterrows():
            ax_line.annotate(
                f"{row['exit_velocity']:.0f}",
                (row["pitch_num"], row["exit_velocity"]),
                textcoords="offset points", xytext=(0, 6), fontsize=7, ha="center", color=LMU_CRIMSON,
            )

    if len(dist_data) > 0:
        l2, = ax_dist_twin.plot(
            dist_data["pitch_num"], dist_data["distance_feet"],
            marker="o", color=LMU_BLUE, linewidth=2, label="Distance (ft)",
        )
        lines.append(l2)
        for _, row in dist_data.iterrows():
            ax_dist_twin.annotate(
                f"{row['distance_feet']:.0f}",
                (row["pitch_num"], row["distance_feet"]),
                textcoords="offset points", xytext=(0, -12), fontsize=7, ha="center", color=LMU_BLUE,
            )

    ax_line.set_title(f"Exit Velocity & Distance by Pitch # ({zone_label})", fontsize=11, fontweight="bold")
    ax_line.set_xlabel("Pitch #", fontsize=9)
    ax_line.set_ylabel("Exit Velocity (mph)", fontsize=9, color=LMU_CRIMSON)
    ax_dist_twin.set_ylabel("Distance (ft)", fontsize=9, color=LMU_BLUE)
    ax_line.tick_params(axis="y", labelsize=8, colors=LMU_CRIMSON)
    ax_dist_twin.tick_params(axis="y", labelsize=8, colors=LMU_BLUE)
    ax_line.tick_params(axis="x", labelsize=8)
    ax_line.grid(True, alpha=0.3)
    if lines:
        ax_line.legend(lines, [l.get_label() for l in lines], fontsize=8, loc="upper left")

    # ── Swing Decision Score trend line ──────────────────────────────────────
    if sd_trend is not None and len(sd_trend) > 0:
        colors = [LMU_BLUE if s >= 0 else LMU_CRIMSON for s in sd_trend["score"]]
        ax_trend.plot(sd_trend["date_str"], sd_trend["score"], color=LMU_BLUE, linewidth=2, zorder=1)
        ax_trend.scatter(sd_trend["date_str"], sd_trend["score"], color=colors, s=60, zorder=2)
        ax_trend.axhline(0, color="gray", linewidth=1, linestyle="--", alpha=0.6)
        for _, row in sd_trend.iterrows():
            ax_trend.annotate(
                f"{row['score']:+.1f}%",
                (row["date_str"], row["score"]),
                textcoords="offset points", xytext=(0, 8), fontsize=7, ha="center",
                color=LMU_BLUE if row["score"] >= 0 else LMU_CRIMSON,
            )
        ax_trend.set_title("Swing Decision Score by Session (In-Zone % − Chase %)", fontsize=11, fontweight="bold")
        ax_trend.set_xlabel("Session Date", fontsize=9)
        ax_trend.set_ylabel("Score (%)", fontsize=9)
        ax_trend.tick_params(axis="x", labelsize=7, rotation=30)
        ax_trend.tick_params(axis="y", labelsize=8)
        ax_trend.grid(True, alpha=0.3, axis="y")
    else:
        ax_trend.set_visible(False)

    # ── Zone contact rate bar chart with "X of Y" labels ─────────────────────
    if len(zone_compare) > 0:
        bars = ax_bar.bar(
            zone_compare["zone_label"], zone_compare["contact_pct"],
            color=LMU_BLUE, alpha=0.85,
        )
        _max_pct = zone_compare["contact_pct"].max()
        for bar, (_, row) in zip(bars, zone_compare.iterrows()):
            ax_bar.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 1.5,
                f"{int(row['contacts'])} of {int(row['total'])}",
                ha="center", va="bottom", fontsize=8,
            )
        ax_bar.set_ylim(0, max(_max_pct * 1.25, 110))
    ax_bar.set_title("Contact Rate by Zone (all sessions in date range)", fontsize=11, fontweight="bold")
    ax_bar.set_xlabel("Zone", fontsize=9)
    ax_bar.set_ylabel("Contact Rate (%)", fontsize=9)
    ax_bar.tick_params(labelsize=8)
    ax_bar.grid(True, alpha=0.3, axis="y")

    buf = io.BytesIO()
    fig.savefig(buf, format="pdf", bbox_inches="tight", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def trim_to_first_contact(df: pd.DataFrame) -> pd.DataFrame:
    """Drop warm-up pitches before a player's first contact in each session.

    For each player+session group, discard every pitch that came before the
    first batted ball (result != -4).  Pitches where result IS NULL are also
    treated as contact because they all carry exit_velocity > 0 in this dataset.
    """
    if df.empty:
        return df

    df = df.sort_values(["player_name", "session_id", "play_timestamp"]).copy()
    df["_is_contact"] = df["result"] != -4
    df["_cumsum"] = df.groupby(["player_name", "session_id"])["_is_contact"].cumsum()
    return df[df["_cumsum"] >= 1].drop(columns=["_is_contact", "_cumsum"])


