"""Swing Frequency tab — swing-decision trend + zone-filterable EV/distance."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import practice as P
from app.dashboards.hitting_practice import charts
from app.dashboards.shell import section

_ZONES = list(range(1, 14))  # 1-13


def zone_chip_row(df: pd.DataFrame) -> html.Div:
    present = sorted(int(z) for z in df["zone_section"].dropna().unique()) \
        if not df.empty and "zone_section" in df.columns else _ZONES
    chips = [html.Button(
        f"Z{z}", id={"type": "sfz-chip", "index": z}, n_clicks=0,
        style={"border": "2px solid #9A0021", "background": "#9A0021", "color": "#fff",
               "borderRadius": "12px", "padding": "2px 10px", "margin": "0 4px 4px 0",
               "cursor": "pointer", "fontFamily": "Teko, sans-serif", "fontSize": "14px"})
        for z in present]
    return html.Div([dcc.Store(id="sfz-active", data=present), html.Div(chips)],
                    style={"margin": "6px 0"})


def ev_body(df: pd.DataFrame, active_zones) -> html.Div:
    d = df
    if active_zones is not None and not df.empty and "zone_section" in df.columns:
        d = df[df["zone_section"].isin(active_zones)]
    return html.Div(dcc.Graph(figure=charts.ev_distance_by_pitch(d)))


def render(df: pd.DataFrame) -> html.Div:
    if df.empty:
        return html.Div("No pitch data for these filters.",
                        style={"color": "#555", "padding": "12px"})
    d = P.trim_to_first_contact(df)
    trend = P.swing_decision_trend(d)
    return html.Div([
        section("Swing Decision Score Trend"),
        dcc.Graph(figure=charts.swing_decision_trend_fig(trend)),
        section("Exit Velo & Distance by Pitch"),
        zone_chip_row(d),
        html.Div(id="sf-ev-body", children=ev_body(d, None)),
    ])
