"""Rename the HitTrax / batting-practice tables to the ALL-CAPS convention the
rest of the PAW tables use (GAMES/BULLPEN/...). Non-destructive, reversible,
idempotent. Run AFTER deploying the code that references the new names.

  practice_sessions -> PRACTICE_SESSIONS
  practice_plays    -> PRACTICE_PLAYS
  raw_practice_csv  -> RAW_PRACTICE_CSV

The RDS is case-sensitive (lower_case_table_names=0 -- GAMES and video_clips
coexist), so a case-only RENAME is a real, distinct rename. Indexes/constraints
follow the table automatically.

Usage:  python scripts/rename_practice_tables.py --status | --rename | --unrename
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402
from app.db import get_engine  # noqa: E402

RENAMES = [
    ("practice_sessions", "PRACTICE_SESSIONS"),
    ("practice_plays", "PRACTICE_PLAYS"),
    ("raw_practice_csv", "RAW_PRACTICE_CSV"),
]


def _present(conn) -> set[str]:
    rows = conn.execute(text(
        "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE()")).fetchall()
    return {r[0] for r in rows}


def status(conn) -> None:
    present = _present(conn)
    for lo, up in RENAMES:
        state = "NEW (renamed)" if up in present else ("old (lowercase)" if lo in present else "MISSING")
        print(f"  {lo:<18} -> {up:<20} : {state}")


def _rename(conn, frm: str, to: str) -> None:
    present = _present(conn)
    if to in present:
        print(f"  skip {frm} (already {to})")
    elif frm in present:
        conn.execute(text(f"RENAME TABLE `{frm}` TO `{to}`"))
        print(f"  renamed {frm} -> {to}")
    else:
        print(f"  skip {frm} (absent)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--rename", action="store_true")
    ap.add_argument("--unrename", action="store_true")
    args = ap.parse_args()
    eng = get_engine()
    if args.rename:
        with eng.begin() as c:
            for lo, up in RENAMES:
                _rename(c, lo, up)
    elif args.unrename:
        with eng.begin() as c:
            for lo, up in RENAMES:
                _rename(c, up, lo)
    else:
        with eng.connect() as c:
            status(c)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
