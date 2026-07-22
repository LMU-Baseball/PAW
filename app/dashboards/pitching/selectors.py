"""Role-aware selection helpers for the pitching dashboard (pure functions).

A player is locked to their own data server-side. Ids are warehouse pitcher_id;
a player's own id is resolved from their Trackman raw id.
"""
from __future__ import annotations

from app.data import pitching as P


def resolve_pitcher(requested_id, *, is_coach: bool, own_trackman_id):
    """The pitcher_id a request may view. Players are self-only."""
    if not is_coach:
        if own_trackman_id is None:
            return None
        # Map the player's Trackman raw id -> a warehouse pitcher_id.
        return _pitcher_id_for_tm(int(own_trackman_id))
    return int(requested_id) if requested_id not in (None, "") else None


def _pitcher_id_for_tm(tm_id: int):
    from app.db import query_df
    df = query_df(
        """
        SELECT pitcher_id FROM fact_tm_game_pitch
         WHERE pitcher_tm_id = :tm AND pitcher_team = 'LOY_LIO'
         GROUP BY pitcher_id ORDER BY COUNT(*) DESC LIMIT 1
        """,
        {"tm": tm_id},
    )
    return None if df.empty else int(df.loc[0, "pitcher_id"])


def pitcher_options(*, is_coach: bool, own_trackman_id) -> list[dict]:
    if is_coach:
        df = P.wh_lmu_pitchers()
        return [{"label": str(r.Pitcher), "value": int(r.PitcherId)}
                for r in df.itertuples()]
    pid = resolve_pitcher(None, is_coach=False, own_trackman_id=own_trackman_id)
    if pid is None:
        return []
    return [{"label": P.pitcher_name(pid), "value": pid}]


def outing_options(pitcher_id) -> list[dict]:
    if pitcher_id is None:
        return []
    df = P.games_for_pitcher(int(pitcher_id))
    return [{"label": str(r.GameLabel), "value": int(r.game_id)}
            for r in df.itertuples()]
