"""Blocking tab: dirt-pitch summary + event table."""
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
              "minWidth": "100px"})


def render(df: pd.DataFrame) -> html.Div:
    if df.empty:
        return html.Div("No pitch data.")
    summ = C.blocking_summary(df)
    bp = summ["block_pct"]
    tiles = html.Div([
        _tile("Dirt", summ["dirt"]),
        _tile("Blocked", summ["blocked"]),
        _tile("Passed/Wild", summ["passed_wild"]),
        _tile("Block%", "—" if bp is None else f"{bp}%"),
    ], style={"display": "flex", "gap": "10px", "flexWrap": "wrap",
              "marginBottom": "12px"})

    ev = C.dirt_events(df)
    if ev.empty:
        body = html.Div("No dirt / blocking events tagged for this game.",
                        style={"color": "#555"})
    else:
        cols = [c for c in (
            "inning", "balls", "strikes", "pitcher_name", "pitch_call",
            "play_result", "plate_loc_height", "BlockOutcome",
        ) if c in ev.columns or c == "BlockOutcome"]
        show = ev[cols].copy()
        rename = {
            "inning": "Inn", "balls": "B", "strikes": "S",
            "pitcher_name": "Pitcher", "pitch_call": "Call",
            "play_result": "Result", "plate_loc_height": "Height",
            "BlockOutcome": "Outcome",
        }
        show = show.rename(columns={k: v for k, v in rename.items() if k in show.columns})
        body = tables.df_table(show, id_="blocking-events")

    return html.Div([
        section("Blocking"),
        tiles,
        section("Dirt / Block Events"),
        body,
        html.Div(
            "Provisional: dirt = BallinDirt calls, PassedBall/WildPitch results, "
            "or low (<1.5 ft) BallCalled/BallinDirt.",
            style={"fontSize": "12px", "color": "#888", "marginTop": "8px"}),
    ])
