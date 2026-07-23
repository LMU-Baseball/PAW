"""Pitch Zones tab — catcher's-view contact heatmap + zone table."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import practice as P
from app.dashboards.hitting_practice import charts, tables
from app.dashboards.shell import CRIMSON, section


def _tile(label, value):
    return html.Div([
        html.Div(str(value), style={"fontSize": "28px", "fontWeight": "bold",
                                    "color": CRIMSON}),
        html.Div(label, style={"fontSize": "14px", "color": "#555"}),
    ], style={"textAlign": "center", "padding": "10px 14px",
              "backgroundColor": "rgba(255,255,255,0.85)", "borderRadius": "8px",
              "minWidth": "110px"})


def _fmt(v, suffix="%"):
    return "—" if v is None else f"{v}{suffix}"


def render(df: pd.DataFrame) -> html.Div:
    if df.empty:
        return html.Div("No pitch-location data for these filters. "
                        "Try a wider date range or another player.",
                        style={"color": "#555", "padding": "12px"})
    d = P.trim_to_first_contact(df)
    summ = P.contact_summary(d)
    zone = P.zone_contact_table(d)
    tiles = html.Div([
        _tile("Pitches", summ["pitches"]),
        _tile("Contact%", _fmt(summ["contact_pct"])),
        _tile("In-Zone", summ["in_zone"]),
        _tile("In-Zone Contact%", _fmt(summ["in_zone_contact_pct"])),
    ], style={"display": "flex", "gap": "10px", "flexWrap": "wrap",
              "marginBottom": "12px"})
    return html.Div([
        section("Pitch Zones"),
        tiles,
        dcc.Graph(figure=charts.pitch_zone_heatmap(d)),
        section("Zone Summary"),
        tables.df_table(zone, id_="pz-zone-table"),
        html.Div(
            "HitTrax does not separate swing-miss from takes; non-contact "
            "(result = -4) includes both. Warm-up pitches before first contact "
            "are trimmed per session.",
            style={"fontSize": "12px", "color": "#888", "marginTop": "8px"}),
    ])
