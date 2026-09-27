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
    else the viewer's own id as a default, else None (layout picks a default)."""
    if requested_id not in (None, ""):
        return int(requested_id)
    return int(own_trackman_id) if own_trackman_id is not None else None


def pitcher_options(*, is_coach: bool, own_trackman_id, start=None, end=None) -> list[dict]:
    """Pitcher dropdown options, scoped to [start, end] when both are given
    (no args = every LMU pitcher who's ever had a bullpen). Every account sees
    the whole roster (team-transparent view).

    2026-09-26 (Brad: "Matt Moreno is missing some bullpen sessions") -- his
    sessions weren't missing, they were split across TWO distinct BULLPEN
    PitcherIds (Trackman itself logged him under two ids over time, most
    likely a device re-pairing upstream of PAW), both displaying as the exact
    same "Moreno, Matthew" label -- a coach picking one identically-labeled
    entry had no way to know a second one existed with the rest of his
    sessions. Whenever `lmu_bullpen_pitchers` returns more than one PitcherId
    for the same display name, each of that name's options gets a
    disambiguating suffix (session count + most recent date) instead of the
    bare name; every other (non-colliding) pitcher's label is unchanged."""
    df = B.lmu_bullpen_pitchers(start=start, end=end)
    dupe_names = set(df["pitcher"][df["pitcher"].duplicated(keep=False)])
    options = []
    for r in df.itertuples():
        label = str(r.pitcher)
        if r.pitcher in dupe_names:
            label = f"{label} ({r.sessions} sessions, last {r.last_date})"
        options.append({"label": label, "value": int(r.pitcher_id)})
    return options


def session_dropdown_options(sessions_df) -> list[dict]:
    """Session-date dropdown options (newest first) from B.session_options()."""
    if sessions_df is None or sessions_df.empty:
        return []
    return [{"label": f"{r.date} ({int(r.pitches)})", "value": str(r.date)}
            for r in sessions_df.itertuples()]
