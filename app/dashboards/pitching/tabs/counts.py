"""Counts tab: count-state multiselect -> pitch usage table + location scatter."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import pitching as P
from app.dashboards.pitching import tables
from app.dashboards.shell import section


def count_options(df: pd.DataFrame) -> list[dict]:
    return [{"label": c, "value": c} for c in P.count_states(df)]


def _usage_display(df: pd.DataFrame) -> pd.DataFrame:
    return P.pitch_usage(df).rename(
        columns={"pitch": "Pitch", "count": "Count", "usage_pct": "Usage %"})


def body(df: pd.DataFrame) -> html.Div:
    if df is None or df.empty:
        return html.Div("No pitches for the selected counts.",
                        style={"padding": "12px", "color": "#555"})
    return html.Div([
        html.Div([section("Pitch Usage"),
                  tables.df_table(_usage_display(df), id_="counts-usage", color_col="Pitch")],
                 style={"flex": "1"}),
        html.Div([section("Location"), dcc.Graph(figure=P.fig_location(df))],
                 style={"flex": "1"}),
    ], style={"display": "flex", "gap": "16px"})


def render(df: pd.DataFrame) -> html.Div:
    opts = count_options(df)
    return html.Div([
        dcc.Dropdown(id="counts-dd", options=opts, value=[o["value"] for o in opts],
                     multi=True, placeholder="Count state(s)",
                     style={"maxWidth": "460px", "margin": "6px 0"}),
        html.Div(id="counts-body", children=body(df)),
    ])
