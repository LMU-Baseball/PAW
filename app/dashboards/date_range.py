"""Shared date-range selection helpers for the stats dashboards (pure)."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from dash import dcc

ALL_IN_RANGE = "__all_in_range__"

PRESETS = [
    ("season", "This Season"), ("week", "Past Week"), ("month", "Past Month"),
    ("3months", "Past 3 Months"), ("6months", "Past 6 Months"),
    ("year", "Past Year"), ("custom", "Custom Range"),
]
_PRESET_DAYS = {"week": 7, "month": 30, "3months": 90, "6months": 181, "year": 365}


def preset_options() -> list[dict]:
    return [{"label": lbl, "value": val} for val, lbl in PRESETS]


def _as_date(d) -> date:
    if isinstance(d, date):
        return d
    return date.fromisoformat(str(d)[:10])


def season_block(anchor) -> tuple[date, date]:
    """Half-year block containing `anchor`: Jan-Jun -> Spring [Jan 1, anchor];
    Jul-Dec -> Fall [Jul 1, anchor]."""
    a = _as_date(anchor)
    start = date(a.year, 1, 1) if a.month <= 6 else date(a.year, 7, 1)
    return start, a


def preset_range(preset, anchor):
    """Resolve a preset to (start, end) anchored at `anchor`. None for 'custom'
    (the caller keeps the calendar's own dates)."""
    a = _as_date(anchor)
    if preset == "season":
        return season_block(a)
    days = _PRESET_DAYS.get(preset)
    if days is None:
        return None
    return a - timedelta(days=days), a


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


def date_control(id_prefix, anchor, *, min_date=None, max_date=None, preset="season",
                 start=None, end=None):
    """Preset dropdown + a calendar (shown only for 'custom'). The calendar keeps
    id f'{id_prefix}-daterange' so existing downstream callbacks are unchanged.
    Explicit `start`/`end` override the preset's default range (used to open on a
    specific day while keeping the full min/max bounds for widening)."""
    from dash import html
    rng = preset_range(preset, anchor) or (min_date, max_date)
    s0, e0 = rng
    start = start if start is not None else s0
    end = end if end is not None else e0
    return html.Div([
        dcc.Dropdown(id=f"{id_prefix}-date-preset", options=preset_options(),
                     value=preset, clearable=False, style={"minWidth": "175px"}),
        html.Div(
            date_picker(id_prefix, str(start) if start else None,
                        str(end) if end else None, min_date=min_date, max_date=max_date),
            id=f"{id_prefix}-cal-wrap",
            style={"display": "block" if preset == "custom" else "none",
                   "marginTop": "6px"}),
    ])


def game_options(games_df: pd.DataFrame, video_game_ids=None) -> list[dict]:
    """Dropdown options for in-range games, prepended with the aggregate sentinel.
    Games whose id is in `video_game_ids` are tagged with a 🎥 marker so coaches
    can see at a glance which games have video. Empty df -> [] (caller shows an
    empty state)."""
    if games_df is None or games_df.empty:
        return []
    vids = {int(g) for g in (video_game_ids or set())}
    opts = [{"label": f"All games in range ({len(games_df)})", "value": ALL_IN_RANGE}]
    for r in games_df.itertuples():
        gid = int(r.game_id)
        label = f"🎥 {r.GameLabel}" if gid in vids else str(r.GameLabel)
        opts.append({"label": label, "value": gid})
    return opts


def range_scoreboard_text(games_df: pd.DataFrame, start, end) -> str:
    n = 0 if games_df is None or games_df.empty else len(games_df)
    return f"{start} – {end} · {n} games"
