"""Top Gun Velo Board — coach-editable grid + save-to-RDS mapping.

`coach_grid` builds the FIRST `editable=True` DataTable in the repo: one row
per rostered pitcher (`velo_board.grid_rows`), with `velo_goal`/`assessment`
as the primary coach inputs and velo_avg/velo_max/max_pr left editable too,
per the spec's "coaches can override any auto cell" -- `grid_rows` makes a
saved override to any of those stick (stored snapshot wins over recomputed
Trackman on the next render). `pitcher_name` stays locked, and so do
change_avg/change_max: those are always COMPUTED (this week's shown
velo_avg/velo_max minus the pitcher's previous stored week), never stored,
so editing them would be silently discarded on re-render. A Season dropdown
and a Week date-picker sit above the grid; a Save button + status line below
it. No callbacks are wired here -- Task 6 owns the Dash callback that reads
`dcc.Dropdown`/`DatePickerSingle`/DataTable state, snaps the picked date to
its Monday via `velo_board.week_start_for`, and calls `save_rows`.
"""
from __future__ import annotations

import math

import pandas as pd
from dash import dash_table, dcc, html

from app.data import velo_board
from app.data.seasons import available_seasons
from app.dashboards import shell

_GOLD = "#F2C744"          # new-PR row highlight, echoing the reference sheet's yellow PR flag

_COLUMNS = [
    {"name": "Pitcher", "id": "pitcher_name", "editable": False},
    {"name": "Velo Avg", "id": "velo_avg", "editable": True, "type": "numeric"},
    {"name": "Velo Max", "id": "velo_max", "editable": True, "type": "numeric"},
    {"name": "Velo Goal", "id": "velo_goal", "editable": True, "type": "numeric"},
    {"name": "Assessment", "id": "assessment", "editable": True, "type": "numeric"},
    {"name": "Max PR", "id": "max_pr", "editable": True, "type": "numeric"},
    {"name": "Chg Avg", "id": "change_avg", "editable": False, "type": "numeric"},
    {"name": "Chg Max", "id": "change_max", "editable": False, "type": "numeric"},
]

_STYLE_DATA_CONDITIONAL = [
    {
        # New-PR row: this week's velo_max IS the pitcher's running max_pr
        # (and both are populated -- excludes rows where neither threw).
        "if": {"filter_query": "{velo_max} = {max_pr} && {velo_max} is not blank"},
        "backgroundColor": _GOLD,
        "color": shell.CRIMSON,
        "fontWeight": "bold",
    },
]


def _grid_columns(df: pd.DataFrame) -> list[dict]:
    """`_COLUMNS` narrowed to whatever `df` actually has, so a caller with a
    thinner frame (e.g. an empty roster) doesn't blow up the DataTable."""
    return [c for c in _COLUMNS if c["id"] in df.columns]


_LABEL_STYLE = {"color": shell.CRIMSON, "fontWeight": "bold", "fontSize": "13px",
                "textTransform": "uppercase", "letterSpacing": "1px",
                "display": "block", "marginBottom": "4px", "textAlign": "center"}


def coach_grid(season_label: str, week_start: str) -> html.Div:
    """The coach-facing editable grid: a centered Season + Week filter row
    (one line, directly under the emblem), then a clearly-labeled editable
    DataTable (id `velo-grid`) whose numbers a coach can change, and a Save
    button (id `velo-save`) that writes them to the database + a status line
    (id `velo-save-status`)."""
    df = velo_board.grid_rows(season_label, week_start)
    data = df.to_dict("records")  # pitcher_id rides along, hidden from _COLUMNS

    # Centered, single-line filter row under the emblem.
    filters = html.Div([
        html.Div([
            html.Label("Season", style=_LABEL_STYLE),
            dcc.Dropdown(
                id="velo-season",
                options=[{"label": s, "value": s} for s in available_seasons()],
                value=season_label, clearable=False,
                style={"minWidth": "150px"}),
        ]),
        html.Div([
            html.Label("Week (starts Monday)", style=_LABEL_STYLE),
            dcc.DatePickerSingle(id="velo-week", date=week_start),
        ]),
    ], style={"display": "flex", "gap": "28px", "justifyContent": "center",
              "alignItems": "flex-end", "flexWrap": "wrap", "padding": "16px 16px 8px"})

    # Grid starts LOCKED (editable=False). "Edit" unlocks it; "Save" persists
    # and re-locks -- see callbacks.py. This is what makes the Edit button do
    # something visible (before, it was just a static label).
    grid = dash_table.DataTable(
        id="velo-grid",
        columns=_grid_columns(df),
        data=data,
        editable=False,
        style_table={"overflowX": "auto"},
        style_cell={"fontFamily": "Teko, sans-serif", "fontSize": "15px",
                    "padding": "4px 8px", "textAlign": "center"},
        style_header={"backgroundColor": shell.CRIMSON, "color": "white", "fontWeight": "bold"},
        style_data_conditional=_STYLE_DATA_CONDITIONAL,
    )

    buttons = shell.edit_save_buttons("velo-edit", "velo-save", "velo-save-status")

    # Buttons on top; the editable grid table lives in a wrapper hidden until
    # Edit is pressed (Save hides it again). Season/Week filters stay visible --
    # Season drives the read-only leaderboard below.
    grid_wrap = html.Div(grid, id="velo-grid-wrap",
                         style={"display": "none", "padding": "0 16px"})

    return html.Div([buttons, filters, grid_wrap],
                    style={"borderBottom": f"2px solid {shell.CRIMSON}",
                           "backgroundColor": "rgba(255,255,255,0.55)"})


def _coerce_numeric(value):
    """Blank/empty-string (and NaN) numeric grid inputs -> None; everything
    else passes through unchanged for `velo_board.upsert_entries`'s own
    `_clean` to scrub."""
    if value is None or value == "":
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def save_rows(grid_data: list[dict], season_label: str, week_start: str, updated_by=None) -> None:
    """Map the coach grid's edited rows -> `velo_board_entries` rows and
    persist the whole week in one `upsert_entries` call."""
    rows = []
    for r in grid_data:
        rows.append({
            "pitcher_id": r.get("pitcher_id"),
            "pitcher_name": r.get("pitcher_name"),
            "season_label": season_label,
            "week_start": week_start,
            "velo_avg": _coerce_numeric(r.get("velo_avg")),
            "velo_max": _coerce_numeric(r.get("velo_max")),
            "velo_goal": _coerce_numeric(r.get("velo_goal")),
            "assessment": _coerce_numeric(r.get("assessment")),
            "max_pr": _coerce_numeric(r.get("max_pr")),
        })
    velo_board.upsert_entries(rows, updated_by=updated_by)
