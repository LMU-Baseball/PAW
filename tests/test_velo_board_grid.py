"""Top Gun Velo Board coach controls + the save-board row mapping."""
import pandas as pd

from app.dashboards.velo_board import grid as G


def test_coach_controls_has_buttons_only():
    """Edit/Save live here; the Season/Week selectors moved to `board_filters`
    so that players get them too."""
    s = str(G.coach_controls())
    assert "velo-edit" in s and "velo-save" in s and "velo-save-status" in s
    assert "velo-season" not in s and "velo-week" not in s
    # the table is NOT here -- it's the shared velo-grid rendered by layout
    assert "velo-grid" not in s


def test_board_filters_has_selectors_and_no_write_controls():
    s = str(G.board_filters("2025/2026", "2026-03-02"))
    assert "velo-season" in s and "velo-week" in s
    assert "velo-edit" not in s and "velo-save" not in s


def test_save_board_persists_goal_assessment_and_changed_override(monkeypatch):
    from app.data import velo_board
    entry_calls, ovr_calls = [], []
    monkeypatch.setattr(velo_board, "upsert_entries",
                        lambda rows, updated_by=None: entry_calls.append((rows, updated_by)))
    monkeypatch.setattr(
        velo_board, "set_override",
        lambda pid, season, season_max=None, season_avg=None, updated_by=None:
            ovr_calls.append((pid, season_max, season_avg)))
    # leaderboard baseline: A season_max 100.0 (a bad reading), season_avg 89.0
    monkeypatch.setattr(velo_board, "leaderboard", lambda s: pd.DataFrame(
        [{"pitcher_name": "A", "season_max": 100.0, "season_avg": 89.0}]))

    G.save_board([{"pitcher_id": 1, "pitcher_name": "A",
                   "season_max": 94.0,      # CHANGED vs baseline 100 -> override
                   "season_avg": 89.0,      # unchanged -> no override
                   "velo_goal": 96.0, "assessment": 90.0}],
                 "2025/2026", "2026-03-02", updated_by=7)

    rows, ub = entry_calls[0]
    assert rows[0]["velo_goal"] == 96.0 and rows[0]["assessment"] == 90.0
    assert rows[0]["week_start"] == "2026-03-02" and ub == 7
    pid, om, oa = ovr_calls[0]
    assert pid == 1 and om == 94.0 and oa is None   # only the changed velo overrides


def test_save_board_no_override_when_value_matches_baseline(monkeypatch):
    from app.data import velo_board
    ovr_calls = []
    monkeypatch.setattr(velo_board, "upsert_entries", lambda rows, updated_by=None: None)
    monkeypatch.setattr(
        velo_board, "set_override",
        lambda pid, season, season_max=None, season_avg=None, updated_by=None:
            ovr_calls.append((season_max, season_avg)))
    monkeypatch.setattr(velo_board, "leaderboard", lambda s: pd.DataFrame(
        [{"pitcher_name": "A", "season_max": 95.0, "season_avg": 90.0}]))

    G.save_board([{"pitcher_id": 1, "pitcher_name": "A", "season_max": 95.0,
                   "season_avg": 90.0, "velo_goal": None, "assessment": None}],
                 "2025/2026", "2026-03-02")
    assert ovr_calls == [(None, None)]   # nothing changed -> null (no-op) override
