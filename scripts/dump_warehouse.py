"""Portable backup of the tm_*/fact_*/dim_* warehouse before the Phase 3 drop.

Writes, under instance/warehouse_archive/ (gitignored):
  <table>.csv.gz        -- full row dump (gzip)
  <table>.schema.sql    -- SHOW CREATE TABLE
  <view>.view.sql       -- SHOW CREATE VIEW (definitions, so views are restorable)
  MANIFEST.txt          -- table -> rows -> file size

No DDL, no writes to the live DB -- pure SELECT/SHOW. Safe to run anytime.

Run:  python scripts/dump_warehouse.py
"""
from __future__ import annotations

import gzip
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402
from app.db import get_engine, query_df  # noqa: E402

WAREHOUSE_TABLES = [
    "dim_conference", "dim_tm_game", "fact_tm_game_pitch", "tm_ingest_file",
    "tm_player", "tm_player_alias", "tm_player_team_status", "tm_team",
    "tm_team_alias", "tm_team_conference_history", "tm_umpire",
]
WAREHOUSE_VIEWS = [
    "vw_active_players", "vw_available_game_types", "vw_available_seasons",
    "vw_cleaned_game_csv", "vw_game_pitchers", "vw_games", "vw_pitch_video",
    "vw_pitch_video_explorer", "vw_pitcher_appearance_summary",
    "vw_pitcher_appearance_velo", "vw_pitcher_games",
    "vw_pitcher_recent_outings", "vw_pitcher_velo_leaderboard",
    "vw_pitcher_velo_leaderboard_spring_2026", "vw_pitcher_velo_trend",
    "vw_pitchers",
]

OUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "instance", "warehouse_archive",
)


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    eng = get_engine()
    manifest = []

    for t in WAREHOUSE_TABLES:
        df = query_df(f"SELECT * FROM `{t}`")
        path = os.path.join(OUT_DIR, f"{t}.csv.gz")
        with gzip.open(path, "wt", encoding="utf-8", newline="") as fh:
            df.to_csv(fh, index=False)
        # schema
        with eng.connect() as c:
            ddl = c.execute(text(f"SHOW CREATE TABLE `{t}`")).fetchone()[1]
        with open(os.path.join(OUT_DIR, f"{t}.schema.sql"), "w", encoding="utf-8") as fh:
            fh.write(ddl + ";\n")
        size = os.path.getsize(path)
        manifest.append((t, len(df), size))
        print(f"  {t:<32} {len(df):>8} rows  ->  {size/1024:,.1f} KiB")

    # View definitions (restorable; views hold no data).
    for v in WAREHOUSE_VIEWS:
        try:
            with eng.connect() as c:
                ddl = c.execute(text(f"SHOW CREATE VIEW `{v}`")).fetchone()[1]
            with open(os.path.join(OUT_DIR, f"{v}.view.sql"), "w", encoding="utf-8") as fh:
                fh.write(ddl + ";\n")
            print(f"  view {v:<38} definition saved")
        except Exception as e:  # a view may already be missing/broken
            print(f"  view {v:<38} SKIP ({e})")

    with open(os.path.join(OUT_DIR, "MANIFEST.txt"), "w", encoding="utf-8") as fh:
        fh.write("Phase 3 warehouse backup\n")
        for t, n, size in manifest:
            fh.write(f"{t}\t{n} rows\t{size} bytes\n")
    total = sum(n for _, n, _ in manifest)
    print(f"\nDumped {len(manifest)} tables, {total:,} total rows, to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
