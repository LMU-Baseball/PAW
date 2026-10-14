"""Load one local Trackman game CSV (e.g. a hand-corrected scrimmage export)
into GAMES, the same way the pipeline loads SFTP files.

Run: python scripts/load_game_csv.py PATH.csv [--game-type Scrimmage] [--correct]
     ... --apply   (without it, a dry run that only prints what would load)

Uses app.ingest.games' parser (ISO dates, GAMES column names), refuses a
non-LMU file, and skips any PitchUID already in GAMES -- so loading the
corrected CSV first means the cron's later copy of the same game is skipped,
not duplicated. On --apply it rebuilds the precalc rollups like the pipeline.

If the cron already loaded Trackman's uncorrected copy, --correct updates
those pitches' hand-correctable fields (games.CORRECTABLE_COLS: names, ids,
inning, count, result) where the CSV differs -- never times or tracking.
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data import precalc  # noqa: E402
from app.db import get_engine, query_df  # noqa: E402
from app.ingest import games  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--game-type", help="GAMES.GameType to set, e.g. Scrimmage")
    ap.add_argument("--correct", action="store_true",
                    help="also fix already-loaded pitches from this CSV")
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

    fixes, loaded_uids = {}, [u for u in parsed["PitchUID"] if str(u) in have]
    if args.correct and loaded_uids:
        ph = ", ".join(f":u{i}" for i in range(len(loaded_uids)))
        existing = query_df(f"SELECT * FROM GAMES WHERE PitchUID IN ({ph})",
                            {f"u{i}": u for i, u in enumerate(loaded_uids)})
        fixes = games.scoring_corrections(parsed, existing)
        per_col: dict[str, int] = {}
        for fix in fixes.values():
            for c in fix:
                per_col[c] = per_col.get(c, 0) + 1
        print(f"corrections: {len(fixes)} pitches -- {per_col or 'nothing differs'}")

    if not args.apply:
        print("dry run -- add --apply to load")
        return 0
    if rows:
        games.chunked_insert(engine, "GAMES", rows)
    with engine.begin() as conn:
        for uid, fix in fixes.items():
            sets = ", ".join(f"`{c}` = :c{i}" for i, c in enumerate(fix))
            vals = {f"c{i}": (None if pd.isna(v) else v) for i, v in enumerate(fix.values())}
            conn.execute(text(f"UPDATE GAMES SET {sets} WHERE PitchUID = :uid"), {**vals, "uid": uid})
        if args.game_type and args.correct and loaded_uids:
            ph = ", ".join(f":u{i}" for i in range(len(loaded_uids)))
            conn.execute(text(f"UPDATE GAMES SET GameType = :gt WHERE PitchUID IN ({ph})"),
                         {"gt": args.game_type, **{f"u{i}": u for i, u in enumerate(loaded_uids)}})
    if rows or fixes:
        precalc.rebuild_all(engine)
    print(f"loaded {len(rows)} rows, corrected {len(fixes)} pitches")
    return 0


if __name__ == "__main__":
    sys.exit(main())
