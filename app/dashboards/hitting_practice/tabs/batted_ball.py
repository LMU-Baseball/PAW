"""Batted Ball tab — spray chart + contact-type distribution."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import practice as P
from app.dashboards.hitting_practice import charts
from app.dashboards.shell import section


def render(plays: pd.DataFrame) -> html.Div:
    if plays is None or plays.empty:
        return html.Div("No batted-ball data for these filters.",
                        style={"color": "#555", "padding": "12px"})
    spray = P.spray_points(plays)
    counts = P.hit_type_counts(plays)
    return html.Div([
        section("Spray Chart"),
        dcc.Graph(figure=charts.spray_chart_fig(spray)),
        section("Contact Type"),
        dcc.Graph(figure=charts.contact_type_bar(counts)),
    ])
