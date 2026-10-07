"""Upload hand-cut SD-card clips (Centerfield / Right) onto bullpen pitches.

Run: python scripts/upload_bullpen_angle_clips.py MAP.csv --angle CF --dir D:/PAW-clips/<folder>
     ... --apply   (without it, a dry run that only prints what would upload)

MAP.csv has `play_id,file` columns: which BULLPEN.PlayID each clip in --dir
belongs to. Building it is per-session work (match clip times to Trackman's
per-pitch Time), so it lives outside this script. Rows are uploaded in file
order. A (play_id, angle) that already has a clip is skipped unless
--replace, so a re-run never silently overwrites one.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data import bullpen_video as BV  # noqa: E402


def probe(path: str) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height:format=duration", "-of", "json", path],
        capture_output=True, text=True, check=True).stdout
    info = json.loads(out)
    stream = (info.get("streams") or [{}])[0]
    return {"width": stream.get("width"), "height": stream.get("height"),
            "duration_sec": float(info.get("format", {}).get("duration") or 0) or None}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("map_csv")
    ap.add_argument("--angle", required=True,
                    choices=[k for k, _ in BV.ANGLES if k != BV.EDGER])
    ap.add_argument("--dir", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--replace", action="store_true")
    args = ap.parse_args(argv)

    with open(args.map_csv, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    have = BV.angles_by_play_id([r["play_id"] for r in rows])

    todo, missing, skipped = [], [], 0
    for r in rows:
        path = os.path.join(args.dir, r["file"])
        if not os.path.exists(path):
            missing.append(r["file"])
        elif args.angle in have.get(r["play_id"], set()) and not args.replace:
            skipped += 1
        else:
            todo.append((r["play_id"], path))

    total_mb = sum(os.path.getsize(p) for _, p in todo) / 1e6
    print(f"{args.angle}: {len(todo)} to upload ({total_mb:.0f} MB), "
          f"{skipped} already there, {len(missing)} missing on disk")
    if missing:
        print("  missing:", ", ".join(missing))
    if not args.apply:
        print("dry run -- add --apply to upload")
        return 0

    for n, (play_id, path) in enumerate(todo, 1):
        with open(path, "rb") as fh:
            data = fh.read()
        BV.add_angle_clip(play_id, args.angle, data, source_file=os.path.basename(path),
                          **probe(path))
        print(f"  [{n}/{len(todo)}] {os.path.basename(path)} -> {play_id}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
