"""Contact Overview tab — team/player KPIs + hit mix + leaders."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import practice as P
from app.dashboards.hitting_practice import charts, tables
from app.dashboards.shell import CRIMSON, section


def _tile(label, value):
    return html.Div([
        html.Div(str(value), style={"fontSize": "28px", "fontWeight": "bold",
                                    "color": CRIMSON}),
        html.Div(label, style={"fontSize": "14px", "color": "#555"}),
    ], style={"textAlign": "center", "padding": "10px 14px",
              "backgroundColor": "rgba(255,255,255,0.85)", "borderRadius": "8px",
              "minWidth": "110px"})


def render(plays: pd.DataFrame, stats: pd.DataFrame, *, player: str) -> html.Div:
    if plays.empty and stats.empty:
        return html.Div("No practice data for these filters.",
                        style={"color": "#555", "padding": "12px"})

    n_plays = len(plays)
    n_sessions = int(plays["session_id"].nunique()) if not plays.empty and "session_id" in plays.columns else 0
    n_players = int(plays["player_name"].nunique()) if not plays.empty else 0
    if player and player != "All Players" and not stats.empty:
        stats = stats[stats["player_name"] == player]
    tiles = html.Div([
        _tile("Plays", n_plays),
        _tile("Sessions", n_sessions),
        _tile("Players", n_players if player == "All Players" else 1),
    ], style={"display": "flex", "gap": "10px", "flexWrap": "wrap",
              "marginBottom": "12px"})

    hit_counts = P.hit_type_counts(plays)
    top_vol = stats.sort_values("total_plays", ascending=False) if not stats.empty else stats
    top_ev = (stats.sort_values("avg_exit_velocity", ascending=False)
              if not stats.empty and "avg_exit_velocity" in stats.columns else stats)

    body = [
        section("Contact Overview"),
        tiles,
        dcc.Graph(figure=charts.hit_type_donut(hit_counts)),
        dcc.Graph(figure=charts.top_players_bar(top_vol, "total_plays",
                                                "Top Players by Plays")),
        dcc.Graph(figure=charts.top_players_bar(top_ev, "avg_exit_velocity",
                                                "Top Players by Avg EV")),
    ]
    if player and player != "All Players" and not stats.empty:
        row = stats.iloc[0]
        detail = pd.DataFrame([{
            "Player": row.get("player_name"),
            "Plays": row.get("total_plays"),
            "Sessions": row.get("total_sessions"),
            "Avg EV": row.get("avg_exit_velocity"),
            "Max EV": row.get("max_exit_velocity"),
            "Avg Dist": row.get("avg_distance"),
            "Hard Hit%": row.get("hard_hit_rate"),
        }])
        body += [section("Player Summary"), tables.df_table(detail, id_="co-player")]
    return html.Div(body)
