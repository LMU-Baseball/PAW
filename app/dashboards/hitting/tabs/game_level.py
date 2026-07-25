"""Game Level tab: batting line + batted-ball profile."""
from __future__ import annotations

import pandas as pd
from dash import html

from app.data import hitting
from app.dashboards.hitting import tables


def _section(title, child):
    return html.Div([
        html.H3(title, style={"color": "#9A0021", "margin": "16px 0 6px"}),
        child,
    ])


def render(game_df: pd.DataFrame) -> html.Div:
    line = hitting.game_batting_line(game_df)
    line_df = pd.DataFrame([line])
    # QC+/PathQ+ are LMU-custom columns absent from the warehouse (NaN) — drop them.
    _drop = ["Avg QC+", "Avg PathQ+"]
    bb_overall = hitting.batted_ball_profile(game_df).drop(columns=_drop, errors="ignore")
    bb_pt = hitting.batted_ball_profile(game_df, by_pitch_type=True).drop(
        columns=_drop, errors="ignore")
    return html.Div([
        _section("Batting Line", tables.stat_table(line_df, id="tbl-line")),
        _section("Batted Ball Profile", tables.stat_table(bb_overall, id="tbl-bb")),
        _section("Batted Ball by Pitch Type", tables.stat_table(bb_pt, id="tbl-bb-pt")),
    ], style={"padding": "10px 4px"})
