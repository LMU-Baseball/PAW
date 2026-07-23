"""Throws tab: pop time / exchange / throw speed."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import catching as C
from app.dashboards.catching import charts, tables
from app.dashboards.shell import CRIMSON, section


def _tile(label, value):
    return html.Div([
        html.Div(str(value), style={"fontSize": "28px", "fontWeight": "bold",
                                    "color": CRIMSON}),
        html.Div(label, style={"fontSize": "14px", "color": "#555"}),
    ], style={"textAlign": "center", "padding": "10px 14px",
              "backgroundColor": "rgba(255,255,255,0.85)", "borderRadius": "8px",
              "minWidth": "110px"})


def _fmt(v, suffix=""):
    return "—" if v is None else f"{v}{suffix}"


def render(df: pd.DataFrame) -> html.Div:
    if df.empty:
        return html.Div("No pitch data.")
    summ = C.throws_summary(df)
    tiles = html.Div([
        _tile("Attempts", summ["attempts"]),
        _tile("Avg Pop", _fmt(summ["avg_pop"], "s")),
        _tile("Min Pop", _fmt(summ["min_pop"], "s")),
        _tile("Avg Exch", _fmt(summ["avg_exchange"], "s")),
        _tile("Avg Velo", _fmt(summ["avg_throw_speed"], " mph")),
    ], style={"display": "flex", "gap": "10px", "flexWrap": "wrap",
              "marginBottom": "12px"})

    attempts = C.throw_attempts(df)
    if attempts.empty:
        body = html.Div(
            "No throw attempts with pop time / throw speed in this game.",
            style={"color": "#555"})
        chart = html.Div()
    else:
        cols = [c for c in (
            "inning", "pitcher_name", "pop_time", "exchange_time", "throw_speed",
            "play_result", "pitch_call",
        ) if c in attempts.columns]
        show = attempts[cols].copy()
        rename = {
            "inning": "Inn", "pitcher_name": "Pitcher", "pop_time": "Pop",
            "exchange_time": "Exchange", "throw_speed": "Throw mph",
            "play_result": "Result", "pitch_call": "Call",
        }
        show = show.rename(columns={k: v for k, v in rename.items() if k in show.columns})
        body = tables.df_table(show, id_="throws-table")
        chart = dcc.Graph(figure=charts.pop_time_chart(df))

    return html.Div([
        section("Throws"),
        tiles,
        chart,
        section("Throw Attempts"),
        body,
        html.Div(
            "Provisional: attempts = rows with non-null pop_time / exchange_time / throw_speed.",
            style={"fontSize": "12px", "color": "#888", "marginTop": "8px"}),
    ])
