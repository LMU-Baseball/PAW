"""One-time cleanup of the Competitive Cauldron KPI columns to the list the
coaching staff asked for (2026-10-04), left to right.

Why it's needed: until the 2026-10-04 fix, `cauldron.seed_default_scoring`
re-inserted every missing default KPI on each app boot (and each test run),
so columns the coach deleted kept coming back alongside the ones he re-added
-- the grid ended up with two K%, two Strike%, two BB%, FPS + FPS%, etc.

What it does:
  * Keeps, relabels and orders the 17 wanted KPIs (TARGET). Where the coach's
    re-added column and a resurrected original both exist, the ORIGINAL is
    kept because it holds the recorded points; the empty duplicate goes.
  * Removes the duplicates (EMPTY_DUPLICATES) -- refuses to if any of them
    has recorded points, so no entered data is lost.
  * Removes the columns no longer wanted (RETIRED). Their historical
    cauldron_daily rows are left in the table (just no longer shown or
    counted), so this is reversible by re-adding the metric.

Dry run by default; prints the plan. `--apply` writes it. Safe to re-run.

Run: python scripts/set_cauldron_kpis.py [--apply]
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from app.data import cauldron  # noqa: E402
from app.db import query_df  # noqa: E402

TARGET = [
    ("k_pct", "K%"),
    ("barrel", "Barrel%"),
    ("bb_pct", "BB%"),
    ("strike_pct", "Strike%"),
    ("first_pitch_strike", "FPS%"),
    ("pre2k_zone", "Pre2K Zone%"),
    ("early_ahead", "E+A%"),
    ("twok_kill", "2K Kill%"),
    ("pen_strike", "Pen Strike%"),
    ("pen_fps", "Pen FPS%"),
    ("pen_os_inzone", "Pen OS InZone%"),
    ("pen_2_3_w", "Pen 2/3 W%"),
    ("pen_1_1_w", "Pen 1-1 W%"),
    ("mod_command", "Mod Command"),
    ("ah_rehab", "AH/Rehab"),
    ("gas_station_pr", "Gas Station PR"),
    ("tonnage_check", "Tonnage Check"),
]
EMPTY_DUPLICATES = ["k", "bb", "strike", "fps", "e_a", "2k_kill"]
RETIRED = ["offspeed_zone", "count_work", "recovery_command"]


def main(apply: bool) -> int:
    scoring = cauldron.read_scoring()
    print("Current config (backup):")
    print(json.dumps(scoring.where(scoring.notna(), None).to_dict("records"), default=str))

    configured = set(scoring["metric"])
    missing = [m for m, _ in TARGET if m not in configured]
    if missing:
        print(f"ABORT: wanted KPIs not in cauldron_scoring: {missing}")
        return 1

    counts = query_df(f"SELECT metric, COUNT(*) n FROM {cauldron.DAILY_TABLE} GROUP BY metric")
    rows_by_metric = dict(zip(counts["metric"], counts["n"]))
    has_data = [m for m in EMPTY_DUPLICATES if rows_by_metric.get(m, 0)]
    if has_data:
        print(f"ABORT: these 'empty' duplicates have recorded points: {has_data}")
        return 1

    labels = dict(zip(scoring["metric"], scoring["label"]))
    print("\nPlan (left to right):")
    for i, (metric, label) in enumerate(TARGET, start=1):
        change = "" if labels.get(metric) == label else f"   (was {labels.get(metric)!r})"
        print(f"  {i:2}. {label:<16} [{metric}, {rows_by_metric.get(metric, 0)} recorded]{change}")
    to_remove = [m for m in EMPTY_DUPLICATES + RETIRED if m in configured]
    for m in to_remove:
        print(f"  remove {labels.get(m)!r} [{m}, {rows_by_metric.get(m, 0)} recorded rows kept]")
    unknown = configured - {m for m, _ in TARGET} - set(EMPTY_DUPLICATES) - set(RETIRED)
    if unknown:
        print(f"  left alone (not in this script's lists): {sorted(unknown)}")

    if not apply:
        print("\nDry run -- nothing written. Re-run with --apply.")
        return 0

    for metric, label in TARGET:
        if labels.get(metric) != label:
            cauldron.update_scoring_label(metric, label)
    for m in to_remove:
        cauldron.delete_scoring_metric(m)
    cauldron.set_scoring_order([m for m, _ in TARGET])
    final = cauldron.read_scoring()
    print("\nApplied. Columns now:", ", ".join(final["label"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(apply="--apply" in sys.argv[1:]))
