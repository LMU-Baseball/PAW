# app/dashboards/hitting/tabs/balls_in_play.py
"""Balls in Play tab: hit-type chip filter -> launch-angle radial + spray chart."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.dashboards.hitting import charts


def _chip_style(color: str, on: bool) -> dict:
    return {"border": f"2px solid {color}", "background": color if on else "#fff",
            "color": "#fff" if on else color, "borderRadius": "14px",
            "padding": "3px 12px", "margin": "0 6px 6px 0", "cursor": "pointer",
            "opacity": "1" if on else ".55", "fontFamily": "Teko, sans-serif",
            "fontSize": "15px"}


def chip_row(bip_df: pd.DataFrame) -> html.Div:
    types = list(pd.unique(bip_df["hit_type"])) if bip_df is not None and not bip_df.empty else []
    chips = [html.Button(str(ht), id={"type": "bip-chip", "index": str(ht)}, n_clicks=0,
                         style=_chip_style(charts._HIT_COLORS.get(str(ht), "#888"), True))
             for ht in types]
    return html.Div([dcc.Store(id="bip-active", data=[str(t) for t in types]),
                     html.Div(chips)], style={"margin": "6px 0"})


def body(bip_df: pd.DataFrame) -> html.Div:
    if bip_df is None or bip_df.empty:
        return html.Div("No balls in play for this selection.",
                        style={"padding": "12px", "color": "#555"})
    return html.Div([
        html.Div(dcc.Graph(figure=charts.radial_fig(bip_df)), style={"flex": "1"}),
        html.Div(dcc.Graph(figure=charts.spray_fig(bip_df)), style={"flex": "1"}),
    ], className="paw-chart-row", style={"display": "flex", "gap": "16px"})


def render(bip_df: pd.DataFrame) -> html.Div:
    return html.Div([chip_row(bip_df), html.Div(id="bip-body", children=body(bip_df))])
