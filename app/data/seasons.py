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
def _games_seasons() -> set[str]:
    """Academic-year labels with real GAMES rows (LMU, numeric GameID). Private:
    the GAMES-only view that current_season() relies on to keep its "latest season
    WITH real data" behavior, kept separate from available_seasons()'s public list
    (which additionally always includes today's calendar season -- see below)."""
    df = query_df(
        f"SELECT DISTINCT Date FROM GAMES WHERE BatterTeam = :t AND {_NUMERIC_DATE}",
        {"t": LMU_BATTER_TEAM})
    return {season_label_for(d) for d in df["Date"]} if not df.empty else set()


@cached
def available_seasons() -> list[str]:
    """Academic-year labels present in GAMES (LMU, numeric GameID), newest first, ALWAYS
    including today's actual calendar academic-year label even if GAMES has zero rows for
    it yet.

    Without this, a Season dropdown built from this list has a hard ceiling: once the last
    labeled season ends, no later season is ever selectable until a GAMES row for it exists
    -- which for Velo Board/Cauldron (backed by BULLPEN, not GAMES) can be months after the
    data a coach actually needs is already flowing. Purely additive: this can only ADD the
    current label to what GAMES-derived data already reports, never remove or reorder an
    existing entry."""
    labels = set(_games_seasons())
    labels.add(season_label_for(date.today().isoformat()))
    return sorted(labels, reverse=True)


def current_season() -> str:
    """Today's real calendar academic-year label -- the dropdown default for
    catching/hitting/pitching (and everything else that defaults off this).

    Used to prefer the latest season WITH real GAMES data instead, falling
    back to today's calendar season only if GAMES was entirely empty -- a
    guard against defaulting onto a blank page before any data existed for
    the new season. That guard is no longer needed: `app.data.lmu_roster`
    unions each season's rostered players in as placeholder rows wherever
    `lmu_pitchers`/`lmu_hitters`/`lmu_catchers` are read, so the current
    season's view is never actually empty, even on day one before any
    Trackman data exists for it."""
    return season_label_for(date.today().isoformat())
