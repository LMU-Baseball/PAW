"""Phase 3 warehouse retirement -- archive (rename) then drop. DESTRUCTIVE.

Two explicit, ordered phases:

  --status            Show which warehouse tables / zz_archived_* / views exist.
  --rename            RENAME the 11 warehouse tables to zz_archived_<name>
                      (instant, reversible; internal FKs follow the rename).
  --drop --confirm    DROP the dependent views, then DROP the zz_archived_*
                      tables (FK checks off for the batch). IRREVERSIBLE.
  --unrename          Revert --rename (zz_archived_<name> -> <name>).

Intended flow: dump_warehouse.py  ->  --rename  ->  verify the live app  ->
(user go)  ->  --drop --confirm.

Run:  python scripts/archive_and_drop_warehouse.py --status
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402
from app.db import get_engine  # noqa: E402
from scripts.dump_warehouse import WAREHOUSE_TABLES, WAREHOUSE_VIEWS  # noqa: E402

ARCHIVE_PREFIX = "zz_archived_"


def _existing(conn, names) -> set[str]:
    rows = conn.execute(text(
        "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE()")).fetchall()
    present = {r[0] for r in rows}
    return {n for n in names if n in present}


def status(conn) -> None:
    live = _existing(conn, WAREHOUSE_TABLES)
    arch = _existing(conn, [ARCHIVE_PREFIX + t for t in WAREHOUSE_TABLES])
    views = _existing(conn, WAREHOUSE_VIEWS)
    print(f"live warehouse tables present:     {len(live):>2} {sorted(live)}")
    print(f"archived (zz_archived_*) present:  {len(arch):>2} {sorted(arch)}")
    print(f"warehouse views present:           {len(views):>2} {sorted(views)}")


def rename(conn) -> None:
    present = _existing(conn, WAREHOUSE_TABLES)
    for t in WAREHOUSE_TABLES:
        if t not in present:
            print(f"  skip {t} (already renamed/absent)")
            continue
        conn.execute(text(f"RENAME TABLE `{t}` TO `{ARCHIVE_PREFIX}{t}`"))
        print(f"  renamed {t} -> {ARCHIVE_PREFIX}{t}")


def unrename(conn) -> None:
    present = _existing(conn, [ARCHIVE_PREFIX + t for t in WAREHOUSE_TABLES])
    for t in WAREHOUSE_TABLES:
        a = ARCHIVE_PREFIX + t
        if a not in present:
            print(f"  skip {a} (absent)")
            continue
        conn.execute(text(f"RENAME TABLE `{a}` TO `{t}`"))
        print(f"  reverted {a} -> {t}")


def drop(conn) -> None:
    # Views first (they reference the tables; harmless if already broken/gone).
    for v in WAREHOUSE_VIEWS:
        conn.execute(text(f"DROP VIEW IF EXISTS `{v}`"))
        print(f"  dropped view {v}")
    # Then the archived tables, FK checks off so order doesn't matter.
    conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
    try:
        for t in WAREHOUSE_TABLES:
            conn.execute(text(f"DROP TABLE IF EXISTS `{ARCHIVE_PREFIX}{t}`"))
            print(f"  dropped table {ARCHIVE_PREFIX}{t}")
        # Also drop any that were never renamed (belt-and-suspenders).
        for t in WAREHOUSE_TABLES:
            conn.execute(text(f"DROP TABLE IF EXISTS `{t}`"))
    finally:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--rename", action="store_true")
    ap.add_argument("--unrename", action="store_true")
    ap.add_argument("--drop", action="store_true")
    ap.add_argument("--confirm", action="store_true",
                    help="required with --drop (irreversible)")
    args = ap.parse_args()

    eng = get_engine()
    if args.status:
        with eng.connect() as c:
            status(c)
        return 0
    if args.rename:
        with eng.begin() as c:
            rename(c)
        print("RENAME done. Verify the live app, then run --drop --confirm.")
        return 0
    if args.unrename:
        with eng.begin() as c:
            unrename(c)
        return 0
    if args.drop:
        if not args.confirm:
            print("Refusing to drop without --confirm (irreversible).")
            return 2
        with eng.begin() as c:
            drop(c)
        print("DROP done. Warehouse retired.")
        with eng.connect() as c:
            status(c)
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
