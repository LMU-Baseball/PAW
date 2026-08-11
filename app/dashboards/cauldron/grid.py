"""Competitive Cauldron coach grid: team assignment + daily entry/override.

`coach_grid` builds an editable `dash_table.DataTable`, one row per rostered
pitcher (`pitching_caps.lmu_pitchers(season)`), mirroring
`velo_board.grid.coach_grid`'s shape:

  - `player` is locked (name only, for mapping back on save `player_id` rides
    along in the row dict, hidden from the rendered columns -- same trick as
    velo_board's `pitcher_id`).
  - `team` is editable via a per-cell dropdown (`presentation: "dropdown"`,
    Team 1..4 options) rather than a plain text cell, so a coach can't
    typo a team name that then silently fails to group in the scoreboard.
    Pre-filled from `cauldron.read_teams(cycle_id)`.
  - One column per `cauldron.read_scoring()` metric, ordered by `sort_order`,
    labeled with the metric's `label`. AUTO metrics are pre-filled with
    today's stored `cauldron_daily` points when one exists, else scored live
    from `compute_player_day` + `score_value` (so a coach sees today's
    Trackman-driven result before ever touching Save); MANUAL metrics
    (`is_manual`) start blank -- there's no auto value to show. Every metric
    cell is editable: typing over an AUTO cell is the "override" path, typing
    into a MANUAL cell is the only way that metric ever gets scored.

A Date picker (`cauldron-date`) and a Cycle selector (`cauldron-cycle`) sit
above the grid. Cycle lifecycle isn't defined yet, so the selector is a plain
`dcc.Dropdown` seeded with just the current `cycle_id` -- a single default
cycle is enough for now; a real cycle picker is future work once cycles have
start/end dates of their own. Below the grid: **Save** (`cauldron-save`),
**Recompute auto** (`cauldron-recompute`), and a status line
(`cauldron-save-status`). No callbacks are wired here -- Task 6 owns the Dash
callback that reads this state and invokes `save_grid` /
`cauldron.score_day`.

`save_grid` maps the grid's edited rows back to RDS. Team: a non-blank `team`
cell -> `cauldron.set_team`. Metrics: the grid always shows POINTS (not a raw
stat), so whatever a coach types into a metric cell IS the points value to
store -- `save_grid` stores it straight as `points` (`raw_value=None`), rather
than re-running it through `score_value` (that would require guessing which
raw scale the coach meant to type). Blank/NaN metric cells are skipped
outright: no empty `cauldron_daily` row is written for a cell the coach left
untouched.

`source` tagging is NOT a blanket `'manual'` -- that would permanently defeat
Recompute the first time a coach ever hits Save on a day with Trackman data
(an untouched AUTO cell, once stored `'manual'`, is "manual-wins" forever
after; `score_day` would never refresh it again). Instead, for a MANUAL
metric (`is_manual` in `cauldron.read_scoring()`) any non-blank cell is
`source='manual'` (there's no auto baseline to compare against). For an AUTO
metric, the cell is compared against the SAME live baseline `coach_grid` used
to pre-fill it (`_auto_points`, i.e. `compute_player_day` + `score_value`
re-run fresh for this save): unchanged from that baseline -> `source='auto'`
(so Recompute can still refresh it later), different -> `source='manual'`
(a real coach override).
"""
from __future__ import annotations

import math

import pandas as pd
from dash import dash_table, dcc, html

from app.data import cauldron
from app.data import pitching_caps
from app.dashboards import shell

_TEAM_OPTIONS = ["Team 1", "Team 2", "Team 3", "Team 4"]

# Row keys that are never metric columns -- everything else in a grid row
# dict is a metric id (see `_grid_rows`/`save_grid`).
_NON_METRIC_KEYS = {"player_id", "player", "team"}


def _metric_columns(scoring: pd.DataFrame) -> list[dict]:
    """One editable numeric column per `cauldron.read_scoring()` row, already
    ordered by `sort_order` (read_scoring's own ORDER BY)."""
    return [
        {"name": row["label"] or row["metric"], "id": row["metric"],
         "editable": True, "type": "numeric"}
        for _, row in scoring.iterrows()
    ]


def _auto_points(pid, metric, scoring_row, play_date) -> int | None:
    """Live-score one AUTO metric for one pitcher/day via
    `compute_player_day` + `score_value`, for pre-filling a cell that has no
    stored `cauldron_daily` row yet. `None` when the pitcher has no tracked
    pitches that day (or the metric's raw value is `None` for the day)."""
    raw = cauldron.compute_player_day(pid, play_date).get(metric)
    return cauldron.score_value(metric, raw, scoring_row)


def _grid_rows(roster: pd.DataFrame, scoring: pd.DataFrame, teams: pd.DataFrame,
               daily: pd.DataFrame, play_date) -> list[dict]:
    """One dict per rostered pitcher: `player_id`/`player`/`team` plus one key
    per metric id, pre-filled per `coach_grid`'s docstring rules."""
    team_by_player: dict[int, str] = {}
    if teams is not None and not teams.empty:
        team_by_player = dict(zip(teams["player_id"].astype(int), teams["team"]))

    stored: dict[tuple[int, str], object] = {}
    if daily is not None and not daily.empty:
        for _, r in daily.iterrows():
            stored[(int(r["player_id"]), r["metric"])] = r["points"]

    rows = []
    for _, r in roster.iterrows():
        pid = int(r["PitcherId"])
        row = {"player_id": pid, "player": r["Pitcher"], "team": team_by_player.get(pid)}
        for _, srow in scoring.iterrows():
            metric = srow["metric"]
            key = (pid, metric)
            if key in stored:
                row[metric] = stored[key]
            elif bool(srow.get("is_manual")):
                row[metric] = None
            else:
                row[metric] = _auto_points(pid, metric, srow, play_date)
        rows.append(row)
    return rows


