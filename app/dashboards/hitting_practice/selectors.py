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


def session_date_options(available_dates: list[str], assignments: dict[str, list[str]],
                         selected_plans: list[str] | None = None) -> tuple[list[str], list[dict]]:
    """Dates for the practice-session dropdown, OR-filtered to any date carrying
    at least one of `selected_plans` (all `available_dates` when none are
    selected), each labeled with its assigned plan names -- e.g.
    "2026-09-17 (Fastball)" -- so a coach can see the tag without opening the
    manage-plans panel. Returns (dates_shown, dropdown_options)."""
    selected = set(selected_plans or [])
    dates = [d for d in available_dates
             if not selected or selected.intersection(assignments.get(d, ()))]

    def _label(d: str) -> str:
        names = assignments.get(d) or []
        return f"{d} ({', '.join(names)})" if names else d

    options = [{"label": f"All sessions in range ({len(dates)})", "value": "__all_sessions__"}]
    options += [{"label": _label(d), "value": d} for d in dates]
    return dates, options


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
