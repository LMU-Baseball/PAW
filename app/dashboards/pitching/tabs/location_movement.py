"""Location / Movement tab: pitch-type chip filter -> movement + location + table."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import pitching as P
from app.dashboards.pitching import tables
from app.dashboards.shell import section


def chip_row(df: pd.DataFrame, prefix: str) -> html.Div:
    """A clickable color chip per pitch type present (all active by default)."""
    types = list(P.pitch_type(df).value_counts().index)
    chips = [html.Button(
        pt, id={"type": f"{prefix}-chip", "index": pt}, n_clicks=0,
        style={"border": f"2px solid {P.pitch_color(pt)}", "background": P.pitch_color(pt),
               "color": "#fff", "borderRadius": "14px", "padding": "3px 12px",
               "margin": "0 6px 6px 0", "cursor": "pointer",
               "fontFamily": "Teko, sans-serif", "fontSize": "15px"})
        for pt in types]
    return html.Div([dcc.Store(id=f"{prefix}-active", data=types),
                     html.Div(chips)], style={"margin": "6px 0"})


def all_pitches(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "Pitch": P.pitch_type(df),
        "Count": df["balls"].astype("Int64").astype(str) + "-"
                 + df["strikes"].astype("Int64").astype(str),
        "Velo": df["rel_speed"].round(1),
        "Result": df["pitch_call"].map(P.pretty_result),
    }).reset_index(drop=True)


def body(df: pd.DataFrame) -> html.Div:
    if df.empty:
        return html.Div("No pitches for the selected pitch types.")
    return html.Div([
        html.Div([
            html.Div([section("Movement"), dcc.Graph(figure=P.fig_movement(df))],
                     style={"flex": "1"}),
            html.Div([section("Location"), dcc.Graph(figure=P.fig_location(df))],
                     style={"flex": "1"}),
        ], style={"display": "flex", "gap": "16px"}),
        section("All Pitches"),
        tables.df_table(all_pitches(df), id_="lm-all"),
    ])


def render(df: pd.DataFrame) -> html.Div:
    if df.empty:
        return html.Div("No pitch data.")
    return html.Div([chip_row(df, "lm"),
                     html.Div(id="lm-body", children=body(df))])
