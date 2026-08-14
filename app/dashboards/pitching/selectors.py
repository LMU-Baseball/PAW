"""Role-aware selection helpers for the pitching dashboard (pure functions).

Team-transparent VIEW: any authenticated account may view any pitcher, so these
return the full roster and trust the requested id regardless of role
(`own_trackman_id` is only a convenience default now; WRITE access is gated
separately, coach-only). Ids are the RAW `GAMES.PitcherId` (== a player's
Trackman id) -- no surrogate mapping needed.
"""
from __future__ import annotations

from app.data import pitching_caps


def resolve_pitcher(requested_id, *, is_coach: bool, own_trackman_id):
    """The pitcher_id a request views: the requested id when given (any account),
    else the viewer's own id as a default, else None (layout picks a default)."""
    if requested_id not in (None, ""):
        return int(requested_id)
    return int(own_trackman_id) if own_trackman_id is not None else None


def pitcher_options(*, is_coach: bool, own_trackman_id, season=None,
                     start=None, end=None) -> list[dict]:
    """Dropdown options for the pitcher selector (value = PitcherId): the full
    roster for the given academic-year season (default = current_season()),
    further scoped to [start, end] when both are given. Every account sees the
    whole roster (team-transparent view)."""
    df = (pitching_caps.lmu_pitchers(season, start=start, end=end)
          if start is not None and end is not None
          else pitching_caps.lmu_pitchers(season))
    return [{"label": str(r.Pitcher), "value": int(r.PitcherId)}
            for r in df.itertuples()]


def outing_options(pitcher_id) -> list[dict]:
    if pitcher_id is None:
        return []
    df = pitching_caps.games_for_pitcher(int(pitcher_id))
    return [{"label": str(r.GameLabel), "value": str(r.game_id)}
            for r in df.itertuples()]
