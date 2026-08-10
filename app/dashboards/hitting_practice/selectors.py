"""Role-aware player options for HitTrax practice (name-based).

No "All Players" aggregate any more -- the dashboard always shows one player
(too heavy otherwise). A coach picks any player; a player is locked to their own
name (best-effort match).
"""
from __future__ import annotations


def filter_names_for_role(names: list[str], *, is_coach: bool, own_name: str | None) -> list[str]:
    if is_coach or not own_name:
        return list(names)
    own = own_name.lower().strip()
    tokens = [t for t in own.replace(",", " ").split() if t]
    matched = []
    for n in names:
        nl = str(n).lower()
        if nl == own or any(t in nl for t in tokens if len(t) > 2):
            matched.append(n)
    return matched or list(names)  # fall back to all if no HitTrax name match


def player_options(names: list[str], *, is_coach: bool, own_name: str | None) -> list[dict]:
    """Dropdown options (alphabetical), role-filtered. No 'All Players'."""
    names = filter_names_for_role(names, is_coach=is_coach, own_name=own_name)
    return [{"label": n, "value": n} for n in names]


def resolve_player(requested: str | None, *, is_coach: bool, own_name: str | None,
                   available: list[str], default: str | None = None) -> str | None:
    """The player to show. Coach: the requested name if it's a valid option,
    else `default` (first-with-a-session-on-the-latest-date) or the first
    available. Player: their own matched name. When the date range has no
    players at all, keep the current selection (`requested`) rather than
    blanking the dashboard -- this is usually only transient (e.g. an empty
    custom range) and there's nothing better to fall back to."""
    avail = filter_names_for_role(available, is_coach=is_coach, own_name=own_name)
    if not avail:
        return requested
    if not is_coach:
        return avail[0]
    if requested and requested in avail:
        return requested
    if default and default in avail:
        return default
    return avail[0]
