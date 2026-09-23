"""Top Gun Velo Board coach controls + the save-board row mapping."""
import pandas as pd

from app.dashboards.velo_board import grid as G


def test_coach_controls_has_buttons_only():
    """Edit/Save live here; the Season/Cycle selectors moved to `board_filters`
    so that players get them too."""
    s = str(G.coach_controls())
    assert "velo-edit" in s and "velo-save" in s and "velo-save-status" in s
    assert "velo-season" not in s and "velo-cycle" not in s
    # the table is NOT here -- it's the shared velo-grid rendered by layout
    assert "velo-grid" not in s


def test_board_filters_has_selectors_and_no_write_controls():
    s = str(G.board_filters("2025/2026", "Fall"))
    assert "velo-season" in s and "velo-cycle" in s
    assert "velo-edit" not in s and "velo-save" not in s


def test_save_board_persists_goal_assessment_and_changed_override(monkeypatch):
    from app.data import velo_board
    ovr_calls, cyc_calls = [], []
    monkeypatch.setattr(
        velo_board, "set_override",
        lambda pid, season, season_max=None, season_avg=None, updated_by=None:
            ovr_calls.append((pid, season_max, season_avg)))
    monkeypatch.setattr(
        velo_board, "set_cycle_override",
        lambda pid, season, cycle, velo_goal=None, assessment=None, updated_by=None:
            cyc_calls.append((pid, cycle, velo_goal, assessment, updated_by)))
    # leaderboard baseline: A season_max 100.0 (a bad reading), season_avg 89.0
    monkeypatch.setattr(velo_board, "leaderboard", lambda s: pd.DataFrame(
        [{"pitcher_name": "A", "season_max": 100.0, "season_avg": 89.0}]))
    # cycle-bullpen auto Assessment baseline: 88.0
    monkeypatch.setattr(velo_board, "cycle_assessment", lambda s, c: {1: 88.0})

    G.save_board([{"pitcher_id": 1, "pitcher_name": "A",
                   "season_max": 94.0,      # CHANGED vs baseline 100 -> override
                   "season_avg": 89.0,      # unchanged -> no override
                   "velo_goal": 96.0, "assessment": 90.0}],   # CHANGED vs auto 88.0
                 "2025/2026", "Spring", updated_by=7)

    pid, om, oa = ovr_calls[0]
    assert pid == 1 and om == 94.0 and oa is None   # only the changed velo overrides
    cpid, ccycle, cgoal, cassess, cby = cyc_calls[0]
    assert cpid == 1 and ccycle == "Spring" and cgoal == 96.0 and cassess == 90.0 and cby == 7


def test_save_board_no_override_when_value_matches_baseline(monkeypatch):
    from app.data import velo_board
    ovr_calls, cyc_calls = [], []
    monkeypatch.setattr(
        velo_board, "set_override",
        lambda pid, season, season_max=None, season_avg=None, updated_by=None:
            ovr_calls.append((season_max, season_avg)))
    monkeypatch.setattr(
        velo_board, "set_cycle_override",
        lambda pid, season, cycle, velo_goal=None, assessment=None, updated_by=None:
            cyc_calls.append(assessment))
    monkeypatch.setattr(velo_board, "leaderboard", lambda s: pd.DataFrame(
        [{"pitcher_name": "A", "season_max": 95.0, "season_avg": 90.0}]))
    monkeypatch.setattr(velo_board, "cycle_assessment", lambda s, c: {1: 91.5})

    G.save_board([{"pitcher_id": 1, "pitcher_name": "A", "season_max": 95.0,
                   "season_avg": 90.0, "velo_goal": None, "assessment": 91.5}],
                 "2025/2026", "Spring")
    assert ovr_calls == [(None, None)]   # nothing changed -> null (no-op) override
    assert cyc_calls == [None]           # assessment matches auto -> null (no-op) override
