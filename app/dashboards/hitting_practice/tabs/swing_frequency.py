"""Swing Frequency tab — swing-decision trend + zone-filterable EV/distance."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import practice as P
from app.dashboards.hitting_practice import charts
from app.dashboards.shell import section

_ZONES = list(range(1, 14))  # 1-13


def chip_style(active: bool, present: bool) -> dict:
    if not present:                       # zone has no data -> greyed, disabled
        bg, fg, border, cursor, opacity = "#e6e6e6", "#999", "#ccc", "default", "0.6"
    elif active:                          # present + selected
        bg, fg, border, cursor, opacity = "#9A0021", "#fff", "#9A0021", "pointer", "1"
    else:                                 # present + deselected
        bg, fg, border, cursor, opacity = "#fff", "#9A0021", "#9A0021", "pointer", "0.55"
    return {"border": f"2px solid {border}", "background": bg, "color": fg,
            "borderRadius": "12px", "padding": "2px 10px", "margin": "0 4px 4px 0",
            "cursor": cursor, "opacity": opacity,
            "fontFamily": "Teko, sans-serif", "fontSize": "14px"}


def zone_chip_row(df: pd.DataFrame) -> html.Div:
    present = {int(z) for z in df["zone_section"].dropna().unique()} \
        if not df.empty and "zone_section" in df.columns else set(_ZONES)
    chips = [html.Button(
        f"Zone {z}", id={"type": "sfz-chip", "index": z}, n_clicks=0,
        disabled=z not in present, style=chip_style(active=z in present, present=z in present))
        for z in _ZONES]
    active0 = sorted(present)
    return html.Div([dcc.Store(id="sfz-active", data=active0),
                     dcc.Store(id="sfz-present", data=active0),
                     html.Div(chips)], style={"margin": "6px 0"})


def ev_body(df: pd.DataFrame, active_zones) -> html.Div:
    d = df
    if active_zones is not None and not df.empty and "zone_section" in df.columns:
        d = df[df["zone_section"].isin(active_zones)]
    return html.Div(dcc.Graph(figure=charts.ev_distance_by_pitch(d)))


def sds_zone_chip_row(df: pd.DataFrame) -> html.Div:
    """Zone chips that define the in-zone set for the Swing Decision Score.
    Defaults to zones 1-9 selected; deselected zones count as chases. All 13
    zones are selectable regardless of whether pitches exist there -- an
    empty selected zone simply contributes nothing to the score. Separate
    from the sfz EV/distance chips above."""
    default_active = list(range(1, 10))
    chips = [html.Button(
        f"Zone {z}", id={"type": "sds-chip", "index": z}, n_clicks=0,
        disabled=False,
        style=chip_style(active=z in default_active, present=True))
        for z in _ZONES]
    return html.Div([dcc.Store(id="sds-active", data=default_active),
                     dcc.Store(id="sds-present", data=list(_ZONES)),
                     html.Div(chips)], style={"margin": "6px 0"})


def trend_body(df: pd.DataFrame, in_zones) -> html.Div:
    """Swing Decision Score Trend chart recomputed for the given in-zone set."""
    trend = P.swing_decision_trend(df, in_zones=in_zones or [])
    return html.Div(dcc.Graph(figure=charts.swing_decision_trend_fig(trend)))


def render(df: pd.DataFrame) -> html.Div:
    if df.empty:
        return html.Div("No pitch data for these filters.",
                        style={"color": "#555", "padding": "12px"})
    d = P.trim_to_first_contact(df)
    return html.Div([
        section("Swing Decision Score Trend"),
        sds_zone_chip_row(d),
        html.Div(id="sds-trend-body", children=trend_body(d, list(range(1, 10)))),
        section("Exit Velo & Distance by Pitch"),
        zone_chip_row(d),
        html.Div(id="sf-ev-body", children=ev_body(d, None)),
    ])
