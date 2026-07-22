"""Location / Movement tab: movement map + location scatter + all-pitches table."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import pitching as P
from app.dashboards.pitching import tables
from app.dashboards.shell import section


def _all_pitches(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame({
        "Pitch": P.pitch_type(df),
        "Count": df["balls"].astype("Int64").astype(str) + "-"
                 + df["strikes"].astype("Int64").astype(str),
        "Velo": df["rel_speed"].round(1),
        "IVB": df["induced_vert_break"].round(1),
        "HB": df["horz_break"].round(1),
        "Result": df["pitch_call"],
    })
    return out.reset_index(drop=True)


def render(df: pd.DataFrame) -> html.Div:
    if df.empty:
        return html.Div("No pitch data.")
    return html.Div([
        html.Div([
            html.Div([section("Movement"), dcc.Graph(figure=P.fig_movement(df))],
                     style={"flex": "1"}),
            html.Div([section("Location"), dcc.Graph(figure=P.fig_location(df))],
                     style={"flex": "1"}),
        ], style={"display": "flex", "gap": "16px"}),
        section("All Pitches"),
        tables.df_table(_all_pitches(df), id_="lm-all"),
    ])
