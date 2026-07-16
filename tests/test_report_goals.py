from app.reports.report_goals import GOALS, beats_goal, apply_goals


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
