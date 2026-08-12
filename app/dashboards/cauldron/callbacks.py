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

from dash import Input, Output, State, no_update
from flask_login import current_user

from app.data import cauldron, pitching_caps, seasons
from app.dashboards.cauldron import grid, visual


def _is_coach() -> bool:
    return bool(getattr(current_user, "is_coach", False))


def _roster_names(season: str) -> dict:
    roster = pitching_caps.lmu_pitchers(season)
    if roster.empty:
        return {}
    return dict(zip(roster["PitcherId"].astype(int), roster["Pitcher"]))


def _refresh(play_date, cycle_id):
    season = seasons.current_season()
    rows = grid._grid_rows(
        pitching_caps.lmu_pitchers(season), cauldron.read_scoring(),
        cauldron.read_teams(cycle_id), cauldron.read_daily(play_date), play_date,
    )
    scoreboard = visual.scoreboard_view(
        cauldron.read_daily(), cauldron.read_teams(cycle_id), cauldron.read_scoring(),
        _roster_names(season))
    return rows, scoreboard


def register_callbacks(dash_app) -> None:

    @dash_app.callback(
        Output("cauldron-grid", "data"),
        Output("cauldron-scoreboard", "children"),
        Input("cauldron-date", "date"),
        Input("cauldron-cycle", "value"),
        prevent_initial_call=True,
    )
    def _on_date_or_cycle(play_date, cycle_id):
        return _refresh(play_date, cycle_id)

    @dash_app.callback(
        Output("cauldron-grid", "editable", allow_duplicate=True),
        Output("cauldron-save-status", "children", allow_duplicate=True),
        Input("cauldron-edit", "n_clicks"),
        prevent_initial_call=True,
    )
    def _on_edit(n_clicks):
        """Edit unlocks the grid for typing (re-checks coach server-side)."""
        if not n_clicks or not _is_coach():
            return no_update, no_update
        return True, "Editing — assign teams / type points into any cell, then Save."

    @dash_app.callback(
        Output("cauldron-grid", "data", allow_duplicate=True),
        Output("cauldron-scoreboard", "children", allow_duplicate=True),
        Output("cauldron-save-status", "children"),
        Output("cauldron-grid", "editable"),
        Input("cauldron-save", "n_clicks"),
        State("cauldron-grid", "data"),
        State("cauldron-date", "date"),
        State("cauldron-cycle", "value"),
        prevent_initial_call=True,
    )
    def _on_save(n_clicks, grid_data, play_date, cycle_id):
        if not n_clicks:
            return no_update, no_update, no_update, no_update
        if not _is_coach():
            return no_update, no_update, no_update, no_update
        grid.save_grid(grid_data, play_date, cycle_id, updated_by=getattr(current_user, "id", None))
        rows, scoreboard = _refresh(play_date, cycle_id)
        return rows, scoreboard, "Saved.", False  # re-lock the grid after saving

    @dash_app.callback(
        Output("cauldron-grid", "data", allow_duplicate=True),
        Output("cauldron-scoreboard", "children", allow_duplicate=True),
        Output("cauldron-save-status", "children", allow_duplicate=True),
        Input("cauldron-recompute", "n_clicks"),
        State("cauldron-date", "date"),
        State("cauldron-cycle", "value"),
        prevent_initial_call=True,
    )
    def _on_recompute(n_clicks, play_date, cycle_id):
        if not n_clicks:
            return no_update, no_update, no_update
        if not _is_coach():
            return no_update, no_update, no_update
        n = cauldron.score_day(play_date)
        rows, scoreboard = _refresh(play_date, cycle_id)
        return rows, scoreboard, f"Recomputed ({n} rows)."
