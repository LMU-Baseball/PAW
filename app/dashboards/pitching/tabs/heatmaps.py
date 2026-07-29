"""Heatmaps tab: pitch-type / batter-side / count filters -> density heatmap."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import pitching as P


def body(df: pd.DataFrame) -> html.Div:
    return html.Div(dcc.Graph(figure=P.fig_heatmap(df)))


def render(df: pd.DataFrame) -> html.Div:
    pts = list(P.pitch_type(df).dropna().unique()) if df is not None and not df.empty else []
    counts = P.count_states(df) if df is not None else []
    return html.Div([
        html.Div([
            dcc.Dropdown(id="hm-pt", options=[{"label": p, "value": p} for p in pts],
                         value=pts, multi=True, placeholder="Pitch type(s)",
                         style={"minWidth": "220px"}),
            dcc.RadioItems(id="hm-side", inline=True, value="All",
                           options=[{"label": "All", "value": "All"},
                                    {"label": "vs RHH", "value": "Right"},
                                    {"label": "vs LHH", "value": "Left"}],
                           style={"display": "inline-flex", "gap": "10px",
                                  "alignItems": "center", "minWidth": "220px"}),
            dcc.Dropdown(id="hm-count", options=[{"label": c, "value": c} for c in counts],
                         value=counts, multi=True, placeholder="Count(s)",
                         style={"minWidth": "220px"}),
        ], style={"display": "flex", "gap": "12px", "margin": "6px 0",
                  "flexWrap": "wrap"}),
        html.Div(id="hm-body", children=body(df)),
    ])
