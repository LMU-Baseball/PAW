"""Overall Framing tab: 4 legacy filters + stolen/lost scatter + summary table."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import catching as C
from app.dashboards.catching import charts, tables
from app.dashboards.shell import section

FILTER_DEFS = [
    ("fr-bat", "Batter Hand", ["All", "Left", "Right"]),
    ("fr-throws", "Pitcher Hand", ["All", "Left", "Right"]),
    ("fr-speed", "Pitch Speed", ["All", "Fastball", "Offspeed"]),
    ("fr-zone", "Zone Location", ["All", "Heart", "Shadow", "Chase", "Waste"]),
]

_TABLE_LABELS = {
    "net_strikes": "Net Strikes", "steal_pct": "Steal%",
    "shadow_net": "Shadow Net", "shadow_steal_pct": "Shadow Steal%",
    "heart_net": "Heart Net", "heart_loss_pct": "Heart LOSS%",
    "waste_net": "Waste Net", "waste_steal_pct": "Waste Steal%",
}


def _fmt(key, val):
    if val is None:
        return "—"
    return f"{val}%" if key.endswith("_pct") else str(val)


def body(df: pd.DataFrame, *, bat_side="All", pitcher_throws="All",
         pitch_speed="All", zone="All") -> html.Div:
    if df.empty:
        return html.Div("No pitch data.")
    f = C.add_framing_cols(df)
    f = C.apply_framing_filters(f, bat_side=bat_side, pitcher_throws=pitcher_throws,
                                pitch_speed=pitch_speed, zone=zone)
    summ = C.framing_table(f)
    table_df = pd.DataFrame([{_TABLE_LABELS[k]: _fmt(k, summ[k]) for k in _TABLE_LABELS}])
    return html.Div([
        dcc.Graph(figure=charts.framing_scatter(f)),
        section("Framing Summary"),
        tables.df_table(table_df, id_="fr-summary"),
    ])


def render(df: pd.DataFrame) -> html.Div:
    filters = []
    for fid, label, opts in FILTER_DEFS:
        filters.append(html.Div([
            html.Label(label, style={"fontWeight": "bold", "fontSize": "14px"}),
            dcc.Dropdown(id=fid, options=[{"label": o, "value": o} for o in opts],
                         value="All", clearable=False, style={"width": "150px"}),
        ]))
    return html.Div([
        section("Overall Framing"),
        html.Div(filters, style={"display": "flex", "gap": "12px",
                                 "flexWrap": "wrap", "marginBottom": "10px"}),
        html.Div(id="fr-body", children=body(df)),
        html.Div("Provisional stolen/lost model (in-zone from plate geometry; "
                 "legacy 'Steal%' = lost/total). Coach-confirmable.",
                 style={"fontSize": "12px", "color": "#888", "marginTop": "8px"}),
    ])
