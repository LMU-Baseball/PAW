# app/dashboards/hitting/tabs/last_27.py
"""Last 27 PA tab: recent-PA batting/batted-ball/swing tables + BIP spray."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import hitting
from app.dashboards.hitting import charts, tables

_H = {"color": "#9A0021", "margin": "16px 0 6px"}


def render(last_df: pd.DataFrame, bip_df: pd.DataFrame) -> html.Div:
    if last_df is None or last_df.empty:
        return html.Div("No recent plate appearances.",
                        style={"padding": "12px", "color": "#555"})
    line_df = pd.DataFrame([hitting.game_batting_line(last_df)])
    _drop = ["Avg QC+", "Avg PathQ+"]
    bb = hitting.batted_ball_profile(last_df).drop(columns=_drop, errors="ignore")
    sd = hitting.swing_decisions_by_zone(last_df)
    return html.Div([
        html.H3("Last 27 PA — Batting Line", style=_H),
        tables.stat_table(line_df, id="l27-line"),
        html.H3("Batted Ball Profile", style=_H),
        tables.stat_table(bb, id="l27-bb"),
        html.H3("Swing Decisions by Zone", style=_H),
        tables.stat_table(sd, id="l27-sd"),
        html.H3("Balls in Play — Spray", style=_H),
        dcc.Graph(figure=charts.spray_fig(bip_df)),
    ], style={"padding": "10px 4px"})
