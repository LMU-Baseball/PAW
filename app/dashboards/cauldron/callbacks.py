"""Dash callbacks for the Competitive Cauldron dashboard.

- **Week change -> rebuild the scoreboard.** This one is for EVERYONE. It is
  deliberately kept free of any coach-only component: a player's layout renders
  neither `cauldron-date` nor `cauldron-grid`, and Dash will not fire a callback
  whose Inputs/Outputs are missing from the current render -- so pairing the
  week Input with a grid Output (as it used to be) left the filter inert for
  players. Week drives only the scoreboard and entry-date drives only the grid
  rows, so the split is clean rather than a workaround.
- **Entry-date change -> refresh the grid rows.** Coach-only in practice: the
  date picker and grid live inside the coach section.
- **Save click** -> persist the edited grid to RDS, then rebuild the scoreboard.
  The coach-write gate is re-checked HERE (not just trusted from the layout
  omitting the grid for players) -- the second half of the double-gate.
- **Recompute click** -> auto-score the day (`cauldron.score_day`, which never
  clobbers a coach's manual entries), then re-read. Also re-checks `is_coach`
  -- Recompute writes too.

`suppress_callback_exceptions=True` on the app (set in index.py) is what lets
Dash accept callbacks referencing ids absent from a given render.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
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


def _scoreboard(week_start, season):
    """Build ONLY the week-bounded scoreboard, fetching its four independent
    reads concurrently (each ~one RDS round trip). Used on Save, where the grid
    is being hidden so its rows don't need re-reading -- this is what makes Save
    snap shut instead of paying the grid recompute + a serial read chain."""
    cycle_id = f"{season}-c1"
    w_start, w_end = _week_bounds(week_start)
    with ThreadPoolExecutor(max_workers=4) as ex:
        f_daily = ex.submit(cauldron.read_daily, start=w_start, end=w_end)
        f_teams = ex.submit(cauldron.read_teams, cycle_id)
        f_scoring = ex.submit(cauldron.read_scoring)
        f_roster = ex.submit(_roster_names, season)
    return visual.scoreboard_view(f_daily.result(), f_teams.result(),
                                  f_scoring.result(), f_roster.result())


def _grid_data(play_date, season):
    """The coach grid's rows for `play_date` (independent of the selected week --
    the grid is a single day's entry sheet, the scoreboard is the week's total)."""
    cycle_id = f"{season}-c1"
    return grid._grid_rows(
        pitching_caps.lmu_pitchers(season), cauldron.read_scoring(),
        cauldron.read_teams(cycle_id), cauldron.read_daily(play_date), play_date,
    )


def register_callbacks(dash_app) -> None:

    @dash_app.callback(
        Output("cauldron-scoreboard", "children"),
        Input("cauldron-week", "date"),
        prevent_initial_call=True,
    )
    def _on_week(week_start):
        """EVERY account: pick a week, get that week's scoreboard. No coach-only
        component may be referenced here or the filter goes dead for players."""
        return _scoreboard(week_start, seasons.current_season())

    @dash_app.callback(
        Output("cauldron-grid", "data"),
        Input("cauldron-date", "date"),
        prevent_initial_call=True,
    )
    def _on_entry_date(play_date):
        """Coach-only in practice (the date picker ships inside the grid)."""
        return _grid_data(play_date, seasons.current_season())

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
        # The grid is being hidden, so DON'T re-read its rows (that was the slow
        # part of Save); only rebuild the scoreboard. Grid rows refresh next
        # time the date/week changes.
        scoreboard = _scoreboard(week_start, season)
        return no_update, scoreboard, "Saved.", False, _HIDDEN  # re-lock + hide
