"""Dash callbacks for the Velo Board dashboard.

Two callbacks, both coach-grid-only inputs (a player's layout never renders
`velo-season`/`velo-week`/`velo-grid`/`velo-save`, so these simply never fire
for a player -- `suppress_callback_exceptions=True` on the app, set in
index.py, is what lets Dash accept callbacks referencing ids absent from a
given render):

- Season/Week change -> re-read the grid + leaderboard for the new
  (season, week).
- Save click -> persist the edited grid to RDS, then re-read both. The
  coach-write gate is re-checked HERE (not just trusted from the layout
  omitting the grid for players) -- the second half of the double-gate.
"""
from __future__ import annotations

from dash import Input, Output, State, no_update
from flask_login import current_user

from app.data import velo_board
from app.dashboards.velo_board import grid, visual


def register_callbacks(dash_app) -> None:

    @dash_app.callback(
        Output("velo-grid", "data"),
        Output("velo-leaderboard", "children"),
        Input("velo-season", "value"),
        Input("velo-week", "date"),
        prevent_initial_call=True,
    )
    def _on_season_or_week(season, week_date):
        week = velo_board.week_start_for(week_date)
        rows = velo_board.grid_rows(season, week).to_dict("records")
        lb = visual.leaderboard_view(velo_board.leaderboard(season))
        return rows, lb

    @dash_app.callback(
        Output("velo-grid", "editable", allow_duplicate=True),
        Output("velo-save-status", "children", allow_duplicate=True),
        Input("velo-edit", "n_clicks"),
        prevent_initial_call=True,
    )
    def _on_edit(n_clicks):
        """Edit unlocks the grid for typing (re-checks coach server-side)."""
        if not n_clicks or not bool(getattr(current_user, "is_coach", False)):
            return no_update, no_update
        return True, "Editing — type new numbers into any cell, then Save."

    @dash_app.callback(
        Output("velo-grid", "data", allow_duplicate=True),
        Output("velo-save-status", "children"),
        Output("velo-leaderboard", "children", allow_duplicate=True),
        Output("velo-grid", "editable"),
        Input("velo-save", "n_clicks"),
        State("velo-grid", "data"),
        State("velo-season", "value"),
        State("velo-week", "date"),
        prevent_initial_call=True,
    )
    def _on_save(n_clicks, grid_data, season, week_date):
        if not n_clicks:
            return no_update, no_update, no_update, no_update
        if not bool(getattr(current_user, "is_coach", False)):
            return no_update, no_update, no_update, no_update
        week = velo_board.week_start_for(week_date)
        grid.save_rows(grid_data, season, week, updated_by=getattr(current_user, "id", None))
        rows = velo_board.grid_rows(season, week).to_dict("records")
        lb = visual.leaderboard_view(velo_board.leaderboard(season))
        return rows, "Saved.", lb, False  # re-lock the grid after saving
