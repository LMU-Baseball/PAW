"""Role-aware selection helpers for the bullpen dashboard (pure functions).

A player is locked to their own data server-side. BULLPEN.PitcherId IS the
raw Trackman id, so a player's own id == their user.trackman_id (no mapping).
"""
from __future__ import annotations

from app.data import bullpen as B


def resolve_pitcher(requested_id, *, is_coach: bool, own_trackman_id):
    """The PitcherId a request may view. Players are self-only."""
    if not is_coach:
        return int(own_trackman_id) if own_trackman_id is not None else None
    return int(requested_id) if requested_id not in (None, "") else None


def pitcher_options(*, is_coach: bool, own_trackman_id, start=None, end=None) -> list[dict]:
    """Pitcher dropdown options, scoped to [start, end] when both are given
    (no args = every LMU pitcher who's ever had a bullpen). Date-scoping is
    coach only -- a player's own option is never filtered by date, so
    narrowing the range can't hide a player from their own dashboard."""
    if is_coach:
        df = B.lmu_bullpen_pitchers(start=start, end=end)
        return [{"label": str(r.pitcher), "value": int(r.pitcher_id)}
                for r in df.itertuples()]
    pid = resolve_pitcher(None, is_coach=False, own_trackman_id=own_trackman_id)
    if pid is None:
        return []
    return [{"label": B.pitcher_name(pid) or str(pid), "value": pid}]


def session_dropdown_options(sessions_df) -> list[dict]:
    """Session-date dropdown options (newest first) from B.session_options()."""
    if sessions_df is None or sessions_df.empty:
        return []
    return [{"label": f"{r.date} ({int(r.pitches)})", "value": str(r.date)}
            for r in sessions_df.itertuples()]
