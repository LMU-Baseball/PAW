"""Session Tables tab — player summary + session log."""
from __future__ import annotations

import pandas as pd
from dash import html

from app.dashboards.hitting_practice import tables
from app.dashboards.shell import section


def render(stats: pd.DataFrame, sessions: pd.DataFrame, *, player: str) -> html.Div:
    st = stats.copy()
    sess = sessions.copy()
    if player and player != "All Players":
        if not st.empty:
            st = st[st["player_name"] == player]
        if not sess.empty:
            sess = sess[sess["player_name"] == player]

    if st.empty and sess.empty:
        return html.Div("No session tables for these filters.",
                        style={"color": "#555", "padding": "12px"})

    player_tbl = pd.DataFrame()
    if not st.empty:
        cols = [c for c in (
            "player_name", "total_sessions", "total_plays",
            "avg_exit_velocity", "max_exit_velocity", "avg_distance",
            "hard_hit_rate", "line_drive_rate", "fly_ball_rate", "last_practice_date",
        ) if c in st.columns]
        player_tbl = st[cols].rename(columns={
            "player_name": "Player", "total_sessions": "Sessions",
            "total_plays": "Plays", "avg_exit_velocity": "Avg EV",
            "max_exit_velocity": "Max EV", "avg_distance": "Avg Dist",
            "hard_hit_rate": "Hard Hit%", "line_drive_rate": "LD%",
            "fly_ball_rate": "FB%", "last_practice_date": "Last Practice",
        })

    sess_tbl = pd.DataFrame()
    if not sess.empty:
        cols = [c for c in (
            "session_date", "player_name", "total_plays",
            "avg_exit_velocity", "max_exit_velocity", "avg_distance",
            "batting_avg", "hard_hit_count", "ground_ball_pct",
            "line_drive_pct", "fly_ball_pct",
        ) if c in sess.columns]
        sess_tbl = sess[cols].rename(columns={
            "session_date": "Date", "player_name": "Player",
            "total_plays": "Plays", "avg_exit_velocity": "Avg EV",
            "max_exit_velocity": "Max EV", "avg_distance": "Avg Dist",
            "batting_avg": "AVG", "hard_hit_count": "Hard Hits",
            "ground_ball_pct": "GB%", "line_drive_pct": "LD%",
            "fly_ball_pct": "FB%",
        })

    return html.Div([
        section("Player Summary"),
        tables.df_table(player_tbl, id_="st-players") if not player_tbl.empty
        else html.Div("No player summary rows."),
        section("Session Log"),
        tables.df_table(sess_tbl, id_="st-sessions") if not sess_tbl.empty
        else html.Div("No session log rows."),
    ])
