"""Static Framing tab: 4 faceted stolen/lost scatters (whole-game, unfiltered)."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.dashboards.catching import charts
from app.dashboards.shell import section

_FACETS = [
    ("batter_side", "Batter Side"),
    ("pitcher_throws", "Pitcher Side"),
    ("PitchSpeed", "Pitch Speed"),
    ("Zone", "Zone Location"),
]


def render(df: pd.DataFrame) -> html.Div:
    if df.empty:
        return html.Div("No pitch data.")
    graphs = []
    for by, title in _FACETS:
        graphs.append(section(title))
        graphs.append(dcc.Graph(figure=charts.framing_facets(df, by=by, title=title)))
    return html.Div(graphs)
