"""Seed/update the `lmu_roster` table from a committed season roster JSON file.

Run: python scripts/load_lmu_roster.py data/rosters/2026-2027.json "2026/2027"

Idempotent: re-running with edited class_year/position updates those fields
in place (same roster_id, matched on season_label+last_name+first_name)
rather than reinserting -- required so placeholder ids (-roster_id) already
possibly saved elsewhere (Cauldron/Velo Board) never shift under a coach's
data. Never deletes a player who's missing from a re-run's file -- prints
anyone in the DB for that season who ISN'T in the new file instead, so a real
drop (transfer, etc.) stays a deliberate manual decision.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data.lmu_roster import load_roster, upsert_season_roster  # noqa: E402


def main(path: str, season_label: str) -> int:
    with open(path, encoding="utf-8") as fh:
        players = json.load(fh)
    before = set(zip(load_roster(season_label)["last_name"],
                      load_roster(season_label)["first_name"]))
    n = upsert_season_roster(season_label, players)
    print(f"upserted {n} players for {season_label} from {path}")
    after_names = {(p["last_name"], p["first_name"]) for p in players}
    dropped = before - after_names
    if dropped:
        print(f"NOTE: in DB for {season_label} but not in this file (NOT removed): "
              f"{sorted(dropped)}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python scripts/load_lmu_roster.py <path.json> <season_label>")
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
