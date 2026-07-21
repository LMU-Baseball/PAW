"""Zone Location tab: filtered scatter + swing-decision + plate-discipline tables."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import hitting
from app.dashboards.hitting import charts, tables

ZONE_FILTER_OPTIONS = [{"label": v, "value": v} for v in
                       ["All Swings", "All Takes", "Heart", "Shadow", "Chase", "Waste"]]


def _filter(game_df: pd.DataFrame, zone_choice: str) -> pd.DataFrame:
    if game_df is None or game_df.empty:
        return pd.DataFrame(columns=getattr(game_df, "columns", None))
    if zone_choice == "All Swings":
        return game_df[game_df["PitchCall"].isin(hitting.SWING_CALLS)]
    if zone_choice == "All Takes":
        return game_df[game_df["PitchCall"].isin(hitting.TAKE_CALLS)]
    return game_df[game_df["Zone"] == zone_choice]


def render(game_df: pd.DataFrame, zone_choice: str = "All Swings") -> html.Div:
    sub = _filter(game_df, zone_choice)
    fig = charts.zone_scatter(sub, title=f"Zone Location — {zone_choice}")
    swing_dec = hitting.swing_decisions_by_zone(game_df) if game_df is not None \
        and not game_df.empty else pd.DataFrame()
    pd_zone = hitting.plate_discipline(game_df, by="zone") if game_df is not None \
        and not game_df.empty else pd.DataFrame()
    pd_pt = hitting.plate_discipline(game_df, by="pitch_type") if game_df is not None \
        and not game_df.empty else pd.DataFrame()

    def sec(title, child):
        return html.Div([html.H3(title, style={"color": "#9A0021",
                                                "margin": "16px 0 6px"}), child])

    return html.Div([
        html.Div(dcc.Graph(figure=fig, config={"displayModeBar": False}),
                 style={"maxWidth": "560px"}),
        sec("Swing / Take by Zone", tables.stat_table(swing_dec, id="tbl-swdec")),
        sec("Plate Discipline — Area of Zone",
            tables.stat_table(pd_zone, id="tbl-pd-zone")),
        sec("Plate Discipline — Pitch Type",
            tables.stat_table(pd_pt, id="tbl-pd-pt")),
    ])
