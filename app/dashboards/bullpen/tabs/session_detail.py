"""Session Detail tab — one bullpen session in detail (interactive report)."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import bullpen as B
from app.dashboards.bullpen import charts, tables

_MUTED = {"padding": "12px", "color": "#555"}


def render(pitcher_id, date) -> html.Div:
    if pitcher_id is None:
        return html.Div("Select a pitcher.", style=_MUTED)
    if not date:
        return html.Div("No bullpen session in this date range.", style=_MUTED)
    df = B.session_pitches(int(pitcher_id), date)
    if df.empty:
        return html.Div("No pitches for this session.", style=_MUTED)

    summ_df = pd.DataFrame(B.summary_by_pitch_type(df))
    graph = lambda fig: dcc.Graph(figure=fig, style={"height": "340px"})
    charts_grid = html.Div(
        [graph(charts.velo_fig(df)), graph(charts.movement_fig(df)),
         graph(charts.release_fig(df)), graph(charts.location_fig(df))],
        style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "12px"})
    return html.Div([
        tables.df_table(summ_df, id_="bp-summary", color_col="pitch"),
        html.Div(style={"height": "12px"}),
        charts_grid,
        html.H4("All pitches", style={"color": "#9A0021", "marginTop": "14px"}),
        tables.df_table(df, id_="bp-pitches", color_col="tagged_pitch_type"),
    ])
