"""Role-aware selection helpers for the catching dashboard (pure functions).

A player is locked to their own data server-side. Ids are the RAW
`GAMES.CatcherId` (== a player's Trackman id) -- no surrogate mapping needed.
"""
from __future__ import annotations

from app.data import catching_caps


def resolve_catcher(requested_id, *, is_coach: bool, own_trackman_id):
    """The catcher_id a request may view. Players are self-only."""
    if not is_coach:
        return int(own_trackman_id) if own_trackman_id is not None else None
    return int(requested_id) if requested_id not in (None, "") else None


def catcher_options(*, is_coach: bool, own_trackman_id) -> list[dict]:
    if is_coach:
        df = catching_caps.lmu_catchers()
        return [{"label": str(r.Catcher), "value": int(r.CatcherId)}
                for r in df.itertuples()]
    cid = resolve_catcher(None, is_coach=False, own_trackman_id=own_trackman_id)
    if cid is None:
        return []
    return [{"label": catching_caps.catcher_name(cid), "value": cid}]


def game_options(catcher_id) -> list[dict]:
    if catcher_id is None:
        return []
    df = catching_caps.games_for_catcher(int(catcher_id))
    return [{"label": str(r.GameLabel), "value": str(r.game_id)}
            for r in df.itertuples()]
