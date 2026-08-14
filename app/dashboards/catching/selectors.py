"""Role-aware selection helpers for the catching dashboard (pure functions).

Team-transparent VIEW: any authenticated account may view any catcher, so these
return the full roster and trust the requested id regardless of role
(`own_trackman_id` is only a convenience default now; WRITE access is gated
separately, coach-only). Ids are the RAW `GAMES.CatcherId` (== a player's
Trackman id) -- no surrogate mapping needed.
"""
from __future__ import annotations

from app.data import catching_caps


def resolve_catcher(requested_id, *, is_coach: bool, own_trackman_id):
    """The catcher_id a request views: the requested id when given (any account),
    else the viewer's own id as a default, else None (layout picks a default)."""
    if requested_id not in (None, ""):
        return int(requested_id)
    return int(own_trackman_id) if own_trackman_id is not None else None


def catcher_options(*, is_coach: bool, own_trackman_id, season=None,
                     start=None, end=None) -> list[dict]:
    """Dropdown options for the catcher selector (value = CatcherId): the full
    roster for the given academic-year season (default = current_season()),
    further scoped to [start, end] when both are given. Every account sees the
    whole roster (team-transparent view)."""
    df = (catching_caps.lmu_catchers(season, start=start, end=end)
          if start is not None and end is not None
          else catching_caps.lmu_catchers(season))
    return [{"label": str(r.Catcher), "value": int(r.CatcherId)}
            for r in df.itertuples()]


def game_options(catcher_id) -> list[dict]:
    if catcher_id is None:
        return []
    df = catching_caps.games_for_catcher(int(catcher_id))
    return [{"label": str(r.GameLabel), "value": str(r.game_id)}
            for r in df.itertuples()]
