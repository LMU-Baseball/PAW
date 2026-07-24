"""Shared date-range selection helpers for the stats dashboards (pure)."""
from __future__ import annotations

import pandas as pd
from dash import dcc

ALL_IN_RANGE = "__all_in_range__"


def date_picker(id_prefix: str, start, end, min_date=None, max_date=None):
    """A styled calendar range picker. Component id = f'{id_prefix}-daterange'."""
    return dcc.DatePickerRange(
        id=f"{id_prefix}-daterange",
        start_date=start,
        end_date=end,
        min_date_allowed=min_date,
        max_date_allowed=max_date,
        display_format="YYYY-MM-DD",
        first_day_of_week=1,
        style={"backgroundColor": "white", "borderRadius": "6px"},
    )


def game_options(games_df: pd.DataFrame) -> list[dict]:
    """Dropdown options for in-range games, prepended with the aggregate sentinel.
    Empty df -> [] (caller shows an empty state)."""
    if games_df is None or games_df.empty:
        return []
    opts = [{"label": f"All games in range ({len(games_df)})", "value": ALL_IN_RANGE}]
    for r in games_df.itertuples():
        opts.append({"label": str(r.GameLabel), "value": int(r.game_id)})
    return opts


def range_scoreboard_text(games_df: pd.DataFrame, start, end) -> str:
    n = 0 if games_df is None or games_df.empty else len(games_df)
    return f"{start} – {end} · {n} games"
