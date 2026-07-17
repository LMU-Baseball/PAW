from app.reports.report_goals import (
    GOALS, TIER_BAND, apply_goals, beats_goal, goal_tier)


def test_higher_is_better_beats():
    assert beats_goal("strike_pct", 60.0) is True      # 60 >= 55 goal
    assert beats_goal("strike_pct", 50.0) is False


def test_lower_is_better_beats():
    assert beats_goal("bb_pct", 4.0) is True            # 4 <= 6 goal
    assert beats_goal("bb_pct", 9.0) is False


def test_unknown_key_or_none_value_is_none():
    assert beats_goal("strike_pct", None) is None
    assert beats_goal("no_such_metric", 10.0) is None


def test_apply_goals_adds_goal_and_beats():
    rows = [{"key": "strike_pct", "value_pct": 60.0},
            {"key": "bb_pct", "value_pct": 9.0}]
    out = apply_goals(rows)
    assert out[0]["goal"] == GOALS["strike_pct"] and out[0]["beats"] is True
    assert out[1]["goal"] == GOALS["bb_pct"] and out[1]["beats"] is False


def test_goal_tier_four_way_higher_is_better():
    goal = GOALS["strike_pct"]  # 55, higher is better
    # just over goal (within TIER_BAND) -> barely met
    assert goal_tier("strike_pct", goal + 0.1) == "good_slight"
    # well over goal -> exceeded
    assert goal_tier("strike_pct", goal * (1 + TIER_BAND) + 1) == "good_strong"
    # just under goal -> barely missed
    assert goal_tier("strike_pct", goal - 0.1) == "bad_slight"
    # well under goal -> badly missed
    assert goal_tier("strike_pct", goal * (1 - TIER_BAND) - 1) == "bad_strong"


def test_goal_tier_lower_is_better_inverts():
    goal = GOALS["bb_pct"]  # 6, lower is better
    assert goal_tier("bb_pct", goal - 0.1) == "good_slight"   # just under -> barely met
    assert goal_tier("bb_pct", 0.0) == "good_strong"          # far under -> exceeded
    assert goal_tier("bb_pct", goal + 0.1) == "bad_slight"    # just over -> barely missed
    assert goal_tier("bb_pct", goal * 3) == "bad_strong"      # far over -> badly missed


def test_goal_tier_none_when_no_goal_or_value():
    assert goal_tier("strike_pct", None) is None
    assert goal_tier("no_such_metric", 10.0) is None


def test_apply_goals_adds_tier_and_chip_class():
    rows = [{"key": "strike_pct", "value_pct": 90.0},   # far over -> dark blue
            {"key": "k_pct", "value_pct": 0.0}]          # far under -> dark red
    out = apply_goals(rows)
    assert out[0]["tier"] == "good_strong" and out[0]["chip"] == "good-strong"
    assert out[1]["tier"] == "bad_strong" and out[1]["chip"] == "bad-strong"
