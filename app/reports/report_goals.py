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

# Metrics where a LOWER value is better (blue when value <= goal).
LOWER_IS_BETTER: set[str] = {"bb_pct", "barrel_pct"}

# Relative band (fraction of the goal) that separates a "slight" beat/miss from a
# "strong" one, for the 4-tier chip coloring. Within +/-10% of the goal (relative)
# = barely met/missed; beyond = exceeded/badly missed. Using a RELATIVE band keeps
# a 6%-goal metric (BB%) and a 70%-goal metric (E&A%) on the same footing.
# PROVISIONAL — coaches may want a wider/narrower band.
TIER_BAND = 0.10

# tier key -> CSS chip class (see report.css):
#   good-strong = dark blue  (exceeded goal)     good = light blue (barely met)
#   bad         = light red  (barely missed)     bad-strong = dark red (badly missed)
_TIER_CLASS = {
    "good_strong": "good-strong",
    "good_slight": "good",
    "bad_slight": "bad",
    "bad_strong": "bad-strong",
}


def beats_goal(key: str, value: float | None) -> bool | None:
    """True/False if the value meets its goal; None if no goal or no value."""
    goal = GOALS.get(key)
    if goal is None or value is None:
        return None
    return value <= goal if key in LOWER_IS_BETTER else value >= goal


def goal_tier(key: str, value: float | None) -> str | None:
    """Four-way tier vs goal for chip coloring.

    Returns 'good_strong' (exceeded) | 'good_slight' (barely met) |
    'bad_slight' (barely missed) | 'bad_strong' (badly missed), or None when
    there is no goal/value. "Strong" vs "slight" is decided by TIER_BAND, a
    relative band around the goal.
    """
    goal = GOALS.get(key)
    if goal is None or value is None or goal == 0:
        return None
    # signed margin in the "good" direction (positive = better than goal)
    margin = (goal - value) if key in LOWER_IS_BETTER else (value - goal)
    strong = abs(margin) / abs(goal) > TIER_BAND
    if margin >= 0:
        return "good_strong" if strong else "good_slight"
    return "bad_strong" if strong else "bad_slight"


def apply_goals(rows: list[dict]) -> list[dict]:
    """Add `goal`, `beats`, `tier`, and `chip` (CSS class) to each metric row."""
    for r in rows:
        r["goal"] = GOALS.get(r["key"])
        r["beats"] = beats_goal(r["key"], r.get("value_pct"))
        r["tier"] = goal_tier(r["key"], r.get("value_pct"))
        r["chip"] = _TIER_CLASS.get(r["tier"], "")
    return rows
