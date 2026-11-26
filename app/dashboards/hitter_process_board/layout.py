"""All Things Process (hitters) page: the same LMU banner and Season/Cycle/Game
Type filters as the pitcher board, over the hitter leaderboard. Read-only for
every logged-in user."""
from __future__ import annotations

from datetime import date

from dash import html
from flask_login import current_user

from app.data import hitter_process_board as HB
from app.data import seasons, velo_board
from app.dashboards import shell
from app.dashboards.hitter_process_board import tables
from app.dashboards.process_board.layout import _swatch, filters, process_header


def legend() -> html.Div:
    return html.Div([
        _swatch(tables.LEADER, "Team leader"),
        _swatch(tables.MEETS, "At or better than LMU Team Average"),
        _swatch(tables.MISSES, "Worse than LMU Team Average"),
        html.Span("Lower is better for GB%, Chase%, Whiff%, IZ Whiff%, SwStr 2K% and Chase 2K%. "
                  f"Leaders need {HB.MIN_PITCHES_FOR_LEADER}+ pitches. Click a column header to sort.",
                  style={"color": "#555"}),
    ], style={"display": "flex", "flexWrap": "wrap", "gap": "6px", "fontSize": "14px",
              "padding": "8px 20px", "justifyContent": "center"})


def serve_layout() -> html.Div:
    if not current_user.is_authenticated:
        return html.Div("Please log in.")
    season = seasons.season_label_for(date.today().isoformat())
    cycle = velo_board.velo_cycle_for_date(date.today())
    board = HB.board(season, cycle)
    return html.Div([
        shell.header(back_href="/hitting", back_label="← Hitting"),
        process_header(),
        html.Div(filters("hproc", HB, season, cycle, tables),
                 style={"borderBottom": f"2px solid {shell.CRIMSON}",
                        "backgroundColor": "rgba(255,255,255,0.55)"}),
        legend(),
        html.Div(tables.hitter_table(board), id="hproc-board",
                 style={"padding": "0 20px 30px"}),
    ])
