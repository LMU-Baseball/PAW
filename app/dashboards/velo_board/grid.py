"""Top Gun Velo Board coach controls + save mapping.

The board is now ONE unified table (`visual.board_table`, id `velo-grid`) that
everyone sees read-only and a coach edits IN PLACE. This module owns:

- `board_filters(season, week)`: the Season/Week selectors, rendered for EVERY
  account. They only choose WHICH rows the shared table shows, so a player
  browses seasons/weeks exactly like a coach (team-transparent view).
- `coach_controls()`: the coach-only Edit/Save buttons + status line (no table
  and no filters -- the table is shared, rendered by `layout` for all users).
- `save_board(grid_data, season, week, updated_by)`: maps the edited table rows
  back to storage. Velo Goal + Assessment persist WEEKLY to `velo_board_entries`
  (`upsert_entries`). Season Max / Season Avg are SEASON-level coach corrections
  written to `velo_board_overrides` (`set_override`) ONLY where the coach's
  value differs from the computed leaderboard baseline -- so an untouched row
  still surfaces a fresh higher reading, and reverting a cell to the baseline
  clears the override.
"""
from __future__ import annotations

import math

from dash import dcc, html

from app.data import velo_board
from app.data.seasons import available_seasons, season_bounds
from app.dashboards import shell

_LABEL_STYLE = {"color": shell.CRIMSON, "fontWeight": "bold", "fontSize": "13px",
                "textTransform": "uppercase", "letterSpacing": "1px",
                "display": "block", "marginBottom": "4px", "textAlign": "center"}


def board_filters(season_label: str, week_start: str) -> html.Div:
    """A centered Season/Week selector row, rendered for EVERY account.

    These are pure VIEW controls -- they pick which season/week the shared
    `velo-grid` table shows -- so players get them too. Write access stays
    coach-only via `coach_controls` + the save callback's `is_coach` re-check."""
    _s_start, _s_end = season_bounds(season_label)
    return html.Div([
        html.Div([
            html.Label("Season", style=_LABEL_STYLE),
            dcc.Dropdown(
                id="velo-season",
                options=[{"label": s, "value": s} for s in available_seasons()],
                value=season_label, clearable=False, style={"minWidth": "150px"}),
        ]),
        html.Div([
            html.Label("Week (starts Monday)", style=_LABEL_STYLE),
            # Bounded to the selected season so the two controls can't drift
            # apart; the season callback re-bounds + snaps this on a change.
            dcc.DatePickerSingle(
                id="velo-week", date=week_start,
                min_date_allowed=_s_start, max_date_allowed=_s_end),
        ]),
    ], style={"display": "flex", "gap": "28px", "justifyContent": "center",
              "alignItems": "flex-end", "flexWrap": "wrap", "padding": "12px 16px"})


def coach_controls() -> html.Div:
    """Coach-only Edit/Save buttons + status line. The editable table itself is
    the shared `velo-grid` rendered by `layout`; the Season/Week filters are
    `board_filters`, which every account gets."""
    return html.Div(
        shell.edit_save_buttons("velo-edit", "velo-save", "velo-save-status"))


def _coerce_numeric(value):
    """Blank/empty-string (and NaN) grid inputs -> None; everything else passes
    through for `upsert_entries`/`set_override`'s own scrub."""
    if value is None or value == "":
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _round1(v):
    """Round to 1 decimal for baseline comparison, or None if missing."""
    if v is None:
        return None
    try:
        if math.isnan(float(v)):
            return None
        return round(float(v), 1)
    except (TypeError, ValueError):
        return None


def save_board(grid_data: list[dict], season_label: str, week_start: str,
               updated_by=None) -> None:
    """Persist the edited unified table: weekly velo_goal/assessment ->
    `velo_board_entries`; changed season_max/season_avg -> `velo_board_overrides`."""
    entry_rows = [{
        "pitcher_id": r.get("pitcher_id"),
        "pitcher_name": r.get("pitcher_name"),
        "season_label": season_label,
        "week_start": week_start,
        "velo_goal": _coerce_numeric(r.get("velo_goal")),
        "assessment": _coerce_numeric(r.get("assessment")),
    } for r in grid_data if r.get("pitcher_id") is not None]
    velo_board.upsert_entries(entry_rows, updated_by=updated_by)

    baseline = velo_board.leaderboard(season_label)
    base_by_name = ({row["pitcher_name"]: row for _, row in baseline.iterrows()}
                    if baseline is not None and not baseline.empty else {})
    for r in grid_data:
        pid = r.get("pitcher_id")
        if pid is None:
            continue
        base = base_by_name.get(r.get("pitcher_name"))
        bm = _round1(base["season_max"]) if base is not None else None
        ba = _round1(base["season_avg"]) if base is not None else None
        gm = _round1(_coerce_numeric(r.get("season_max")))
        ga = _round1(_coerce_numeric(r.get("season_avg")))
        # override only a value the coach actually CHANGED vs. the baseline;
        # a match writes NULL (no override) so fresh readings still surface.
        om = gm if (gm is not None and gm != bm) else None
        oa = ga if (ga is not None and ga != ba) else None
        velo_board.set_override(pid, season_label, season_max=om, season_avg=oa,
                                updated_by=updated_by)
