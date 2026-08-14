"""Player options for HitTrax practice (name-based).

No "All Players" aggregate -- the dashboard always shows one player (too heavy
otherwise). Team-transparent VIEW: every account may pick any player. The
`is_coach`/`own_name` params are retained for signature stability (callers pass
them unchanged) but no longer restrict the option list; WRITE access is gated
separately (coach-only) in the dashboards.
"""
from __future__ import annotations


def filter_names_for_role(names: list[str], *, is_coach: bool, own_name: str | None) -> list[str]:
    """Every account sees the full name list (team-transparent view)."""
    return list(names)


def player_options(names: list[str], *, is_coach: bool, own_name: str | None) -> list[dict]:
    """Dropdown options (alphabetical). No 'All Players'."""
    return [{"label": n, "value": n} for n in list(names)]


def resolve_player(requested: str | None, *, is_coach: bool, own_name: str | None,
                   available: list[str], default: str | None = None) -> str | None:
    """The player to show (any account): the requested name if it's a valid
    option, else `default` (first-with-a-session-on-the-latest-date), else the
    first available. When the date range has no players at all, keep the current
    selection (`requested`) rather than blanking the dashboard -- usually only
    transient (e.g. an empty custom range) and nothing better to fall back to."""
    avail = list(available)
    if not avail:
        return requested
    if requested and requested in avail:
        return requested
    if default and default in avail:
        return default
    return avail[0]
