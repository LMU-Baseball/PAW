"""Add the missing indexes the dashboards actually need. Purely additive.

Measured 2026-08-23 (see docs/DATABASE.md):

  BULLPEN  — 24,581 rows, ZERO indexes. Every query in app/data/bullpen.py
             filters `WHERE PitcherId = :pid` (5 of them also on a Date range),
             so every bullpen report does a full 24,581-row scan.
  VIDEO    — 20,638 rows, ZERO indexes. app/data/hitting.py:77 joins it as
             `LEFT JOIN VIDEO v ON g.GameID = v.GameID AND g.PitchUID = v.PitchUID`.
  GAMES    — 104,764 rows with 12 indexes, but all single-column. A query
             filtering player AND date can only use one of them.

TEXT columns need a prefix length. `Date` is stored as TEXT holding ISO
`YYYY-MM-DD`, so prefix 10 covers the whole date — the same choice the existing
`ix_games_date` already made.

Nothing here drops or modifies data. Safe to re-run: existing indexes are skipped.

Usage:  python scripts/apply_db_indexes.py [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

from app.db import get_engine, query_df  # noqa: E402

# (table, index name, index definition, why)
INDEXES = [
    ("BULLPEN", "ix_bullpen_pitcherid_date", "PitcherId, `Date`(10)",
     "every bullpen query filters PitcherId; table had NO indexes at all"),
    ("VIDEO", "ix_video_pitchuid_gameid", "PitchUID(64), GameID(32)",
     "hitting.py LEFT JOINs VIDEO on (GameID, PitchUID); table had NO indexes"),
    ("GAMES", "ix_games_pitcherid_date", "PitcherId, `Date`(10)",
     "pitching dashboards filter pitcher + date range together"),
    ("GAMES", "ix_games_batterid_date", "BatterId, `Date`(10)",
     "hitting dashboards filter batter + date range together"),
]


def existing(table: str) -> set[str]:
    return set(query_df(
        "SELECT DISTINCT index_name AS i FROM information_schema.statistics "
        "WHERE table_schema=DATABASE() AND table_name=:t", {"t": table}
    ).i)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="print the DDL without executing it")
    a = ap.parse_args()

    eng = get_engine()
    print("=== BEFORE ===")
    for tbl in dict.fromkeys(t for t, *_ in INDEXES):
        idx = existing(tbl)
        n = query_df(f"SELECT COUNT(*) AS n FROM `{tbl}`").n.iloc[0]
        print(f"  {tbl:9s} {int(n):>9,} rows, {len(idx)} index(es): "
              f"{sorted(idx) if idx else 'NONE'}")

    created, skipped = [], []
    for tbl, name, cols, why in INDEXES:
        if name in existing(tbl):
            skipped.append(f"{tbl}.{name} (already exists)")
            continue
        ddl = f"CREATE INDEX {name} ON `{tbl}` ({cols})"
        if a.dry_run:
            print(f"\n  [dry-run] {ddl}\n            reason: {why}")
            continue
        print(f"\n  {tbl}: creating {name} ({cols})")
        print(f"    reason: {why}")
        print("    running ...", end="", flush=True)
        with eng.begin() as conn:
            conn.execute(text(ddl))
        print(" done")
        created.append(f"{tbl}.{name}")

    if a.dry_run:
        print("\n(dry run — nothing executed)")
        return

    print("\n=== AFTER ===")
    for tbl in dict.fromkeys(t for t, *_ in INDEXES):
        print(f"  {tbl}:")
        print(query_df(
            "SELECT index_name AS idx, "
            "GROUP_CONCAT(CONCAT(column_name, IFNULL(CONCAT('(', sub_part, ')'), '')) "
            "             ORDER BY seq_in_index) AS cols "
            "FROM information_schema.statistics "
            "WHERE table_schema=DATABASE() AND table_name=:t "
            "GROUP BY index_name ORDER BY index_name", {"t": tbl}
        ).to_string(index=False))

    print(f"\nCREATED ({len(created)}):")
    for c in created or ["  (none)"]:
        print("  +", c)
    if skipped:
        print(f"SKIPPED ({len(skipped)}):")
        for s in skipped:
            print("  -", s)


if __name__ == "__main__":
    main()
