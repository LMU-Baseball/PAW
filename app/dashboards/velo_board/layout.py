"""Top Gun Velo Board dashboard shell: role-branched layout.

Every logged-in user (player or coach) sees the branded header, the Season/Week
filters (`grid.board_filters`) and the heat leaderboard -- the filters are pure
VIEW controls, so a player browses any season/week just like a coach.

A coach ALSO sees the Edit/Save buttons (`grid.coach_controls`), placed above
the filters in their own coach-only section -- players never receive those
controls in the component tree at all (the first half of the coach-write
double-gate; `callbacks.py`'s save callback re-checking `current_user.is_coach`
is the second half).
"""
from __future__ import annotations

from dash import dcc, html
from flask_login import current_user

from app.data import seasons
from app.data import velo_board
from app.dashboards import shell
from app.dashboards.velo_board import grid, visual


def serve_layout() -> html.Div:
    if not current_user.is_authenticated:
        return html.Div("Please log in.")
    is_coach = bool(getattr(current_user, "is_coach", False))

    season = seasons.current_season()
    week = velo_board.default_week_for(season)

    board = velo_board.board_rows(season, week)
    children = [
        dcc.Store(id="velo-selection", data={"season": season, "week": week}),
        shell.header(back_href="/pitching", back_label="← Pitching"),
        visual.top_gun_header(),
    ]
    # Control bar above the shared table: the Season/Week filters are for
    # EVERYONE; only a coach additionally gets the Edit/Save buttons on top.
    controls = []
    if is_coach:
        controls.append(html.Div(grid.coach_controls(), id="velo-coach-section"))
    controls.append(grid.board_filters(season, week))
    children.append(html.Div(controls,
                             style={"borderBottom": f"2px solid {shell.CRIMSON}",
                                    "backgroundColor": "rgba(255,255,255,0.55)"}))
    # ONE unified table for everyone (read-only leaderboard; a coach edits the
    # four editable columns in place). Always a DataTable so callbacks find it.
    children.append(html.Div(visual.board_table(board), id="velo-board",
                             style={"padding": "0 20px"}))
    return html.Div(children)
