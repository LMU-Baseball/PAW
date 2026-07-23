"""Framing tab: takes scatter + called-strike % by zone, shadow, and L/R."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import catching as C
from app.dashboards.catching import charts, tables
from app.dashboards.shell import CRIMSON, section


def _tile(label, value):
    return html.Div([
        html.Div(str(value), style={"fontSize": "28px", "fontWeight": "bold",
                                    "color": CRIMSON}),
        html.Div(label, style={"fontSize": "14px", "color": "#555"}),
    ], style={"textAlign": "center", "padding": "10px 14px",
              "backgroundColor": "rgba(255,255,255,0.85)", "borderRadius": "8px",
              "minWidth": "110px"})


def _fmt_pct(v):
    return "—" if v is None else f"{v}%"


def render(df: pd.DataFrame) -> html.Div:
    if df.empty:
        return html.Div("No pitch data.")
    overall = C.framing_overall(df)
    shadow = C.framing_shadow(df)
    tiles = html.Div([
        _tile("Takes", overall["takes"]),
        _tile("Called K", overall["called_strikes"]),
        _tile("CS%", _fmt_pct(overall["cs_pct"])),
        _tile("Shadow CS%", _fmt_pct(shadow["cs_pct"])),
        _tile("Shadow Takes", shadow["takes"]),
    ], style={"display": "flex", "gap": "10px", "flexWrap": "wrap",
              "marginBottom": "12px"})

    zone = C.framing_by_zone(df).copy()
    zone["CS%"] = zone["CS%"].apply(lambda v: "—" if v is None else v)
    splits = C.framing_by_batter_side(df).copy()
    splits["CS%"] = splits["CS%"].apply(lambda v: "—" if v is None else v)

    return html.Div([
        section("Framing — Called Strikes on Takes"),
        tiles,
        dcc.Graph(figure=charts.framing_scatter(df)),
        section("Called Strike % by Zone"),
        tables.df_table(zone, id_="framing-zone"),
        section("Called Strike % by Batter Side"),
        tables.df_table(splits, id_="framing-splits"),
        html.Div(
            "Provisional: no park/umpire adjustment. Takes = StrikeCalled + "
            "BallCalled/BallinDirt/BallIntentional/AutomaticBall. "
            "Shadow CS% is the primary framing signal.",
            style={"fontSize": "12px", "color": "#888", "marginTop": "8px"}),
    ])
