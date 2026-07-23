"""Framing tab: takes scatter + called-strike % by attack zone."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import catching as C
from app.dashboards.catching import charts, tables
from app.dashboards.shell import section


def render(df: pd.DataFrame) -> html.Div:
    if df.empty:
        return html.Div("No pitch data.")
    overall = C.framing_overall(df)
    cs = overall["cs_pct"]
    headline = (
        f"{overall['called_strikes']} / {overall['takes']} takes called strikes"
        + (f" ({cs}%)" if cs is not None else "")
    )
    zone = C.framing_by_zone(df)
    # Display-friendly nulls
    zone = zone.copy()
    zone["CS%"] = zone["CS%"].apply(lambda v: "—" if v is None else v)
    return html.Div([
        section("Framing — Called Strikes on Takes"),
        html.Div(headline, style={"fontSize": "18px", "marginBottom": "8px"}),
        dcc.Graph(figure=charts.framing_scatter(df)),
        section("Called Strike % by Zone"),
        tables.df_table(zone, id_="framing-zone"),
        html.Div("Provisional: no park/umpire adjustment. Zones = Heart/Shadow/Chase/Waste.",
                 style={"fontSize": "12px", "color": "#888", "marginTop": "8px"}),
    ])
