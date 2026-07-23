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


def lmu_players() -> list[tuple[int, str, int]]:
    """(raw_tm_id, name, n_tracked) for LMU batters AND pitchers, so pitchers get
    their own roster card. n_tracked is that (id,name) identity's row count, used
    to break same-id collisions (a stray 1-row identity loses to the real one)."""
    bat = query_df(
        """
        SELECT batter_tm_id AS id, batter_name AS name, COUNT(*) AS n
          FROM fact_tm_game_pitch
         WHERE batter_team = :team AND batter_tm_id IS NOT NULL
         GROUP BY batter_tm_id, batter_name
        """, {"team": LMU_BATTER_TEAM})
    pit = query_df(
        """
        SELECT pitcher_tm_id AS id, pitcher_name AS name, COUNT(*) AS n
          FROM fact_tm_game_pitch
         WHERE pitcher_team = :team AND pitcher_tm_id IS NOT NULL
         GROUP BY pitcher_tm_id, pitcher_name
        """, {"team": LMU_BATTER_TEAM})
    rows = [(int(r.id), str(r.name), int(r.n)) for r in bat.itertuples()]
    rows += [(int(r.id), str(r.name), int(r.n)) for r in pit.itertuples()]
    return rows


def build_media(players, roster_cards):
    """Map raw_tm_id -> roster card, confident matches only, dominant identity wins.

    players: list of (raw_tm_id, warehouse_name, n_tracked).
    Sorting by n_tracked ascending means the heaviest identity is written LAST and
    wins the id key (a 1-pitch stray under someone else's id loses)."""
    by_norm = {_norm_name(p["name"]): p for p in roster_cards}
    li_index: dict[tuple[str, str], list[dict]] = {}
    for p in roster_cards:
        first, last = _name_parts(p["name"])
        li_index.setdefault((last, first[:1]), []).append(p)

    def match(name):
        p = by_norm.get(_norm_name(name))
        if p is None:
            first, last = _name_parts(name)
            cand = li_index.get((last, first[:1]), [])
            p = cand[0] if len(cand) == 1 else None  # unambiguous only
        return p

    media, matched_names, unmatched = {}, set(), []
    for tm_id, name, _n in sorted(players, key=lambda t: t[2]):  # light first
        p = match(name)
        if p:
            media[str(tm_id)] = {"jersey": p["jersey"], "photo_url": p["photo_url"],
                                 "name": p["name"]}
            matched_names.add(p["name"])
        else:
            unmatched.append(name)
    unmatched_roster = [p["name"] for p in roster_cards if p["name"] not in matched_names]
    return media, sorted(set(unmatched)), unmatched_roster


def main() -> int:
    print(f"Fetching {ROSTER_URL} ...")
    roster_cards = scrape_roster(_fetch(ROSTER_URL))
    print(f"  parsed {len(roster_cards)} roster cards")
    players = lmu_players()
    print(f"  {len(players)} LMU (batter+pitcher) identities in the warehouse")
    media, unmatched, unmatched_roster = build_media(players, roster_cards)

    path = media_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(media, fh, indent=2)
    print(f"  wrote {len(media)} matched entries -> {path}")
    if unmatched:
        print(f"  UNMATCHED players (no roster photo): {sorted(set(unmatched))}")
    if unmatched_roster:
        print(f"  roster players not in warehouse players (walk-ons, etc.): "
              f"{len(unmatched_roster)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
