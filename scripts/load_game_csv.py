"""Load one local Trackman game CSV (e.g. a hand-corrected scrimmage export)
into GAMES, the same way the pipeline loads SFTP files.

Run: python scripts/load_game_csv.py PATH.csv [--game-type Scrimmage]
     ... --apply   (without it, a dry run that only prints what would load)

Uses app.ingest.games' parser (ISO dates, GAMES column names), refuses a
non-LMU file, and skips any PitchUID already in GAMES -- so loading the
corrected CSV first means the cron's later copy of the same game is skipped,
not duplicated. On --apply it rebuilds the precalc rollups like the pipeline.
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data import precalc  # noqa: E402
from app.db import get_engine  # noqa: E402
from app.ingest import games  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--game-type", help="GAMES.GameType to set, e.g. Scrimmage")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)

    parsed = games.parse_game_csv(pd.read_csv(args.csv), source_file=args.csv)
    if not games.is_lmu_game(parsed):
        print("not an LMU game (no LOY_LIO pitcher/batter, no foreign id 78) -- nothing loaded")
        return 1
    engine = get_engine()
    have = games.existing_keys(engine, "GAMES", "PitchUID")
    rows = [r for r in parsed.to_dict(orient="records") if games.dedup_key(r) not in have]
    if args.game_type:
        for r in rows:
            r["GameType"] = args.game_type
    print(f"{os.path.basename(args.csv)}: {len(parsed)} pitches, {len(rows)} new, "
          f"{len(parsed) - len(rows)} already in GAMES; dates {sorted(set(parsed['Date']))}")
    if not args.apply:
        print("dry run -- add --apply to load")
        return 0
    if rows:
        games.chunked_insert(engine, "GAMES", rows)
        precalc.rebuild_all(engine)
    print(f"loaded {len(rows)} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
