"""Static Framing tab: call-type chips + 4 faceted stolen/lost scatters."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import catching as C
from app.dashboards.catching import charts
from app.dashboards.shell import section

_FACETS = [
    ("batter_side", "Batter Side"),
    ("pitcher_throws", "Pitcher Side"),
    ("PitchSpeed", "Pitch Speed"),
    ("Zone", "Zone Location"),
]
_CALL_ORDER = ["Stolen Strike", "Lost Strike", "Correct Call"]


def call_chip_row() -> html.Div:
    chips = [html.Button(
        ct, id={"type": "static-call-chip", "index": ct}, n_clicks=0,
        style={"border": f"2px solid {charts.CALLTYPE_COLORS[ct]}",
               "background": charts.CALLTYPE_COLORS[ct], "color": "#fff",
               "borderRadius": "14px", "padding": "3px 12px",
               "margin": "0 6px 6px 0", "cursor": "pointer",
               "fontFamily": "Teko, sans-serif", "fontSize": "15px"})
        for ct in _CALL_ORDER]
    return html.Div([dcc.Store(id="static-call-active", data=list(_CALL_ORDER)),
                     html.Div(chips)], style={"margin": "6px 0"})


def body(df: pd.DataFrame, active_calls=None) -> html.Div:
    if df.empty:
        return html.Div("No pitch data.")
    f = C.add_framing_cols(df)
    if active_calls is not None:
        f = f[f["CallType"].isin(active_calls)]
    graphs = []
    for by, title in _FACETS:
        graphs.append(section(title))
        graphs.append(dcc.Graph(figure=charts.framing_facets(f, by=by, title=title)))
    return html.Div(graphs)


def render(df: pd.DataFrame) -> html.Div:
    if df.empty:
        return html.Div("No pitch data.")
    return html.Div([call_chip_row(),
                     html.Div(id="static-body", children=body(df))])
