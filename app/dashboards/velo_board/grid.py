"""Top Gun Velo Board coach controls + save mapping.

The board is now ONE unified table (`visual.board_table`, id `velo-grid`) that
everyone sees read-only and a coach edits IN PLACE. This module owns:

- `board_filters(season, cycle)`: the Season/Cycle selectors, rendered for
  EVERY account. They only choose WHICH rows the shared table shows, so a
  player browses seasons/cycles exactly like a coach (team-transparent
  view). Cycle replaced a Week date-picker 2026-09-22 (Brad) -- Assessment
  and Velo Goal are both cycle-scoped values, not weekly ones, so a Week
  filter no longer matched what the grid actually showed. Fall/Spring only
  (switches Jan 1, `velo_board.VELO_CYCLES`) -- the velo board's own
  2-cycle split, not Built on the Bluff's 3-cycle Fall/Winter/Spring
  (same date, Brad: "remove winter as a cycle").
- `coach_controls()`: the coach-only Edit/Save buttons + status line (no table
  and no filters -- the table is shared, rendered by `layout` for all users).
- `save_board(grid_data, season, cycle, updated_by)`: maps the edited table
  rows back to storage. Velo Goal + Assessment persist to
  `velo_board_cycle_overrides` (`set_cycle_override`) -- Assessment only
  written when the coach's value differs from the auto cycle-bullpen
  baseline (`velo_board.cycle_assessment`), same "no-op unless changed"
  idiom Season Max/Avg already use. Season Max / Season Avg are SEASON-level
  coach corrections written to `velo_board_overrides` (`set_override`) ONLY
  where the coach's value differs from the computed leaderboard baseline --
  so an untouched row still surfaces a fresh higher reading, and reverting a
  cell to the baseline clears the override.
"""
from __future__ import annotations

import math

from dash import dcc, html

from app.data import velo_board
from app.data.seasons import available_seasons
from app.dashboards import shell

_LABEL_STYLE = {"color": shell.CRIMSON, "fontWeight": "bold", "fontSize": "13px",
                "textTransform": "uppercase", "letterSpacing": "1px",
                "display": "block", "marginBottom": "4px", "textAlign": "center"}


def board_filters(season_label: str, cycle: str) -> html.Div:
    """A centered Season/Cycle selector row, rendered for EVERY account.

    These are pure VIEW controls -- they pick which season/cycle the shared
    `velo-grid` table shows -- so players get them too. Write access stays
    coach-only via `coach_controls` + the save callback's `is_coach` re-check."""
    return html.Div([
        html.Div([
            html.Label("Season", style=_LABEL_STYLE),
            dcc.Dropdown(
                id="velo-season",
                options=[{"label": s, "value": s} for s in available_seasons()],
                value=season_label, clearable=False, style={"minWidth": "150px"}),
        ]),
        html.Div([
            html.Label("Cycle", style=_LABEL_STYLE),
            dcc.Dropdown(
                id="velo-cycle",
                options=[{"label": c, "value": c} for c in velo_board.VELO_CYCLES],
                value=cycle, clearable=False, style={"minWidth": "130px"}),
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


def save_board(grid_data: list[dict], season_label: str, cycle: str,
               updated_by=None) -> None:
    """Persist the edited unified table: Velo Goal (typed as-is) + Assessment
    (only when changed vs. the cycle's auto bullpen baseline) both go to
    `velo_board_cycle_overrides`; changed season_max/season_avg ->
    `velo_board_overrides`."""
    baseline = velo_board.leaderboard(season_label)
    base_by_name = ({row["pitcher_name"]: row for _, row in baseline.iterrows()}
                    if baseline is not None and not baseline.empty else {})
    auto_assess = velo_board.cycle_assessment(season_label, cycle)
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

        ba_auto = _round1(auto_assess.get(int(pid)))
        ga_val = _round1(_coerce_numeric(r.get("assessment")))
        oassess = ga_val if (ga_val is not None and ga_val != ba_auto) else None
        velo_board.set_cycle_override(
            pid, season_label, cycle,
            velo_goal=_coerce_numeric(r.get("velo_goal")), assessment=oassess,
            updated_by=updated_by)