def coach_grid(play_date, cycle_id, season) -> html.Div:
    """The coach-facing editable grid: Date picker, Cycle selector, the
    editable DataTable itself (id `cauldron-grid`), and Save/Recompute
    buttons (`cauldron-save`/`cauldron-recompute`) + status line
    (`cauldron-save-status`)."""
    scoring = cauldron.read_scoring()
    roster = pitching_caps.lmu_pitchers(season)
    teams = cauldron.read_teams(cycle_id)
    daily = cauldron.read_daily(play_date)

    data = _grid_rows(roster, scoring, teams, daily, play_date)

    columns = [
        {"name": "Player", "id": "player", "editable": False},
        {"name": "Team", "id": "team", "editable": True, "presentation": "dropdown"},
    ] + _metric_columns(scoring)

    dropdown = {"team": {"options": [{"label": t, "value": t} for t in _TEAM_OPTIONS]}}

    controls = html.Div([
        html.Div([
            html.Label("Date", style={"color": "white", "fontWeight": "bold"}),
            dcc.DatePickerSingle(id="cauldron-date", date=play_date),
        ]),
        html.Div([
            html.Label("Cycle", style={"color": "white", "fontWeight": "bold"}),
            dcc.Dropdown(
                id="cauldron-cycle",
                options=[{"label": cycle_id, "value": cycle_id}],
                value=cycle_id, clearable=False,
                style={"minWidth": "130px"}),
        ]),
        html.Div([
            html.Button("Save", id="cauldron-save", n_clicks=0, style={
                "backgroundColor": shell.CRIMSON, "color": "white", "border": "none",
                "borderRadius": "4px", "padding": "8px 16px", "fontWeight": "bold",
                "cursor": "pointer", "marginRight": "8px"}),
            html.Button("Recompute auto", id="cauldron-recompute", n_clicks=0, style={
                "backgroundColor": "#2864A8", "color": "white", "border": "none",
                "borderRadius": "4px", "padding": "8px 16px", "fontWeight": "bold",
                "cursor": "pointer"}),
            html.Div(id="cauldron-save-status", style={"color": "white", "fontSize": "13px",
                                                         "marginTop": "4px"}),
        ]),
    ], style={"display": "flex", "gap": "20px", "alignItems": "flex-end",
              "padding": "12px 16px", "backgroundColor": shell.BANNER})

    grid = dash_table.DataTable(
        id="cauldron-grid",
        columns=columns,
        data=data,
        editable=True,
        dropdown=dropdown,
        style_table={"overflowX": "auto"},
        style_cell={"fontFamily": "Teko, sans-serif", "fontSize": "15px",
                    "padding": "4px 8px", "textAlign": "center"},
        style_header={"backgroundColor": shell.CRIMSON, "color": "white", "fontWeight": "bold"},
    )

    return html.Div([controls, grid])


def _coerce_numeric(value):
    """Blank/empty-string (and NaN) grid inputs -> None; everything else
    passes through unchanged."""
    if value is None or value == "":
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def save_grid(grid_data: list[dict], play_date, cycle_id, updated_by=None) -> None:
    """Map the coach grid's edited rows -> `cauldron_teams`/`cauldron_daily`
    writes. A filled `team` cell upserts that pitcher's team for `cycle_id`.
    Every other non-blank cell is a metric id -> a `cauldron_daily` row
    (`raw_value=None`, `points`=the cell's value) for `play_date`; blank
    cells are skipped, not written as empty rows.

    `source` per cell: a MANUAL metric is always `'manual'` when filled. An
    AUTO metric is `'auto'` when its value still matches the live
    `_auto_points` baseline (an untouched prefill -- Recompute may keep
    refreshing it), else `'manual'` (the coach typed over it). A metric id
    the current scoring config no longer recognizes falls back to `'manual'`
    (no baseline to compare against -- safest to treat as a deliberate
    entry)."""
    scoring = cauldron.read_scoring()
    scoring_by_metric = {row["metric"]: row for _, row in scoring.iterrows()}

    daily_rows = []
    for r in grid_data:
        pid = r.get("player_id")
        team = r.get("team")
        if team not in (None, ""):
            cauldron.set_team(pid, cycle_id, team, updated_by)

        for key, value in r.items():
            if key in _NON_METRIC_KEYS:
                continue
            points = _coerce_numeric(value)
            if points is None:
                continue

            srow = scoring_by_metric.get(key)
            if srow is not None and not bool(srow.get("is_manual")):
                baseline = _auto_points(pid, key, srow, play_date)
                source = "auto" if points == baseline else "manual"
            else:
                source = "manual"

            daily_rows.append({
                "player_id": pid,
                "play_date": play_date,
                "metric": key,
                "raw_value": None,
                "points": points,
                "source": source,
            })

    if daily_rows:
        cauldron.upsert_daily(daily_rows, updated_by=updated_by)
