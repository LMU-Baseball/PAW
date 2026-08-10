"""Academic-year season helpers.

A "season" is an academic year running **Aug 1 -> Jul 31**, labeled
`"YYYY/YYYY+1"` (e.g. `"2025/2026"` = Aug 2025 - Jul 2026 = Fall 2025 + Spring
2026). Used by the game dashboards' Season dropdown + the per-season precalc.
"""
from __future__ import annotations

from datetime import date

from app.db import query_df
from app.data.cache import cached

LMU_BATTER_TEAM = "LOY_LIO"
_NUMERIC_DATE = "Date REGEXP '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'"


def season_label_for(date_str) -> str:
    """Academic-year label for an ISO date. Months Aug-Dec belong to that
    calendar year's season; Jan-Jul belong to the prior year's season."""
    s = str(date_str)[:10]
    y, m = int(s[:4]), int(s[5:7])
    ay = y if m >= 8 else y - 1
    return f"{ay}/{ay + 1}"


def season_bounds(label: str) -> tuple[str, str]:
    """(start, end) ISO dates for a season label: Aug 1 -> Jul 31."""
    a, b = label.split("/")
    return f"{int(a)}-08-01", f"{int(b)}-07-31"


@cached
def available_seasons() -> list[str]:
    """Academic-year labels present in GAMES (LMU, numeric GameID), newest first."""
    df = query_df(
        f"SELECT DISTINCT Date FROM GAMES WHERE BatterTeam = :t AND {_NUMERIC_DATE}",
        {"t": LMU_BATTER_TEAM})
    labels = {season_label_for(d) for d in df["Date"]} if not df.empty else set()
    return sorted(labels, reverse=True)


def current_season() -> str:
    """The latest season that has data (the dropdown's default). Falls back to
    today's academic year only if GAMES is empty."""
    seasons = available_seasons()
    return seasons[0] if seasons else season_label_for(date.today().isoformat())
