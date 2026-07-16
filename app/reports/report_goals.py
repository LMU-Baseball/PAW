"""Goal benchmarks for the pitcher report + conditional-highlight logic.

PLACEHOLDER numbers seeded from last year's sample report; confirm the real
targets with the coaching staff. Keys match the metric keys produced by
app.data.pitching.
"""
from __future__ import annotations

GOALS: dict[str, float] = {
    "strike_pct": 55.0,
    "fps_pct": 65.0,
    "ea_pct": 70.0,
    "pre2k_pct": 48.0,
    "twok_kill_pct": 55.0,
    "k_pct": 27.0,
    "bb_pct": 6.0,
    "barrel_pct": 7.0,
}

# Metrics where a LOWER value is better (green when value <= goal).
LOWER_IS_BETTER: set[str] = {"bb_pct", "barrel_pct"}


def beats_goal(key: str, value: float | None) -> bool | None:
    """True/False if the value meets its goal; None if no goal or no value."""
    goal = GOALS.get(key)
    if goal is None or value is None:
        return None
    return value <= goal if key in LOWER_IS_BETTER else value >= goal


def apply_goals(rows: list[dict]) -> list[dict]:
    """Add `goal` and `beats` to each metric row (rows have `key`,`value_pct`)."""
    for r in rows:
        r["goal"] = GOALS.get(r["key"])
        r["beats"] = beats_goal(r["key"], r.get("value_pct"))
    return rows
