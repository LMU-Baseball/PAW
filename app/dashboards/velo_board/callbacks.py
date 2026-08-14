"""Dash callbacks for the Velo Board dashboard.

The board is ONE unified table (`velo-grid`) everyone sees; a coach edits it in
place. All inputs here are coach-only (a player's layout renders neither the
Season/Week selectors nor the Edit/Save buttons, so these never fire for a
player -- `suppress_callback_exceptions=True`, set in index.py, lets Dash
accept callbacks referencing ids absent from a given render):

- Season/Week change -> re-read the table rows.
- Edit click -> unlock the table's four editable columns in place.
- Save click -> persist (goal/assessment weekly + changed velo overrides), then
  re-read and re-lock. The coach-write gate is re-checked HERE.
"""
from __future__ import annotations

from dash import Input, Output, State, no_update
from flask_login import current_user

from app.data import velo_board
from app.dashboards.velo_board import grid, visual


def _is_coach() -> bool:
    return bool(getattr(current_user, "is_coach", False))


def register_callbacks(dash_app) -> None:

    @dash_app.callback(
        Output("velo-grid", "data"),
        Input("velo-season", "value"),
        Input("velo-week", "date"),
        prevent_initial_call=True,
    )
    def _on_season_or_week(season, week_date):
        week = velo_board.week_start_for(week_date)
        return visual.board_records(velo_board.board_rows(season, week))

    @dash_app.callback(
        Output("velo-grid", "editable", allow_duplicate=True),
        Output("velo-save-status", "children", allow_duplicate=True),
        Input("velo-edit", "n_clicks"),
        prevent_initial_call=True,
    )
    def _on_edit(n_clicks):
        """Edit unlocks the four editable columns in place (re-checks coach)."""
        if not n_clicks or not _is_coach():
            return no_update, no_update
        return True, ("Editing — type into Season Max / Season Avg / Velo Goal / "
                      "Assessment, then Save.")

    @dash_app.callback(
        Output("velo-grid", "data", allow_duplicate=True),
        Output("velo-grid", "editable"),
        Output("velo-save-status", "children"),
        Input("velo-save", "n_clicks"),
        State("velo-grid", "data"),
        State("velo-season", "value"),
        State("velo-week", "date"),
        prevent_initial_call=True,
    )
    def _on_save(n_clicks, grid_data, season, week_date):
        if not n_clicks or not _is_coach():
            return no_update, no_update, no_update
        week = velo_board.week_start_for(week_date)
        grid.save_board(grid_data, season, week, updated_by=getattr(current_user, "id", None))
        rows = visual.board_records(velo_board.board_rows(season, week))
        return rows, False, "Saved."   # re-read + re-lock in place
