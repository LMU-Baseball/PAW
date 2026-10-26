"""Dash callbacks for the All Things Process board.

- Season/Cycle change -> refresh the Game Type choices (all selected).
- Season/Cycle/Game Type/sort change -> re-read the board and re-style it
  (leader/baseline styles depend on the rows, so they're recomputed too).
"""
from __future__ import annotations

from dash import Input, Output, State

from app.data import process_board as PB
from app.dashboards.process_board import tables


def register_callbacks(dash_app) -> None:

    @dash_app.callback(
        Output("process-game-types", "options"),
        Output("process-game-types", "value"),
        Input("process-season", "value"),
        Input("process-cycle", "value"),
        prevent_initial_call=True,
    )
    def _on_window(season, cycle):
        types = PB.game_types(*PB.cycle_bounds(season, cycle))
        return [{"label": t, "value": t} for t in types], types

    @dash_app.callback(
        Output(tables.TABLE_ID, "data"),
        Output(tables.TABLE_ID, "style_data_conditional"),
        Input("process-game-types", "value"),
        Input(tables.TABLE_ID, "sort_by"),
        State("process-season", "value"),
        State("process-cycle", "value"),
        prevent_initial_call=True,
    )
    def _on_filters(game_types, sort_by, season, cycle):
        board = PB.board(season, cycle, game_types or None)
        return tables.records(board, sort_by), tables.cell_styles(board)
