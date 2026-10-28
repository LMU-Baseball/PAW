"""Dash callbacks for the hitter All Things Process board.

- Season/Cycle change -> refresh the Game Type choices (all selected).
- Season/Cycle/Game Type/sort change -> re-read the board and re-style it
  (baseline and leader styles depend on the rows, so they're recomputed too).
"""
from __future__ import annotations

from dash import Input, Output, State

from app.data import hitter_process_board as HB
from app.dashboards.hitter_process_board import tables


def register_callbacks(dash_app) -> None:

    @dash_app.callback(
        Output("hproc-game-types", "options"),
        Output("hproc-game-types", "value"),
        Input("hproc-season", "value"),
        Input("hproc-cycle", "value"),
        prevent_initial_call=True,
    )
    def _on_window(season, cycle):
        types = HB.game_types(*HB.cycle_bounds(season, cycle))
        return [{"label": t, "value": t} for t in types], types

    @dash_app.callback(
        Output(tables.TABLE_ID, "data"),
        Output(tables.TABLE_ID, "style_data_conditional"),
        Input("hproc-game-types", "value"),
        Input(tables.TABLE_ID, "sort_by"),
        State("hproc-season", "value"),
        State("hproc-cycle", "value"),
        prevent_initial_call=True,
    )
    def _on_filters(game_types, sort_by, season, cycle):
        board = HB.board(season, cycle, game_types or None)
        return tables.records(board, sort_by), tables.cell_styles(board)
