"""RHH v. LHH tab: side-by-side usage + location vs left/right-handed hitters."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import pitching as P
from app.dashboards.pitching import tables
from app.dashboards.shell import section

_USAGE_COLS = {"pitch": "Pitch", "count": "#", "usage_pct": "Usage%"}


def _side_col(df: pd.DataFrame, side: str, usage: pd.DataFrame) -> html.Div:
    sub = df[df["batter_side"] == side]
    tbl = (usage[list(_USAGE_COLS)].rename(columns=_USAGE_COLS)
           if not usage.empty else pd.DataFrame(columns=list(_USAGE_COLS.values())))
    return html.Div([
        section(f"vs {side}-handed"),
        tables.df_table(tbl, id_=f"split-usage-{side.lower()}"),
        dcc.Graph(figure=P.fig_location_split(sub)),
    ], style={"flex": "1"})


def render(df: pd.DataFrame) -> html.Div:
    if df.empty:
        return html.Div("No pitch data.")
    splits = P.splits_by_batter_side(df)
    return html.Div([
        _side_col(df, "Left", splits["Left"]["usage"]),
        _side_col(df, "Right", splits["Right"]["usage"]),
    ], style={"display": "flex", "gap": "16px"})
