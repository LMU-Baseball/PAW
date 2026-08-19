"""Batted Ball tab — hit-type chips -> distribution fan + landing scatter, + contact bar."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import practice as P
from app.dashboards.hitting_practice import charts
from app.dashboards.shell import section

_HIT_ORDER = ["Ground Ball", "Line Drive", "Fly Ball"]


def bb_chip_style(color: str, active: bool) -> dict:
    return {"border": f"2px solid {color}",
            "background": color if active else "#fff",
            "color": "#fff" if active else color,
            "borderRadius": "12px", "padding": "2px 10px", "margin": "0 4px 4px 0",
            "cursor": "pointer", "opacity": "1" if active else ".55",
            "fontFamily": "Teko, sans-serif", "fontSize": "14px"}


def chip_row(plays: pd.DataFrame) -> html.Div:
    labels = pd.Series(dtype=object)
    if plays is not None and not plays.empty and "hit_type" in plays.columns:
        labels = plays["hit_type"].map(P.HIT_TYPE_MAP)
    present = [t for t in _HIT_ORDER if t in set(labels.dropna())]
    if not present:
        present = list(_HIT_ORDER)
    chips = [html.Button(t, id={"type": "bb-chip", "index": t}, n_clicks=0,
                         style=bb_chip_style(P.HIT_TYPE_COLORS.get(t, "#5a5a5a"), active=True))
             for t in present]
    return html.Div([dcc.Store(id="bb-active", data=present),
                     dcc.Store(id="bb-present", data=present),
                     html.Div(chips)], style={"margin": "6px 0"})


def body(plays: pd.DataFrame, active_labels) -> html.Div:
    d = plays
    if active_labels is not None and plays is not None and not plays.empty \
            and "hit_type" in plays.columns:
        keep = set(active_labels)
        d = plays[plays["hit_type"].map(P.HIT_TYPE_MAP).isin(keep)]
    fan = P.spray_fan(d)
    spray = P.spray_points(d)
    counts = P.hit_type_counts(plays)  # contact bar stays unfiltered (overview)
    return html.Div([
        html.Div([
            html.Div([section("Batted-Ball Distribution"),
                      dcc.Graph(figure=charts.spray_distribution_fan(fan))],
                     style={"flex": "1"}),
            html.Div([section("Landing Chart"),
                      dcc.Graph(figure=charts.spray_chart_fig(spray))],
                     style={"flex": "1"}),
        ], className="paw-chart-row", style={"display": "flex", "gap": "16px"}),
        section("Contact Type"),
        dcc.Graph(figure=charts.contact_type_bar(counts)),
    ])


def render(plays: pd.DataFrame) -> html.Div:
    if plays is None or plays.empty:
        return html.Div("No batted-ball data for these filters.",
                        style={"color": "#555", "padding": "12px"})
    return html.Div([chip_row(plays),
                     html.Div(id="bb-body", children=body(plays, None))])
