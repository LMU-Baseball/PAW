"""Role-aware selection helpers for the pitching dashboard (pure functions).

A player is locked to their own data server-side. Ids are the RAW
`GAMES.PitcherId` (== a player's Trackman id) -- no surrogate mapping needed.
"""
from __future__ import annotations

from app.data import pitching_caps


def resolve_pitcher(requested_id, *, is_coach: bool, own_trackman_id):
    """The pitcher_id a request may view. Players are self-only."""
    if not is_coach:
        return int(own_trackman_id) if own_trackman_id is not None else None
    return int(requested_id) if requested_id not in (None, "") else None


def pitcher_options(*, is_coach: bool, own_trackman_id, season=None) -> list[dict]:
    """Dropdown options for the pitcher selector (value = PitcherId), scoped to
    the given academic-year season (default = current_season())."""
    if is_coach:
        df = pitching_caps.lmu_pitchers(season)
        return [{"label": str(r.Pitcher), "value": int(r.PitcherId)}
                for r in df.itertuples()]
    pid = resolve_pitcher(None, is_coach=False, own_trackman_id=own_trackman_id)
    if pid is None:
        return []
    return [{"label": pitching_caps.pitcher_name(pid), "value": pid}]


def outing_options(pitcher_id) -> list[dict]:
    if pitcher_id is None:
        return []
    df = pitching_caps.games_for_pitcher(int(pitcher_id))
    return [{"label": str(r.GameLabel), "value": str(r.game_id)}
            for r in df.itertuples()]
