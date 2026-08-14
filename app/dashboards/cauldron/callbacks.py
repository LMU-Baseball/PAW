"""Dash callbacks for the Competitive Cauldron dashboard.

Three callbacks, all coach-grid-only inputs except the scoreboard output
(a player's layout never renders `cauldron-date`/`cauldron-cycle`/
`cauldron-grid`/`cauldron-save`/`cauldron-recompute`, so these simply never
fire for a player -- `suppress_callback_exceptions=True` on the app, set in
index.py, is what lets Dash accept callbacks referencing ids absent from a
given render):

- Date/Cycle change -> refresh the grid rows + the scoreboard for the new
  (play_date, cycle).
- Save click -> persist the edited grid to RDS, then re-read both. The
  coach-write gate is re-checked HERE (not just trusted from the layout
  omitting the grid for players) -- the second half of the double-gate.
- Recompute click -> auto-score the day (`cauldron.score_day`, which never
  clobbers a coach's manual entries), then re-read both. Also re-checks
  `is_coach` -- Recompute writes too.
"""
from __future__ import annotations

from datetime import date, timedelta

from dash import Input, Output, State, no_update
from flask_login import current_user

from app.data import cauldron, pitching_caps, seasons, velo_board
from app.dashboards.cauldron import grid, visual

_HIDDEN = {"display": "none"}
_VISIBLE = {"display": "block"}


def _is_coach() -> bool:
    return bool(getattr(current_user, "is_coach", False))


def _roster_names(season: str) -> dict:
    roster = pitching_caps.lmu_pitchers(season)
    if roster.empty:
        return {}
    return dict(zip(roster["PitcherId"].astype(int), roster["Pitcher"]))


def _week_bounds(week_start):
    """Snap `week_start` to its Monday and return the inclusive Mon..Sun window."""
    ws = velo_board.week_start_for(week_start)
    we = (date.fromisoformat(ws) + timedelta(days=6)).isoformat()
    return ws, we


def _refresh(play_date, week_start, season):
    cycle_id = f"{season}-c1"
    rows = grid._grid_rows(
        pitching_caps.lmu_pitchers(season), cauldron.read_scoring(),
        cauldron.read_teams(cycle_id), cauldron.read_daily(play_date), play_date,
    )
    w_start, w_end = _week_bounds(week_start)
    scoreboard = visual.scoreboard_view(
        cauldron.read_daily(start=w_start, end=w_end), cauldron.read_teams(cycle_id),
        cauldron.read_scoring(), _roster_names(season))
    return rows, scoreboard


def register_callbacks(dash_app) -> None:

    @dash_app.callback(
        Output("cauldron-grid", "data"),
        Output("cauldron-scoreboard", "children"),
        Input("cauldron-date", "date"),
        Input("cauldron-week", "date"),
        prevent_initial_call=True,
    )
    def _on_date_or_week(play_date, week_start):
        return _refresh(play_date, week_start, seasons.current_season())

    @dash_app.callback(
        Output("cauldron-grid", "editable", allow_duplicate=True),
        Output("cauldron-grid-wrap", "style", allow_duplicate=True),
        Output("cauldron-save-status", "children", allow_duplicate=True),
        Input("cauldron-edit", "n_clicks"),
        prevent_initial_call=True,
    )
    def _on_edit(n_clicks):
        """Edit reveals + unlocks the grid for typing (re-checks coach)."""
        if not n_clicks or not _is_coach():
            return no_update, no_update, no_update
        return (True, _VISIBLE,
                "Editing — assign teams / captains / type points, then Save.")

    @dash_app.callback(
        Output("cauldron-grid", "data", allow_duplicate=True),
        Output("cauldron-scoreboard", "children", allow_duplicate=True),
        Output("cauldron-save-status", "children"),
        Output("cauldron-grid", "editable"),
        Output("cauldron-grid-wrap", "style"),
        Input("cauldron-save", "n_clicks"),
        State("cauldron-grid", "data"),
        State("cauldron-date", "date"),
        State("cauldron-week", "date"),
        prevent_initial_call=True,
    )
    def _on_save(n_clicks, grid_data, play_date, week_start):
        if not n_clicks or not _is_coach():
            return no_update, no_update, no_update, no_update, no_update
        season = seasons.current_season()
        cycle_id = f"{season}-c1"
        grid.save_grid(grid_data, play_date, cycle_id, updated_by=getattr(current_user, "id", None))
        rows, scoreboard = _refresh(play_date, week_start, season)
        # re-lock AND hide the grid after saving
        return rows, scoreboard, "Saved.", False, _HIDDEN
