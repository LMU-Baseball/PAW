"""Upload hand-cut SD-card game/scrimmage clips onto GAMES pitches.

Run: python scripts/upload_game_angle_clips.py MAP.csv --angle HomeBehind --dir D:/PAW-clips/<folder>
     ... --apply   (without it, a dry run that only prints what would upload)

MAP.csv has `play_id,file` columns (Trackman PlayID per clip, the same map
format as upload_bullpen_angle_clips.py). PlayIDs are resolved to
GAMES.PitchUID, so the game must already be loaded (scripts/load_game_csv.py
or the cron). A (pitch, angle) already uploaded is skipped unless --replace.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data import game_video as GV  # noqa: E402
from app.data.video import ANGLES  # noqa: E402
from app.db import query_df  # noqa: E402
from scripts.upload_bullpen_angle_clips import probe  # noqa: E402


def pitch_uids_by_play_id(play_ids: list[str]) -> dict[str, str]:
    if not play_ids:
        return {}
    ph = ", ".join(f":p{i}" for i in range(len(play_ids)))
    df = query_df(f"SELECT PlayID, PitchUID FROM GAMES WHERE PlayID IN ({ph})",
                  {f"p{i}": p for i, p in enumerate(play_ids)})
    return dict(df.itertuples(index=False))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("map_csv")
    ap.add_argument("--angle", required=True, choices=[k for k, _ in ANGLES])
    ap.add_argument("--dir", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--replace", action="store_true")
    args = ap.parse_args(argv)

    with open(args.map_csv, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    uid = pitch_uids_by_play_id([r["play_id"] for r in rows])
    have = GV.sizes_by_pitch_uid(list(uid.values()))

    todo, absent, unknown, skipped = [], [], [], 0
    for r in rows:
        path = os.path.join(args.dir, r["file"])
        if not os.path.exists(path):
            absent.append(r["file"])
        elif r["play_id"] not in uid:
            unknown.append(r["file"])
        elif (uid[r["play_id"]], args.angle) in have and not args.replace:
            skipped += 1
        else:
            todo.append((uid[r["play_id"]], path))

    total_mb = sum(os.path.getsize(p) for _, p in todo) / 1e6
    print(f"{args.angle}: {len(todo)} to upload ({total_mb:.0f} MB), {skipped} already there, "
          f"{len(absent)} not cut for this angle, {len(unknown)} with no GAMES row")
    if unknown:
        print("  no GAMES row:", ", ".join(unknown[:5]), "..." if len(unknown) > 5 else "")
    if not args.apply:
        print("dry run -- add --apply to upload")
        return 0

    for n, (pitch_uid, path) in enumerate(todo, 1):
        with open(path, "rb") as fh:
            data = fh.read()
        GV.add_clip(pitch_uid, args.angle, data, source_file=os.path.basename(path), **probe(path))
        print(f"  [{n}/{len(todo)}] {os.path.basename(path)} -> {pitch_uid}", flush=True)

    sizes = GV.sizes_by_pitch_uid([u for u, _ in todo])
    bad = [p for u, p in todo if sizes.get((u, args.angle)) != os.path.getsize(p)]
    print(f"verified {len(todo) - len(bad)}/{len(todo)} uploaded at matching size")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
