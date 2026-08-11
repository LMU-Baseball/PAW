"""Competitive Cauldron dashboard shell: role-branched layout.

Every logged-in user (player or coach) sees the branded header + the
team scoreboard (`visual.scoreboard_view`). A coach ALSO sees the editable
daily grid (`grid.coach_grid`), placed above the scoreboard in its own
coach-only section -- players never receive the grid in the component tree
at all (the first half of the coach-write double-gate; `callbacks.py`'s
save/recompute callbacks re-checking `current_user.is_coach` is the second
half).
"""
from __future__ import annotations

from datetime import date

from dash import html
from flask_login import current_user

from app.data import pitching_caps
from app.data import seasons
from app.data.cauldron import read_daily, read_scoring, read_teams
from app.dashboards import shell
from app.dashboards.cauldron import grid, visual


def _default_play_date() -> str:
    return date.today().isoformat()


def _default_cycle(season: str) -> str:
    return f"{season}-c1"


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
    cycle = _default_cycle(season)
    roster_names = _roster_names(season)

    children = [shell.header(back_href="/pitching", back_label="← Pitching")]
    if is_coach:
        children.append(html.Div(grid.coach_grid(play_date, cycle, season), id="cauldron-coach-section"))
    children.append(visual.cauldron_header())
    children.append(html.Div(
        id="cauldron-scoreboard",
        children=visual.scoreboard_view(
            read_daily(), read_teams(cycle), read_scoring(), roster_names),
    ))
    return html.Div(children)
