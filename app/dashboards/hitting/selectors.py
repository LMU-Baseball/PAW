"""Role-aware selection helpers (pure functions of explicit role/id params).

A player is locked to their own data server-side; these functions never trust a
client-supplied hitter id for a player. `current_user` is read by layout/callbacks
and passed in, keeping this module testable in isolation. Ids are batter_tm_id.
"""
from __future__ import annotations

from app.data import hitting_wh


def resolve_batter(requested_id, *, is_coach: bool, own_trackman_id):
    """The batter id a request is allowed to view. Players are self-only."""
    if not is_coach:
        return int(own_trackman_id) if own_trackman_id is not None else None
    return int(requested_id) if requested_id not in (None, "") else None


def hitter_options(*, is_coach: bool, own_trackman_id) -> list[dict]:
    """Dropdown options for the hitter selector (value = batter_tm_id)."""
    if is_coach:
        df = hitting_wh.wh_lmu_hitters()
        return [{"label": str(r.Batter), "value": int(r.BatterId)}
                for r in df.itertuples()]
    if own_trackman_id is None:
        return []
    prof = hitting_wh.wh_player_profile(int(own_trackman_id))
    return [{"label": prof["name"] or str(own_trackman_id),
             "value": int(own_trackman_id)}]


def game_options(batter_tm_id) -> list[dict]:
    """Dropdown options (newest first) for a batter's games (value = game_id)."""
    if batter_tm_id is None:
        return []
    df = hitting_wh.wh_games_for_batter(int(batter_tm_id))
    return [{"label": str(r.GameLabel), "value": int(r.game_id)}
            for r in df.itertuples()]
