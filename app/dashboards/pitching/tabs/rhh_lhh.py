"""RHH v. LHH tab: pitch-type chip filter -> side-by-side usage + location by type."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import pitching as P
from app.dashboards.pitching import tables
from app.dashboards.pitching.tabs.location_movement import chip_row
from app.dashboards.shell import section

_USAGE_COLS = {"pitch": "Pitch", "count": "#", "usage_pct": "Usage%"}


def _side_col(df: pd.DataFrame, side: str) -> html.Div:
    sub = df[df["batter_side"] == side]
    usage = P.pitch_usage(sub) if len(sub) else P.pitch_usage(df.iloc[0:0])
    tbl = (usage[list(_USAGE_COLS)].rename(columns=_USAGE_COLS)
           if not usage.empty else pd.DataFrame(columns=list(_USAGE_COLS.values())))
    return html.Div([
        section(f"vs {side}-handed"),
        tables.df_table(tbl, id_=f"split-usage-{side.lower()}"),
        dcc.Graph(figure=P.fig_location_split(sub)),
    ], style={"flex": "1"})


def body(df: pd.DataFrame) -> html.Div:
    if df.empty:
        return html.Div("No pitches for the selected pitch types.")
    return html.Div([_side_col(df, "Left"), _side_col(df, "Right")],
                    style={"display": "flex", "gap": "16px"})


def render(df: pd.DataFrame) -> html.Div:
    if df.empty:
        return html.Div("No pitch data.")
    return html.Div([chip_row(df, "splits"),
                     html.Div(id="splits-body", children=body(df))])
