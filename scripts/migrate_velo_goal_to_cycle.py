"""One-off migration: velo_board_entries.velo_goal (per-week) -> the coach's
typed Velo Goal on `velo_board_cycle_overrides` (per-cycle).

Background: the velo board's filter bar moved from Week to Cycle
(Fall/Winter/Spring) 2026-09-22, and Velo Goal moved with it onto the
cycle-scoped table -- but the values a coach had already typed into the old
weekly grid were left behind in `velo_board_entries` (that table's read path
was simply retired, not migrated), so they stopped showing up on the board.
This script brings them forward.

For each (pitcher, season) with one or more weekly velo_goal entries, groups
those weeks by which training cycle they fall in (`splash_report.
cycle_for_date`) and takes the MOST RECENT week's value per (pitcher,
season, cycle) as the coach's current goal for that cycle. Never touches
Assessment -- that's auto-computed fresh from BULLPEN now (see
`velo_board.cycle_assessment`) -- any existing Assessment override on the
target cycle row is read first and written back unchanged so this migration
can't clobber it.

Idempotent: re-running just re-derives and re-writes the same latest-week
values.

Usage:  python scripts/migrate_velo_goal_to_cycle.py [--dry-run]
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data import splash_report as SR  # noqa: E402
from app.data import velo_board as VB  # noqa: E402
from app.db import query_df  # noqa: E402


def main(dry_run: bool) -> None:
    VB.ensure_tables()
    df = query_df(
        f"SELECT pitcher_id, pitcher_name, season_label, week_start, velo_goal "
        f"FROM {VB.VELO_BOARD_TABLE} WHERE velo_goal IS NOT NULL")
    if df.empty:
        print("velo_board_entries has no velo_goal values -- nothing to migrate.")
        return

    df["cycle"] = df["week_start"].map(SR.cycle_for_date)
    groups = df.sort_values("week_start").groupby(
        ["pitcher_id", "season_label", "cycle"], as_index=False).last()

    for _, r in groups.iterrows():
        pid, season, cycle = int(r["pitcher_id"]), r["season_label"], r["cycle"]
        goal = float(r["velo_goal"])
        existing = VB.read_cycle_overrides(season, cycle)
        cur = existing[existing["pitcher_id"].astype(int) == pid]
        keep_assessment = (float(cur.iloc[0]["assessment"])
                           if not cur.empty and cur.iloc[0]["assessment"] is not None
                           and cur.iloc[0]["assessment"] == cur.iloc[0]["assessment"]
                           else None)
        print(f"{'[dry-run] would set' if dry_run else 'setting'} "
             f"{r['pitcher_name']} ({season} {cycle}): velo_goal={goal} "
             f"(week {r['week_start']}), keeping assessment={keep_assessment}")
        if not dry_run:
            VB.set_cycle_override(pid, season, cycle, velo_goal=goal,
                                  assessment=keep_assessment)

    print(f"\n{len(groups)} (pitcher, season, cycle) goal(s) "
         f"{'would be' if dry_run else ''} migrated.")


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
