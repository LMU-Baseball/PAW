"""Add query-aligned indexes to GAMES (it shipped with ZERO indexes, so every
cold query full-scans ~104k rows). Non-destructive, reversible, idempotent.

Indexes match how the caps data layer actually filters GAMES:
  GameID    -> game_pitches / pitchers_for_game / scoreboard / video
  BatterId  -> hitting reads + sibling lookup
  PitcherId -> pitching reads + sibling lookup + velo
  CatcherId -> catching reads + sibling lookup
  Date      -> recent-window / range queries / recent_games
  PitchUID  -> insert dedup (existing_keys)

TEXT columns (GameID, Date) take a prefix length; the double id columns and
varchar PitchUID are indexed directly (PitchUID prefixed to a safe length).

Usage:  python scripts/index_games.py --status | --create | --drop
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402
from app.db import get_engine  # noqa: E402

# (index_name, column expression incl. any prefix length)
INDEXES = [
    ("ix_games_gameid", "GameID(32)"),
    ("ix_games_batterid", "BatterId"),
    ("ix_games_pitcherid", "PitcherId"),
    ("ix_games_catcherid", "CatcherId"),
    ("ix_games_date", "Date(10)"),
    ("ix_games_pitchuid", "PitchUID(64)"),
]


def _existing(conn) -> set[str]:
    rows = conn.execute(text(
        "SELECT DISTINCT INDEX_NAME FROM INFORMATION_SCHEMA.STATISTICS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'GAMES'")).fetchall()
    return {r[0] for r in rows}


def status(conn) -> None:
    have = _existing(conn)
    for name, col in INDEXES:
        print(f"  {'present' if name in have else 'MISSING':>8}  {name:<20} ({col})")


def create(conn) -> None:
    have = _existing(conn)
    for name, col in INDEXES:
        if name in have:
            print(f"  skip {name} (exists)")
            continue
        conn.execute(text(f"CREATE INDEX {name} ON GAMES ({col})"))
        print(f"  created {name} ON GAMES ({col})")


def drop(conn) -> None:
    have = _existing(conn)
    for name, _ in INDEXES:
        if name not in have:
            print(f"  skip {name} (absent)")
            continue
        conn.execute(text(f"DROP INDEX {name} ON GAMES"))
        print(f"  dropped {name}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--create", action="store_true")
    ap.add_argument("--drop", action="store_true")
    args = ap.parse_args()
    eng = get_engine()
    if args.create:
        with eng.begin() as c:
            create(c)
    elif args.drop:
        with eng.begin() as c:
            drop(c)
    else:
        with eng.connect() as c:
            status(c)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
