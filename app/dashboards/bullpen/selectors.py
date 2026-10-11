"""Role-aware selection helpers for the bullpen dashboard (pure functions).

Team-transparent VIEW: any authenticated account may view any bullpen, so these
return the full roster and trust the requested id regardless of role
(`own_trackman_id` is only a convenience default now; WRITE access is gated
separately, coach-only). BULLPEN.PitcherId IS the raw Trackman id.
"""
from __future__ import annotations

from app.data import bullpen as B


def resolve_pitcher(requested_id, *, is_coach: bool, own_trackman_id):
    """The PitcherId a request views: the requested id when given (any account),
    else the viewer's own id as a default, else None (layout picks a default).

    A caller doesn't need to pre-expand this through `B.pitcher_ids_for` --
    every `app.data.bullpen` read that takes a `pitcher_id` already does that
    expansion itself (see that module's 2026-09-27 docstring notes)."""
    if requested_id not in (None, ""):
        return int(requested_id)
    return int(own_trackman_id) if own_trackman_id is not None else None


def pitcher_options(*, is_coach: bool, own_trackman_id, start=None, end=None) -> list[dict]:
    """Pitcher dropdown options, scoped to [start, end] when both are given
    (no args = every LMU pitcher who's ever had a bullpen). Every account sees
    the whole roster (team-transparent view). ONE option per distinct display
    name -- `B.lmu_bullpen_pitchers` already merges a player logged under more
    than one BULLPEN PitcherId (Trackman device re-pairings) into a single
    row; see that function's 2026-09-27 docstring for why (Brad: "I don't
    want multiple Matt Morenos to select from, I just want all of his
    bullpens under one name")."""
    df = B.lmu_bullpen_pitchers(start=start, end=end)
    return [{"label": str(r.pitcher), "value": int(r.pitcher_id)}
            for r in df.itertuples()]


ALL_SESSIONS = "all"


def session_dropdown_options(sessions_df) -> list[dict]:
    """Session-date dropdown options (newest first) from B.session_options(),
    led by an "All sessions in range" option once there's more than one
    session -- a pitcher rarely throws every pitch type in one pen, so the
    season-wide view is what fills the by-pitch-type table (Brad, 2026-10-11)."""
    if sessions_df is None or sessions_df.empty:
        return []
    opts = [{"label": f"{r.date} ({int(r.pitches)})", "value": str(r.date)}
            for r in sessions_df.itertuples()]
    if len(opts) > 1:
        total = int(sessions_df["pitches"].sum())
        opts.insert(0, {"label": f"All sessions in range ({total})", "value": ALL_SESSIONS})
    return opts


def default_session_value(opts: list[dict]):
    """Most recent single session -- the page still opens on one pen, not the
    all-sessions view."""
    return next((o["value"] for o in opts if o["value"] != ALL_SESSIONS), None)
