"""Last Outings tab: averages across the last N appearances + a trend table."""
from __future__ import annotations

import pandas as pd
from dash import html

from app.data import pitching as P
from app.dashboards.pitching import tables
from app.dashboards.shell import section

_COLS = {
    "game_date": "Date", "appearance_avg_velo": "Avg Velo",
    "appearance_max_velo": "Max Velo", "pitch_count": "Pitches",
}


def render(pitcher_id, game_id, n: int = 5) -> html.Div:
    if pitcher_id is None or game_id is None:
        return html.Div("No outing selected.")
    recent = P.recent_outings(int(pitcher_id), int(game_id), n)
    if recent.empty:
        return html.Div("No prior outings.")
    avg = P.averages_last5(recent)
    show = avg[[c for c in _COLS if c in avg.columns]].rename(columns=_COLS)
    return html.Div([
        section(f"Last {len(show)} Outings"),
        tables.df_table(show, id_="lo-avgs"),
    ])
