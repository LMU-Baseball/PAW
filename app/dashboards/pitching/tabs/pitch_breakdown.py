"""Pitch Breakdown tab: characteristics + usage + velo trend (inning / pitch count)."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import pitching as P
from app.dashboards.pitching import tables
from app.dashboards.shell import section

_CHAR_COLS = {
    "pitch": "Pitch", "count": "#", "usage_pct": "Usage%",
    "avg_velo": "Velo", "max_velo": "Max", "spin_rate": "Spin",
    "ivb": "IVB", "hb": "HB", "extension": "Ext",
}


def render(df: pd.DataFrame) -> html.Div:
    if df.empty:
        return html.Div("No pitch data.")
    char = P.pitch_characteristics(df)[list(_CHAR_COLS)].rename(columns=_CHAR_COLS)
    return html.Div([
        section("Pitch Characteristics"),
        tables.df_table(char, id_="pb-char"),
        section("Velocity Trend"),
        dcc.Tabs(id="pb-velo-tabs", value="inning", children=[
            dcc.Tab(label="By Inning", value="inning",
                    children=[dcc.Graph(figure=P.fig_velo_by_inning(df))]),
            dcc.Tab(label="By Pitch Count", value="pc",
                    children=[dcc.Graph(figure=P.fig_velo_by_pitch(df))]),
        ]),
    ])
