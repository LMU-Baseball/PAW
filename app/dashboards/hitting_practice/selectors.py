"""Role-aware player options for HitTrax practice (name-based)."""
from __future__ import annotations

from app.data import practice as P


def resolve_player(requested: str | None, *, is_coach: bool, own_name: str | None) -> str:
    """Coach: requested or All Players. Player: best-effort name match."""
    if is_coach:
        return requested or "All Players"
    if not own_name:
        return "All Players"
    # Prefer exact, else substring match on last token.
    return own_name


def filter_names_for_role(names: list[str], *, is_coach: bool, own_name: str | None) -> list[str]:
    if is_coach or not own_name:
        return names
    own = own_name.lower().strip()
    tokens = [t for t in own.replace(",", " ").split() if t]
    matched = []
    for n in names:
        nl = str(n).lower()
        if nl == own or any(t in nl for t in tokens if len(t) > 2):
            matched.append(n)
    return matched or names  # fall back to all if no HitTrax name match


def player_options(pitch_df, *, is_coach: bool, own_name: str | None) -> list[dict]:
    names = P.player_names(pitch_df)
    names = filter_names_for_role(names, is_coach=is_coach, own_name=own_name)
    opts = [{"label": "All Players", "value": "All Players"}]
    if not is_coach and own_name:
        # Lock to matched names only (no All Players for players with a match).
        matched = filter_names_for_role(P.player_names(pitch_df), is_coach=False, own_name=own_name)
        if matched and matched != P.player_names(pitch_df):
            return [{"label": n, "value": n} for n in matched]
    opts += [{"label": n, "value": n} for n in names]
    return opts
