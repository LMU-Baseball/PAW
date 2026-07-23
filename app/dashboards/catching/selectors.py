"""Role-aware selection helpers for the catching dashboard (pure functions).

A player is locked to their own data server-side. Ids are warehouse catcher_id;
a player's own id is resolved from their Trackman raw id.
"""
from __future__ import annotations

from app.data import catching as C


def resolve_catcher(requested_id, *, is_coach: bool, own_trackman_id):
    """The catcher_id a request may view. Players are self-only."""
    if not is_coach:
        if own_trackman_id is None:
            return None
        return _catcher_id_for_tm(int(own_trackman_id))
    return int(requested_id) if requested_id not in (None, "") else None


def _catcher_id_for_tm(tm_id: int):
    from app.db import query_df
    df = query_df(
        """
        SELECT catcher_id FROM fact_tm_game_pitch
         WHERE catcher_tm_id = :tm AND pitcher_team = :lmu
           AND catcher_id IS NOT NULL
         GROUP BY catcher_id ORDER BY COUNT(*) DESC LIMIT 1
        """,
        {"tm": tm_id, "lmu": C.LMU_PITCHER_TEAM},
    )
    return None if df.empty else int(df.loc[0, "catcher_id"])


def catcher_options(*, is_coach: bool, own_trackman_id) -> list[dict]:
    if is_coach:
        df = C.wh_lmu_catchers()
        return [{"label": str(r.Catcher), "value": int(r.CatcherId)}
                for r in df.itertuples()]
    cid = resolve_catcher(None, is_coach=False, own_trackman_id=own_trackman_id)
    if cid is None:
        return []
    return [{"label": C.catcher_name(cid), "value": cid}]


def game_options(catcher_id) -> list[dict]:
    if catcher_id is None:
        return []
    df = C.games_for_catcher(int(catcher_id))
    return [{"label": str(r.GameLabel), "value": int(r.game_id)}
            for r in df.itertuples()]
