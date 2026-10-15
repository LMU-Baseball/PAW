"""Remove a bad/duplicate game load from GAMES by GameID.

Run: python scripts/remove_game.py GAME_ID [--apply]

A manual upload (e.g. a hand-corrected camera-system CSV) and the automated
Trackman SFTP pull can both load the same physical game under two different
GameIDs (different PitchUID sets -- see app.ingest.games.dedup_key), showing
up as a duplicate entry in the outing/game picker. This deletes every GAMES
row for one bad GameID -- never the whole table -- and rebuilds the precalc
rollups so dashboards/reports stop seeing it.

On --apply, also appends the GameID to data/excluded_games.json (unless
--no-exclude) -- without that, the next cron run would just re-insert the
same rows: its dedup is per-PitchUID against what's currently in GAMES, so a
deleted row's PitchUID looks "new" again the moment the source file is
re-walked on the SFTP server (which this script has no reach into and does
not delete). app.ingest.games.load_games checks that list on every row.

Without --apply, prints what would be deleted and does nothing else (dry run,
the default -- mirrors load_game_csv.py). Deleting GAMES rows is the kind of
one-off write CLAUDE.md says never to run directly against the shared DB; this
script exists so that write is reviewed code, run deliberately with --apply,
not an ad hoc DELETE typed into a shell.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data import precalc  # noqa: E402
from app.db import get_engine, query_df  # noqa: E402
from app.ingest.games import EXCLUDED_GAMES_PATH  # noqa: E402


def _append_exclusion(game_id: str, summary_row) -> None:
    entries = []
    if EXCLUDED_GAMES_PATH.exists():
        with open(EXCLUDED_GAMES_PATH, encoding="utf-8") as fh:
            entries = json.load(fh)
    if any(e["game_id"] == game_id for e in entries):
        return  # already excluded (e.g. re-running --apply after a partial failure)
    entries.append({
        "game_id": game_id,
        "reason": f"Removed via scripts/remove_game.py: {int(summary_row['n'])} pitches, "
                  f"GameType={summary_row['GameType']}, "
                  f"{summary_row['HomeTeam']} vs {summary_row['AwayTeam']}.",
        "removed": date.today().isoformat(),
    })
    with open(EXCLUDED_GAMES_PATH, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, indent=2)
        fh.write("\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("game_id")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--no-exclude", action="store_true",
                    help="skip appending to data/excluded_games.json "
                         "(e.g. the GameID can never recur, so there's nothing to re-block)")
    args = ap.parse_args(argv)

    summary = query_df(
        "SELECT COUNT(*) AS n, MIN(Date) AS date_min, MAX(Date) AS date_max, "
        "GameType, HomeTeam, AwayTeam "
        "FROM GAMES WHERE GameID = :g "
        "GROUP BY GameType, HomeTeam, AwayTeam",
        {"g": args.game_id},
    )
    if summary.empty:
        print(f"no GAMES rows for GameID={args.game_id!r} -- nothing to do")
        return 1
    row = summary.iloc[0]
    print(f"GameID={args.game_id!r}: {int(row['n'])} pitches, "
          f"{row['date_min']}..{row['date_max']}, GameType={row['GameType']}, "
          f"{row['HomeTeam']} vs {row['AwayTeam']}")

    if not args.apply:
        print("dry run -- add --apply to delete")
        return 0

    engine = get_engine()
    with engine.begin() as conn:
        result = conn.execute(text("DELETE FROM GAMES WHERE GameID = :g"), {"g": args.game_id})
    if not args.no_exclude:
        _append_exclusion(args.game_id, row)
    precalc.rebuild_all(engine)
    print(f"deleted {result.rowcount} rows for GameID={args.game_id!r}"
          + ("" if args.no_exclude else " and added it to data/excluded_games.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
