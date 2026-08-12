"""Top Gun Velo Board dashboard shell: role-branched layout.

Every logged-in user (player or coach) sees the branded header + the
player-facing heat leaderboard. A coach ALSO sees the editable weekly grid
(`grid.coach_grid`), placed above the leaderboard in its own coach-only
section -- players never receive the grid in the component tree at all (the
first half of the coach-write double-gate; `callbacks.py`'s save callback
re-checking `current_user.is_coach` is the second half).
"""
from __future__ import annotations

from datetime import date

from dash import dcc, html
from flask_login import current_user

from app.data import seasons
from app.data import velo_board
from app.dashboards import shell
from app.dashboards.velo_board import grid, visual


def _default_week(season_label: str) -> str:
    """The most-recent sensible week inside `season_label`: today's week if
    the season is still in progress (today falls within its bounds), else
    the season's final week (today is past a completed season's end, or --
    edge case -- before its start)."""
    start, end = seasons.season_bounds(season_label)
    today = date.today().isoformat()
    anchor = min(today, end)
    if anchor < start:
        anchor = start
    return velo_board.week_start_for(anchor)


def serve_layout() -> html.Div:
    if not current_user.is_authenticated:
        return html.Div("Please log in.")
    is_coach = bool(getattr(current_user, "is_coach", False))

    season = seasons.current_season()
    week = _default_week(season)

    children = [
        dcc.Store(id="velo-selection", data={"season": season, "week": week}),
        shell.header(back_href="/pitching", back_label="← Pitching"),
        visual.top_gun_header(),
    ]
    # Filters + the editable grid live directly under the emblem, coach-only.
    if is_coach:
        children.append(html.Div(grid.coach_grid(season, week), id="velo-coach-section"))
    children.append(html.Div(
        id="velo-leaderboard",
        children=visual.leaderboard_view(velo_board.leaderboard(season)),
    ))
    return html.Div(children)
