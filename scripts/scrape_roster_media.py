"""Scrape LMU roster headshots + jersey numbers and map them to Trackman ids.

Writes instance/roster_media.json keyed by batter_tm_id:
    {"806253": {"jersey": "34", "photo_url": "https://.../Zach_Wadas.jpg?width=360...",
                "name": "Zach Wadas"}, ...}

Run:  python scripts/scrape_roster_media.py
Needs network (lmulions.com) + the analytics DB (for the id mapping). Idempotent.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data.roster_media import _name_parts, _norm_name, media_path  # noqa: E402
from app.db import query_df  # noqa: E402

ROSTER_URL = "https://lmulions.com/sports/baseball/roster"
LMU_BATTER_TEAM = "LOY_LIO"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")


def _name_from_img(src: str) -> str:
    """'.../Zach_Wadas.jpg?width=80' -> 'Zach Wadas'."""
    base = src.split("?")[0].rsplit("/", 1)[-1]
    base = re.sub(r"\.(jpg|jpeg|png|webp)$", "", base, flags=re.I)
    return base.replace("_", " ").strip()


def _upscale(src: str, width: int = 360) -> str:
    if "width=" in src:
        return re.sub(r"width=\d+", f"width={width}", src)
    sep = "&" if "?" in src else "?"
    return f"{src}{sep}width={width}"


def scrape_roster(html: str) -> list[dict]:
    """[{name, jersey, photo_url}] for each roster card."""
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for card in soup.select("li.sidearm-roster-player"):
        img = card.find("img")
        src = (img.get("src") or img.get("data-src")) if img else None
        if not src:
            continue
        jn = card.select_one(".sidearm-roster-player-jersey-number")
        jersey = jn.get_text(strip=True) if jn else ""
        anchor = card.select_one(".sidearm-roster-player-name a")
        name = anchor.get_text(strip=True) if anchor else _name_from_img(src)
        # anchor text can carry stray whitespace/jersey; fall back to filename if odd
        if not name or any(ch.isdigit() for ch in name[:2]):
            name = _name_from_img(src)
        out.append({"name": name, "jersey": jersey, "photo_url": _upscale(src)})
    return out


def lmu_hitters() -> list[tuple[int, str]]:
    df = query_df(
        """
        SELECT DISTINCT batter_tm_id, batter_name FROM fact_tm_game_pitch
         WHERE batter_team = :team AND batter_tm_id IS NOT NULL
        """,
        {"team": LMU_BATTER_TEAM},
    )
    return [(int(r.batter_tm_id), str(r.batter_name)) for r in df.itertuples()]


def build_media(players: list[dict], hitters: list[tuple[int, str]]) -> tuple[dict, list, list]:
    by_norm = {_norm_name(p["name"]): p for p in players}
    # Fallback index by (last, first-initial); only used when UNAMBIGUOUS, so a
    # nickname (Matt/Matthew, Richie/Richard) still resolves to the right player.
    li_index: dict[tuple[str, str], list[dict]] = {}
    for p in players:
        first, last = _name_parts(p["name"])
        li_index.setdefault((last, first[:1]), []).append(p)

    media, matched_names, unmatched_hitters = {}, set(), []
    for tm_id, batter_name in hitters:
        p = by_norm.get(_norm_name(batter_name))
        if p is None:
            first, last = _name_parts(batter_name)
            cand = li_index.get((last, first[:1]), [])
            p = cand[0] if len(cand) == 1 else None
        if p:
            media[str(tm_id)] = {"jersey": p["jersey"], "photo_url": p["photo_url"],
                                 "name": p["name"]}
            matched_names.add(p["name"])
        else:
            unmatched_hitters.append(batter_name)
    unmatched_roster = [p["name"] for p in players if p["name"] not in matched_names]
    return media, unmatched_hitters, unmatched_roster


def main() -> int:
    print(f"Fetching {ROSTER_URL} ...")
    players = scrape_roster(_fetch(ROSTER_URL))
    print(f"  parsed {len(players)} roster cards")
    hitters = lmu_hitters()
    print(f"  {len(hitters)} LMU batter ids in the warehouse")
    media, unmatched_hitters, unmatched_roster = build_media(players, hitters)

    path = media_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(media, fh, indent=2)
    print(f"  wrote {len(media)} matched entries -> {path}")
    if unmatched_hitters:
        print(f"  UNMATCHED hitters (no roster photo): {sorted(set(unmatched_hitters))}")
    if unmatched_roster:
        print(f"  roster players not in warehouse hitters (pitchers, etc.): "
              f"{len(unmatched_roster)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
