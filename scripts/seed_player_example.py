"""Seed the "Player Example" demo pitcher's Built on the Bluff plan (2026-10-04,
Brad: a made-up player coaches can show recruits and test on, filled in as
if he'd thrown every script several times this fall).

All values are invented -- not copied from any real player -- but kept inside
the ranges the real roster's plans actually use (engine strength/ROM numbers,
script goals/measurables, pen-result values, movement shapes). The demo
player's id (`splash_report.DEMO_PLAYER_ID`) is far outside the roster's id
range and appears only in the Bluff page's player dropdown.

Writes go through the same `splash_report` functions the page's own Save
button uses. Dry run by default. Refuses to overwrite once the demo plan
exists (coaches may have edited it since) unless `--force` is passed.

Run: python scripts/seed_player_example.py [--apply] [--force]
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from app.data import splash_report as SR  # noqa: E402

SEASON = "2026/2027"
CYCLE = "Fall"

PLAN = {
    "vision_statement": "Hold 91-93 mph deep into outings\n"
                        "Land the slider for a strike in any count\n"
                        "Add 10 lbs by the end of the fall",
    "training_goals": "FB Avg Velo 92 mph\nFPS 62%\nPre2K Zone 52%\nDevelop gyro SL",
    "feet_set": "Partner Decels (Green x8)\n"
                "Front-Foot Elevated Figure 8's (Blue x6)\n"
                "Water Bag Lateral Step Back (x5)",
    "feet_moving": "Rotational StepBack (Yellow/Baseball x4)\n"
                   "Walking Windup (Yellow/Baseball x4)\n"
                   "Roll-Ins (Yellow/Baseball x4)",
    "work_day": "MedBall Split Stance Shotput (x5)\n"
                "MedBall Stepbacks Shotput (x5)\n"
                "MedBall w/CVB Drive Leg (x5)",
}

# Start of fall -> latest test. Both move from the yellow toward/into the green
# band of ENGINE_THRESHOLDS, which is what a fall of work should look like.
ENGINE = [
    ("IR", 57.4, 63.1), ("ER", 30.9, 36.2), ("Scaption", 29.2, 33.8), ("Grip", 39.6, 43.0),
    ("IROM", 53.0, 58.0), ("EROM", 112.0, 119.0), ("ScaptionROM", 188.0, 196.0),
    ("TotalArc", 172.0, 183.0),
]

GAS = [
    {"need": "Upper Body Strength", "exercise": "Prone W Lift", "sets_reps": "3x12",
     "notes": "Slow eccentric"},
    {"need": "Upper Body Strength", "exercise": "Half Kneeling Internal Rotations",
     "sets_reps": "3x10", "notes": "Light band"},
    {"need": "Upper Body Strength", "exercise": "Elevated Single Arm Serratus Press",
     "sets_reps": "3x8", "notes": None},
    {"need": "Forearm Strength", "exercise": "Weighted Wrist Extensions", "sets_reps": "3x15",
     "notes": "5lb DB"},
    {"need": "Forearm Strength", "exercise": "Wrist Flexion Isometric Holds",
     "sets_reps": "3x20 sec", "notes": None},
]

SCRIPTS = [
    {"script_number": 1, "script_type": "Velo", "goal": "FB Avg Velo 92 mph",
     "measurable": "Max FB Velo", "pitch_design_result": None},
    {"script_number": 2, "script_type": "Velo", "goal": "FB Avg Velo 92 mph",
     "measurable": "Avg FB Velo (Ladder)", "pitch_design_result": None},
    {"script_number": 3, "script_type": "Execution", "goal": "FPS 62%",
     "measurable": "0-0 Count Win%", "pitch_design_result": None},
    {"script_number": 4, "script_type": "Execution", "goal": "Pre2K Zone 52%",
     "measurable": "OS InZone%", "pitch_design_result": None},
    {"script_number": 5, "script_type": "Execution", "goal": "Pre2K Zone 52%",
     "measurable": "2/3 Win%", "pitch_design_result": None},
    {"script_number": 6, "script_type": "Pitch Design", "goal": "Develop gyro SL",
     "measurable": "SL Avg VB", "pitch_design_result": "1.2"},
]


def _rows(*rows):
    """Pads to the fixed 12-row script with blank rows."""
    out = [{"row_num": i, "pitch_type": p, "ball_info": b, "info": n, "result": r}
           for i, (p, b, n, r) in enumerate(rows, start=1)]
    out += [{"row_num": i, "pitch_type": "", "ball_info": "", "info": "", "result": ""}
            for i in range(len(out) + 1, SR.N_SCRIPT_ROWS + 1)]
    return out


SCRIPT_ROWS = {
    1: _rows(("Shuffle", "6 oz", "100%", "86.9"), ("Shuffle", "6 oz", "100%", "87.4"),
             ("Shuffle", "5 oz", "100%", "89.8"), ("Shuffle", "5 oz", "100%", "90.3"),
             ("Wind Up", "Baseball", "100%", "92.6"), ("Wind Up", "Baseball", "100%", "93.1"),
             ("Choice", "Baseball", "100%", "93.4"), ("Choice", "4 oz", "100%", "94.8"),
             ("Choice", "4 oz", "100%", "95.2"), ("Wind Up", "Baseball", "100%", "92.9")),
    2: _rows(("Shuffle", "Baseball", "80%", "87.1"), ("Shuffle", "Baseball", "85%", "88.6"),
             ("Wind Up", "Baseball", "90%", "89.9"), ("Wind Up", "Baseball", "95%", "91.2"),
             ("Wind Up", "Baseball", "100%", "92.4"), ("Stretch", "Baseball", "100%", "91.8"),
             ("Stretch", "Baseball", "100%", "92.0"), ("Wind Up", "Baseball", "100%", "92.7"),
             ("Wind Up", "Baseball", "95%", "91.1"), ("Wind Up", "Baseball", "100%", "92.3")),
    3: _rows(("FB", "Glove-side", "0-0", "W"), ("FB", "Arm-side", "0-0", "W"),
             ("SL", "Back foot", "0-0", "L"), ("FB", "Up", "0-0", "W"),
             ("CH", "Arm-side low", "0-0", "W"), ("FB", "Glove-side", "0-0", "L"),
             ("SL", "Glove-side", "0-0", "W"), ("FB", "Arm-side", "0-0", "W"),
             ("FB", "Down", "0-0", "W"), ("CH", "Arm-side low", "0-0", "L")),
    4: _rows(("SL", "Glove-side", "0-0", "In"), ("CH", "Arm-side", "1-0", "In"),
             ("SL", "Back foot", "0-1", "Out"), ("SL", "Glove-side", "1-1", "In"),
             ("CH", "Down", "0-0", "In"), ("SL", "Middle", "1-0", "In"),
             ("CH", "Arm-side", "1-1", "Out"), ("SL", "Glove-side", "0-1", "In"),
             ("CH", "Down", "2-1", "In"), ("SL", "Glove-side", "0-0", "Out")),
    5: _rows(("FB", "Up", "2-1", "W"), ("SL", "Glove-side", "1-2", "W"),
             ("FB", "Arm-side", "3-1", "L"), ("CH", "Down", "2-2", "W"),
             ("FB", "Glove-side", "2-0", "W"), ("SL", "Back foot", "0-2", "W"),
             ("FB", "Up", "3-2", "L"), ("CH", "Arm-side low", "1-2", "W"),
             ("FB", "Down", "2-1", "W"), ("SL", "Glove-side", "2-2", "L")),
    6: _rows(("SL", "Gyro grip", "Spike", ""), ("SL", "Gyro grip", "Spike", ""),
             ("SL", "Gyro grip", "Bullet", ""), ("SL", "Gyro grip", "Bullet", ""),
             ("SL", "Gyro grip", "Bullet", ""), ("SL", "Gyro grip", "Full intent", ""),
             ("SL", "Gyro grip", "Full intent", ""), ("SL", "Gyro grip", "Full intent", ""),
             ("FB", "4-seam", "Tunnel check", ""), ("SL", "Gyro grip", "Full intent", "")),
}

# Each script thrown 6-7 times across the fall, trending toward its goal with
# realistic bullpen-to-bullpen noise.
PEN = {
    1: [("2026-08-27", 91.2), ("2026-09-03", 91.8), ("2026-09-10", 91.5), ("2026-09-17", 92.6),
        ("2026-09-24", 93.0), ("2026-10-01", 93.4)],
    2: [("2026-08-28", 89.4), ("2026-09-04", 89.9), ("2026-09-11", 90.6), ("2026-09-18", 90.3),
        ("2026-09-25", 91.4), ("2026-10-02", 91.7)],
    3: [("2026-08-29", 52.0), ("2026-09-05", 58.0), ("2026-09-12", 55.0), ("2026-09-19", 61.0),
        ("2026-09-26", 64.0), ("2026-10-02", 67.0)],
    4: [("2026-08-30", 41.0), ("2026-09-06", 45.0), ("2026-09-13", 50.0), ("2026-09-20", 48.0),
        ("2026-09-27", 55.0), ("2026-10-03", 58.0)],
    5: [("2026-08-31", 46.0), ("2026-09-07", 50.0), ("2026-09-14", 54.0), ("2026-09-21", 53.0),
        ("2026-09-28", 59.0), ("2026-10-03", 62.0)],
    6: [("2026-09-01", 4.1), ("2026-09-08", 3.2), ("2026-09-15", 2.6), ("2026-09-22", 1.9),
        ("2026-09-29", 1.4), ("2026-10-03", 1.2)],
}

# The slider tightening toward a true gyro shape over the fall; fastball
# shape stable on the velo scripts.
MOVEMENT = {
    1: [("2026-08-27", "Fastball", 9.4, 16.8), ("2026-09-17", "Fastball", 9.1, 17.3),
        ("2026-10-01", "Fastball", 8.8, 17.6)],
    2: [("2026-09-04", "Fastball", 9.2, 17.0), ("2026-09-25", "Fastball", 8.9, 17.5)],
    6: [("2026-09-01", "Slider", -6.2, 4.1), ("2026-09-08", "Slider", -5.1, 3.2),
        ("2026-09-15", "Slider", -4.0, 2.6), ("2026-09-22", "Slider", -3.1, 1.9),
        ("2026-09-29", "Slider", -2.4, 1.4), ("2026-10-03", "Slider", -2.0, 1.2),
        ("2026-09-22", "Changeup", 14.2, 7.1), ("2026-10-03", "Changeup", 14.8, 6.4)],
}


def main(apply: bool, force: bool) -> int:
    pid = SR.DEMO_PLAYER_ID
    existing = SR.read_scripts(pid, SEASON, CYCLE)
    if (existing["goal"] != "").any() and not force:
        print(f"{SR.DEMO_PLAYER_NAME} ({pid}) already has a {SEASON} {CYCLE} plan -- "
              "not overwriting (coaches may have edited it). Pass --force to reseed.")
        return 0

    pen_rows = [{"script_number": n, "pen_date": d, "value": v}
                for n, sessions in PEN.items() for d, v in sessions]
    movement_rows = {n: [{"pen_date": d, "pitch_type": t, "hb": hb, "ivb": ivb}
                         for d, t, hb, ivb in rows] for n, rows in MOVEMENT.items()}
    print(f"{SR.DEMO_PLAYER_NAME} ({pid}), {SEASON} {CYCLE}: plan, {len(ENGINE)} engine "
          f"metrics, {len(GAS)} gas station rows, {len(SCRIPTS)} scripts, "
          f"{len(pen_rows)} pen results, "
          f"{sum(len(r) for r in movement_rows.values())} movement entries")
    if not apply:
        print("Dry run -- nothing written. Re-run with --apply.")
        return 0

    SR.save_all(
        pid, SEASON, CYCLE,
        plan_fields=PLAN,
        engine_rows=[{"metric_key": k, "base_value": b, "now_value": n} for k, b, n in ENGINE],
        gas_rows=[dict(r) for r in GAS],
        script_fields={s["script_number"]: {k: v for k, v in s.items() if k != "script_number"}
                       for s in SCRIPTS},
        script_pitch_rows=SCRIPT_ROWS,
        pen_rows=pen_rows,
        movement_rows=movement_rows,
    )
    print("Seeded.")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    sys.exit(main(apply="--apply" in args, force="--force" in args))
