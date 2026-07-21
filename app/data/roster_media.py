"""Roster media (headshot + jersey) loaded from a scraped JSON file.

`scripts/scrape_roster_media.py` writes `instance/roster_media.json`, keyed by
`batter_tm_id`. The hitting sidebar reads it via `player_media()`. Everything
degrades gracefully to blanks when the file is missing or a player isn't matched,
so the dashboard never depends on the scrape having run.
"""
from __future__ import annotations

import json
import os
import re

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
_FILENAME = "roster_media.json"
_cache: dict | None = None


def _norm_name(s: str) -> str:
    """Order/case/punctuation-insensitive name key.

    Handles both "Last, First" (warehouse) and "First Last [Suffix]" (roster):
    both collapse to the same sorted-token key, e.g. "carmona jose".
    """
    if not s:
        return ""
    s = s.lower()
    if "," in s:  # "Last, First"
        last, first = (p.strip() for p in s.split(",", 1))
        s = f"{first} {last}"
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    toks = [t for t in s.split() if t and t not in _SUFFIXES]
    return " ".join(sorted(toks))


def _name_parts(s: str) -> tuple[str, str]:
    """(first, last) lowercased, for a last-name + first-initial fallback match.

    Handles "Last, First" and "First [Middle] Last [Suffix]".
    """
    if not s:
        return "", ""
    s = s.lower()
    if "," in s:
        last, first = (p.strip() for p in s.split(",", 1))
        s = f"{first} {last}"
    toks = [t for t in re.sub(r"[^a-z0-9 ]", " ", s).split()
            if t and t not in _SUFFIXES]
    if not toks:
        return "", ""
    return toks[0], toks[-1]


def _instance_dir() -> str:
    """The Flask instance dir (app context) or <repo>/instance as a fallback."""
    try:
        from flask import current_app
        return current_app.instance_path
    except Exception:
        return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), "instance")


def media_path() -> str:
    return os.path.join(_instance_dir(), _FILENAME)


def load_roster_media(force: bool = False) -> dict:
    """Read the scraped JSON (module-cached). Returns {} if the file is missing."""
    global _cache
    if _cache is not None and not force:
        return _cache
    path = media_path()
    try:
        with open(path, encoding="utf-8") as fh:
            _cache = json.load(fh)
    except (FileNotFoundError, ValueError):
        _cache = {}
    return _cache


def player_media(batter_tm_id) -> dict:
    """{'jersey','photo_url'} for a batter_tm_id, blanks if not present."""
    entry = load_roster_media().get(str(batter_tm_id)) or {}
    return {"jersey": entry.get("jersey", ""), "photo_url": entry.get("photo_url", "")}
