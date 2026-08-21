"""Pitch Breakdown tab: characteristics + usage + velo trend (inning / pitch count)
+ the movement / release-point pair.

This is the dashboard's DEFAULT tab (`value="breakdown"` in layout.serve_layout),
so it is the pitching homepage -- which is why the coaches' meeting asked for
movement and release side/height to live here rather than one tab deep. Both
figures come straight out of `app.data.pitching`; nothing is recomputed locally.

The two figures sit in a `paw-chart-row` flex pair: side by side on anything
wider than a phone, stacked at <=720px by the shell's media query. That class is
load-bearing, not decoration -- this dashboard gets opened on phones in the
dugout, and two squeezed-together scatters are unreadable there.
"""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import pitching as P
from app.dashboards.pitching import tables
from app.dashboards.shell import section

_CHAR_COLS = {
    "pitch": "Pitch", "count": "#", "usage_pct": "Usage%",
    "avg_velo": "Velo", "max_velo": "Max", "spin_rate": "Spin",
    "ivb": "IVB", "hb": "HB", "extension": "Ext",
}


def _chart_pair(df: pd.DataFrame) -> html.Div:
    """Movement + release point, side by side (stacked on a phone).

    Both figures dropna their own inputs, so a frame whose break or release
    columns are all-NaN yields an empty-but-valid panel rather than raising --
    no guard needed here.
    """
    return html.Div([
        html.Div([section("Movement"), dcc.Graph(figure=P.fig_movement(df))],
                 style={"flex": "1"}),
        html.Div([section("Release Point"), dcc.Graph(figure=P.fig_release(df))],
                 style={"flex": "1"}),
    ], className="paw-chart-row", style={"display": "flex", "gap": "16px"})


def render(df: pd.DataFrame) -> html.Div:
    if df.empty:
        return html.Div("No pitch data.")
    char = P.pitch_characteristics(df)[list(_CHAR_COLS)].rename(columns=_CHAR_COLS)
    return html.Div([
        section("Pitch Characteristics"),
        tables.df_table(char, id_="pb-char"),
        _chart_pair(df),
        section("Velocity Across Outing"),
        dcc.Graph(figure=P.fig_velo_by_pitch(df)),
    ])
