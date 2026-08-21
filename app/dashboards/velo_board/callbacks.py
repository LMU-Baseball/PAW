"""Dash callbacks for the Velo Board dashboard.

The board is ONE unified table (`velo-grid`) everyone sees; a coach edits it in
place.

- Season/Week change -> re-read the table rows. This fires for EVERY account:
  the selectors, the table and this callback's Output are all in a player's
  render too, so a player browses seasons/weeks exactly like a coach. (Dash will
  not fire a callback whose Inputs/Outputs are missing from the current render,
  which is why the filters must live outside the coach-only section.)

The remaining inputs are coach-only -- a player's layout renders no Edit/Save
buttons, so they never fire for a player (`suppress_callback_exceptions=True`,
set in index.py, lets Dash accept callbacks referencing ids absent from a given
render):
- Edit click -> unlock the table's four editable columns in place.
- Save click -> persist (goal/assessment weekly + changed velo overrides), then
  re-read and re-lock. The coach-write gate is re-checked HERE.
"""
from __future__ import annotations

from dash import Input, Output, State, no_update
from flask_login import current_user

from app.data import velo_board
from app.data.seasons import season_bounds
from app.dashboards.velo_board import grid, visual


def _is_coach() -> bool:
    return bool(getattr(current_user, "is_coach", False))


def register_callbacks(dash_app) -> None:

    @dash_app.callback(
        Output("velo-grid", "data"),
        Output("velo-week", "date"),
        Output("velo-week", "min_date_allowed"),
        Output("velo-week", "max_date_allowed"),
        Input("velo-season", "value"),
        Input("velo-week", "date"),
        prevent_initial_call=True,
    )
    def _on_season_or_week(season, week_date):
        """Season OR week change -> re-read the table rows, keeping the two
        controls coherent.

        Rather than asking WHICH input fired, this asks whether the picker's
        week still lies inside the selected season and snaps it when it doesn't.
        That covers the drift case (season changed, week left behind -- weekly
        Velo Goal / Assessment would blank out while the season-level columns
        updated) without depending on a callback context, and it leaves a week
        the user picked alone whenever it is already valid for that season.

        The week Output is `no_update` unless a snap is actually needed: it is
        also an Input, so echoing a value back would fire this callback a second
        time and pay another `board_rows` read for nothing."""
        start, end = season_bounds(season)
        week = velo_board.week_start_for(week_date) if week_date else None
        if week is None or not (velo_board.week_start_for(start) <= week <= end):
            week = velo_board.default_week_for(season)
            return (visual.board_records(velo_board.board_rows(season, week)),
                    week, start, end)
        return (visual.board_records(velo_board.board_rows(season, week)),
                no_update, start, end)

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
