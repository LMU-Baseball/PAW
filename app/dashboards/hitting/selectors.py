"""Role-aware selection helpers (pure functions of explicit role/id params).

Team-transparent VIEW: any authenticated account may view any hitter, so these
return the full roster and trust the requested id regardless of role. The
`is_coach`/`own_trackman_id` params are retained (callers pass them unchanged);
`own_trackman_id` now only supplies a convenience default. WRITE access is gated
separately (coach-only) in the dashboards. Ids are batter_tm_id.
"""
from __future__ import annotations

from app.data import hitting_caps


def resolve_batter(requested_id, *, is_coach: bool, own_trackman_id):
    """The batter id a request views: the requested id when given (any account),
    else the viewer's own id as a default, else None (layout picks a default)."""
    if requested_id not in (None, ""):
        return int(requested_id)
    return int(own_trackman_id) if own_trackman_id is not None else None


def hitter_options(*, is_coach: bool, own_trackman_id, season=None,
                    start=None, end=None) -> list[dict]:
    """Dropdown options for the hitter selector (value = batter_tm_id): the full
    roster for the given academic-year season (default = current_season()),
    further scoped to [start, end] when both are given. Every account sees the
    whole roster (team-transparent view)."""
    df = (hitting_caps.lmu_hitters(season, start=start, end=end)
          if start is not None and end is not None
          else hitting_caps.lmu_hitters(season))
    return [{"label": str(r.Batter), "value": int(r.BatterId)}
            for r in df.itertuples()]


def game_options(batter_tm_id) -> list[dict]:
    """Dropdown options (newest first) for a batter's games (value = game_id)."""
    if batter_tm_id is None:
        return []
    df = hitting_caps.games_for_batter(int(batter_tm_id))
    return [{"label": str(r.GameLabel), "value": str(r.game_id)}
            for r in df.itertuples()]
