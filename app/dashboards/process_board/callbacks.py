"""Dash callbacks for the All Things Process boards (pitcher + hitter share
these through `register_filter_callbacks`).

- Season/Cycle change -> refresh the Game Type choices (all selected) and
  reset Dates to the whole cycle.
- Date preset -> date range (Past Day/Week/Month anchor on the cycle's most
  recent game day, so "Past Day" is the last game, not an empty today).
- Game Type/Dates change -> re-list the Games in range, keeping any picked
  games that are still in it.
- Season/Cycle change -> re-list the Pitch Types thrown that cycle.
- Any filter/sort change -> re-read the board and re-style it (leader and
  baseline styles depend on the rows, so they're recomputed too).
"""
from __future__ import annotations

from dash import Input, Output, State, no_update

from app.data import process_board as PB
from app.dashboards import date_range as dr
from app.dashboards.process_board import layout, tables


def register_filter_callbacks(dash_app, prefix: str, data, table) -> None:

    @dash_app.callback(
        Output(f"{prefix}-game-types", "options"),
        Output(f"{prefix}-game-types", "value"),
        Output(f"{prefix}-date-preset", "value"),
        Output(f"{prefix}-daterange", "min_date_allowed"),
        Output(f"{prefix}-daterange", "max_date_allowed"),
        Output(f"{prefix}-daterange", "start_date"),
        Output(f"{prefix}-daterange", "end_date"),
        Input(f"{prefix}-season", "value"),
        Input(f"{prefix}-cycle", "value"),
        prevent_initial_call=True,
    )
    def _on_window(season, cycle):
        c_start, c_end = data.cycle_bounds(season, cycle)
        types = data.game_types(c_start, c_end)
        return ([{"label": t, "value": t} for t in types], types, "cycle",
                c_start, c_end, c_start, c_end)

    @dash_app.callback(
        Output(f"{prefix}-pitch-types", "options"),
        Output(f"{prefix}-pitch-types", "value"),
        Input(f"{prefix}-season", "value"),
        Input(f"{prefix}-cycle", "value"),
        State(f"{prefix}-pitch-types", "value"),
        prevent_initial_call=True,
    )
    def _on_pitch_types(season, cycle, picked):
        kinds = data.pitch_types(season, cycle)
        return [{"label": k, "value": k} for k in kinds], [k for k in (picked or []) if k in kinds]

    @dash_app.callback(
        Output(f"{prefix}-daterange", "start_date", allow_duplicate=True),
        Output(f"{prefix}-daterange", "end_date", allow_duplicate=True),
        Output(f"{prefix}-cal-wrap", "style"),
        Input(f"{prefix}-date-preset", "value"),
        State(f"{prefix}-season", "value"),
        State(f"{prefix}-cycle", "value"),
        prevent_initial_call=True,
    )
    def _on_preset(preset, season, cycle):
        show = {"display": "block" if preset == "custom" else "none", "marginTop": "6px"}
        if preset == "custom":
            return no_update, no_update, show
        c_start, c_end = data.cycle_bounds(season, cycle)
        rng = dr.preset_range(preset, data.latest_game_date(season, cycle))
        if rng is None:
            return c_start, c_end, show
        s, e = rng
        return max(str(s), str(c_start)), min(str(e), str(c_end)), show

    @dash_app.callback(
        Output(f"{prefix}-games", "options"),
        Output(f"{prefix}-games", "value"),
        Output(f"{prefix}-games", "placeholder"),
        Input(f"{prefix}-game-types", "value"),
        Input(f"{prefix}-daterange", "start_date"),
        Input(f"{prefix}-daterange", "end_date"),
        State(f"{prefix}-season", "value"),
        State(f"{prefix}-cycle", "value"),
        State(f"{prefix}-games", "value"),
        prevent_initial_call=True,
    )
    def _on_games(game_types, start, end, season, cycle, picked):
        g = data.games(season, cycle, game_types or None, start, end)
        still_in_range = [gid for gid in (picked or []) if gid in set(g["game_id"])]
        return layout.game_options(g), still_in_range, layout.games_placeholder(g)

    @dash_app.callback(
        Output(table.TABLE_ID, "data"),
        Output(table.TABLE_ID, "style_data_conditional"),
        Input(f"{prefix}-games", "value"),
        Input(f"{prefix}-game-types", "value"),
        Input(f"{prefix}-daterange", "start_date"),
        Input(f"{prefix}-daterange", "end_date"),
        Input(f"{prefix}-hand", "value"),
        Input(f"{prefix}-pitch-types", "value"),
        Input(table.TABLE_ID, "sort_by"),
        State(f"{prefix}-season", "value"),
        State(f"{prefix}-cycle", "value"),
        prevent_initial_call=True,
    )
    def _on_filters(game_ids, game_types, start, end, hand, pitch_types, sort_by,
                    season, cycle):
        board = data.board(season, cycle, game_types or None, start, end, game_ids or None,
                           hand, pitch_types or None)
        return table.records(board, sort_by), table.cell_styles(board)


def register_callbacks(dash_app) -> None:
    register_filter_callbacks(dash_app, "process", PB, tables)
