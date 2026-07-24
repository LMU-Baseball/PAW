"""Caught Stealing tab: attempt tiles + per-attempt table (real SB/CS outcomes)."""
from __future__ import annotations

import pandas as pd
from dash import html

from app.data import catching as C
from app.dashboards.catching import tables
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
    summ = C.caught_stealing_summary(df)
    tiles = html.Div([
        _tile("Attempts", summ["attempts"]),
        _tile("Caught", summ["caught"]),
        _tile("CS%", _fmt(summ["cs_pct"], "%")),
        _tile("Avg Pop (s)", _fmt(summ["avg_pop"])),
    ], style={"display": "flex", "gap": "10px", "flexWrap": "wrap",
              "marginBottom": "12px"})

    ev = C.caught_stealing_events(df)
    if ev.empty:
        table = html.Div("No stolen-base attempts recorded for this game.",
                         style={"color": "#555", "padding": "8px"})
    else:
        show = pd.DataFrame({
            "Inn": ev.get("inning"),
            "Pitcher": ev.get("pitcher_name"),
            "Result": ev["Caught"].map({True: "Caught", False: "Stolen"}),
            "Pop (s)": ev["pop_time"].map(
                lambda v: "—" if pd.isna(v) else f"{v:.2f}"),
            "Exch (s)": ev["exchange_time"].map(
                lambda v: "—" if pd.isna(v) else f"{v:.2f}"),
            "Throw (mph)": ev["throw_speed"].map(
                lambda v: "—" if pd.isna(v) else f"{v:.1f}"),
        })
        table = tables.df_table(show, id_="cs-table")

    return html.Div([section("Caught Stealing"), tiles, table])
