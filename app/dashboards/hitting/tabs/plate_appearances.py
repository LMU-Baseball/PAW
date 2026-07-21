"""Plate Appearances tab: per-PA zone scatter + pitch table; all-PAs facet."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.dashboards.hitting import charts, tables

_PA_TABLE_COLS = ["PitchofPA", "TaggedPitchType", "PitchCall", "PlayResult",
                  "Balls", "Strikes", "ExitSpeed", "Pitcher"]


def pa_choices(game_df: pd.DataFrame) -> list[dict]:
    if game_df is None or game_df.empty:
        return []
    keys = sorted(game_df.groupby(["Inning", "PAofInning"]).groups.keys())
    return [{"label": f"Inn {int(i)} · PA {int(p)}", "value": f"{int(i)}-{int(p)}"}
            for (i, p) in keys]


def _pa_slice(game_df, pa_value):
    keys = sorted(game_df.groupby(["Inning", "PAofInning"]).groups.keys())
    if not keys:
        return game_df.iloc[0:0]
    if pa_value:
        inn, pa = (int(x) for x in pa_value.split("-"))
    else:
        inn, pa = keys[0]
    return game_df[(game_df["Inning"] == inn) & (game_df["PAofInning"] == pa)]


def render_breakdown(game_df: pd.DataFrame, pa_value: str | None) -> html.Div:
    sub = _pa_slice(game_df, pa_value) if game_df is not None and not game_df.empty \
        else pd.DataFrame()
    fig = charts.zone_scatter(sub, title="Pitch Locations")
    cols = [c for c in _PA_TABLE_COLS if c in sub.columns]
    tbl = tables.stat_table(sub[cols] if not sub.empty else pd.DataFrame(),
                            id="tbl-pa")
    return html.Div([
        html.Div(dcc.Graph(figure=fig, config={"displayModeBar": False}),
                 style={"maxWidth": "560px"}),
        tbl,
    ])


def render_all_pas(game_df: pd.DataFrame) -> dcc.Graph:
    return dcc.Graph(figure=charts.all_pas_figure(game_df),
                     config={"displayModeBar": False})
