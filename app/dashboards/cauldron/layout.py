"""Competitive Cauldron dashboard shell: role-branched layout.

Every logged-in user (player or coach) sees the branded header, the Season/Week
filters (`grid.season_week_filters`) and the team scoreboard
(`visual.scoreboard_view`) -- the selectors are pure VIEW controls, so a player
browses seasons/weeks just like a coach. Season is the outer scope: it picks the
roster, the `{season}-c1` cycle the teams come from, and the week the picker
opens on.

A coach ALSO sees the editable daily grid (`grid.coach_grid`), placed above the
filters in its own coach-only section -- players never receive the grid in the
component tree at all (the first half of the coach-write double-gate;
`callbacks.py`'s save/recompute callbacks re-checking `current_user.is_coach`
is the second half). The grid's own **Entry date** picker stays inside it: that
one chooses the day being written to, so it is an edit control, not a filter.
"""
from __future__ import annotations

from datetime import date, timedelta

from dash import html
from flask_login import current_user

from app.data import pitching_caps
from app.data import seasons
from app.data import velo_board
from app.data.cauldron import read_daily, read_scoring, read_teams
from app.dashboards import shell
from app.dashboards.cauldron import grid, visual


def _default_play_date() -> str:
    return date.today().isoformat()


def _default_cycle(season: str) -> str:
    return f"{season}-c1"


def _week_bounds(week_start: str) -> tuple[str, str]:
    """Inclusive Mon..Sun window for a Monday `week_start`."""
    end = (date.fromisoformat(week_start) + timedelta(days=6)).isoformat()
    return week_start, end


def _roster_names(season: str) -> dict:
    roster = pitching_caps.lmu_pitchers(season)
    if roster.empty:
        return {}
    return dict(zip(roster["PitcherId"].astype(int), roster["Pitcher"]))


def serve_layout() -> html.Div:
    if not current_user.is_authenticated:
        return html.Div("Please log in.")
    is_coach = bool(getattr(current_user, "is_coach", False))

    season = seasons.current_season()
    play_date = _default_play_date()
    week = velo_board.default_week_for(season)
    cycle = _default_cycle(season)
    roster_names = _roster_names(season)
    w_start, w_end = _week_bounds(week)

    children = [
        shell.header(back_href="/pitching", back_label="← Pitching"),
        visual.cauldron_header(),
    ]
    # Buttons + the (hidden-until-edit) grid live directly under the emblem,
    # coach-only. The Week filter below them is for EVERYONE -- it only chooses
    # which week the shared scoreboard totals.
    controls = []
    if is_coach:
        controls.append(html.Div(grid.coach_grid(play_date, week, season),
                                 id="cauldron-coach-section"))
    controls.append(grid.season_week_filters(season, week))
    children.append(html.Div(controls,
                             style={"borderBottom": f"2px solid {shell.CRIMSON}",
                                    "backgroundColor": "rgba(255,255,255,0.55)"}))
    # Weekly scoreboard: only the selected week's daily points (reset each week).
    children.append(html.Div(
        id="cauldron-scoreboard",
        children=visual.scoreboard_view(
            read_daily(start=w_start, end=w_end), read_teams(cycle),
            read_scoring(), roster_names),
    ))
    return html.Div(children)
