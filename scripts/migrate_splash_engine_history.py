"""One-off migration: splash_engine_metrics (single Base/Now row per metric)
-> splash_engine_readings (one dated row per metric per reading).

Background: Building the Engine was originally a single mutable Base/Now
pair per (player, season, cycle, metric). The 2026-09-10 planning session
replaced that with a true time series -- one row per reading date -- so a
coach's every-2-week reassessment adds a new dated row instead of silently
overwriting the trend (see app/data/splash_report.py's READINGS_TABLE
docstring). This script migrates whatever was already saved under the old
shape into the new one; it does not touch or drop the old table.

We don't know the real historical date a "base" reading was taken on (the
old schema never recorded one) -- only `updated_at`, which reflects the
last time either value was touched. Heuristic used here: the "now" reading
lands on updated_at's date; if base_value differs from now_value, the
"base" reading lands 14 days earlier (matching the "every 2 weeks" cadence
these tables are actually used at). Idempotent: both land as upserts keyed
by (player, season, cycle, metric, reading_date), so re-running this is
safe -- it just re-writes the same two rows.

Usage:  python scripts/migrate_splash_engine_history.py [--dry-run]
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data import splash_report as SR  # noqa: E402
from app.db import query_df  # noqa: E402


def main(dry_run: bool) -> None:
    SR.ensure_tables()
    df = query_df(f"SELECT * FROM {SR.ENGINE_TABLE}")
    if df.empty:
        print("splash_engine_metrics is empty -- nothing to migrate.")
        return

    by_key: dict[tuple, list[dict]] = {}
    for _, r in df.iterrows():
        key = (int(r["player_id"]), r["season_label"], r["cycle"])
        updated_at = r["updated_at"]
        now_date = (updated_at.date() if hasattr(updated_at, "date")
                    else datetime.strptime(str(updated_at)[:10], "%Y-%m-%d").date())
        base_v = None if r["base_value"] is None or (
            isinstance(r["base_value"], float) and r["base_value"] != r["base_value"]) \
            else float(r["base_value"])
        now_v = None if r["now_value"] is None or (
            isinstance(r["now_value"], float) and r["now_value"] != r["now_value"]) \
            else float(r["now_value"])
        rows = by_key.setdefault(key, [])
        if now_v is not None:
            rows.append({"metric_key": r["metric_key"], "reading_date": now_date.isoformat(),
                        "value": now_v})
        if base_v is not None and base_v != now_v:
            base_date = now_date - timedelta(days=14)
            rows.append({"metric_key": r["metric_key"], "reading_date": base_date.isoformat(),
                        "value": base_v})

    total = sum(len(v) for v in by_key.values())
    print(f"{len(df)} old rows -> {total} readings across {len(by_key)} (player, season, cycle) keys.")
    if dry_run:
        print("--dry-run: no writes made.")
        return

    for (player_id, season_label, cycle), rows in by_key.items():
        # upsert_engine_readings takes ONE reading_date for the whole batch
        # (it's built for the Update Readings form, one day at a time) --
        # migrated rows span up to two dates per key, so group by date here.
        by_date: dict[str, list[dict]] = {}
        for row in rows:
            by_date.setdefault(row["reading_date"], []).append(
                {"metric_key": row["metric_key"], "value": row["value"]})
        for reading_date, date_rows in by_date.items():
            SR.upsert_engine_readings(player_id, season_label, cycle, reading_date, date_rows,
                                      updated_by=None)
    print("Migration complete.")


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
