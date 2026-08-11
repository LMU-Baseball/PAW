"""Competitive Cauldron coach grid: editable DataTable component + the
save-grid -> set_team/upsert_daily row mapping."""
import pandas as pd

from app.dashboards.cauldron import grid as G


def _scoring_df():
    return pd.DataFrame([
        {"metric": "strike_pct", "label": "Strike%", "threshold": 55.0,
         "direction": "gte", "points_met": 20, "points_missed": -10,
         "is_manual": False, "min_sample": 5, "sort_order": 1},
        {"metric": "mod_command", "label": "Mod Command", "threshold": None,
         "direction": None, "points_met": 20, "points_missed": -10,
         "is_manual": True, "min_sample": None, "sort_order": 2},
    ])


def _roster_df():
    return pd.DataFrame([{"PitcherId": 823008, "Pitcher": "Behrens, Adam"}])


def _patch_reads(monkeypatch, teams_df=None, daily_df=None, computed=None):
    monkeypatch.setattr("app.data.cauldron.read_scoring", lambda: _scoring_df())
    monkeypatch.setattr("app.data.pitching_caps.lmu_pitchers", lambda season=None: _roster_df())
    monkeypatch.setattr("app.data.cauldron.read_teams",
                         lambda cycle_id: teams_df if teams_df is not None else pd.DataFrame(
                             columns=["player_id", "cycle_id", "team"]))
    monkeypatch.setattr("app.data.cauldron.read_daily",
                         lambda play_date=None, player_id=None: daily_df if daily_df is not None
                         else pd.DataFrame(columns=["player_id", "play_date", "metric", "points", "source"]))
    monkeypatch.setattr("app.data.cauldron.compute_player_day",
                         lambda pid, play_date: computed if computed is not None else {})


def test_coach_grid_is_editable_and_has_required_ids(monkeypatch):
    _patch_reads(monkeypatch)

    comp = G.coach_grid("2026-03-02", "cycle-1", "2025/2026")
    s = str(comp)

    assert "cauldron-grid" in s
    assert "cauldron-save" in s
    assert "cauldron-recompute" in s
    assert "cauldron-date" in s
    assert "cauldron-cycle" in s
    assert "cauldron-save-status" in s
    assert "editable=True" in s


def test_coach_grid_prefills_team_and_scores_auto_metric_live(monkeypatch):
    teams_df = pd.DataFrame([{"player_id": 823008, "cycle_id": "cycle-1", "team": "Team 2"}])
    _patch_reads(monkeypatch, teams_df=teams_df, computed={"strike_pct": 60.0})

    comp = G.coach_grid("2026-03-02", "cycle-1", "2025/2026")
    s = str(comp)

    # Team 2 pre-filled from read_teams, and the AUTO metric scored live
    # (60.0 >= 55.0 threshold -> points_met = 20) since no stored daily row.
    assert "Team 2" in s
    assert "'strike_pct': 20" in s
    # MANUAL metric has no auto value to show.
    assert "'mod_command': None" in s


def test_save_grid_routes_team_to_set_team(monkeypatch):
    captured = {}
    monkeypatch.setattr("app.data.cauldron.read_scoring", lambda: _scoring_df())
    monkeypatch.setattr("app.data.cauldron.compute_player_day", lambda pid, play_date: {})
    monkeypatch.setattr(
        "app.data.cauldron.set_team",
        lambda pid, cycle_id, team, updated_by=None: captured.setdefault(
            "team_call", (pid, cycle_id, team, updated_by)))
    monkeypatch.setattr("app.data.cauldron.upsert_daily", lambda rows, updated_by=None: None)

    G.save_grid([{"player_id": 823008, "player": "Behrens, Adam", "team": "Team 1"}],
                "2026-03-02", "cycle-1", updated_by=7)

    assert captured["team_call"] == (823008, "cycle-1", "Team 1", 7)


def test_save_grid_routes_filled_metric_cell_to_upsert_daily_as_manual(monkeypatch):
    captured = {}
    monkeypatch.setattr("app.data.cauldron.read_scoring", lambda: _scoring_df())
    # No stored/live raw value for strike_pct -> no AUTO baseline to match,
    # so a filled cell always falls back to 'manual'.
    monkeypatch.setattr("app.data.cauldron.compute_player_day", lambda pid, play_date: {})
    monkeypatch.setattr("app.data.cauldron.set_team", lambda *a, **k: None)
    def _fake_upsert_daily(rows, updated_by=None):
        captured["rows"] = rows
        captured["updated_by"] = updated_by

    monkeypatch.setattr("app.data.cauldron.upsert_daily", _fake_upsert_daily)

    G.save_grid([{"player_id": 823008, "player": "Behrens, Adam", "team": "Team 1",
                  "strike_pct": 20, "mod_command": ""}],
                "2026-03-02", "cycle-1", updated_by=7)

    rows = captured["rows"]
    assert len(rows) == 1  # the blank mod_command cell was skipped, not written
    row = rows[0]
    assert row["player_id"] == 823008
    assert row["metric"] == "strike_pct"
    assert row["points"] == 20
    assert row["raw_value"] is None
    assert row["source"] == "manual"
    assert row["play_date"] == "2026-03-02"
    assert captured["updated_by"] == 7


def test_save_grid_coerces_blank_and_nan_metric_cells_to_skipped(monkeypatch):
    monkeypatch.setattr("app.data.cauldron.read_scoring", lambda: _scoring_df())
    monkeypatch.setattr("app.data.cauldron.compute_player_day", lambda pid, play_date: {})
    monkeypatch.setattr("app.data.cauldron.set_team", lambda *a, **k: None)
    calls = []
    monkeypatch.setattr("app.data.cauldron.upsert_daily",
                         lambda rows, updated_by=None: calls.append(rows))

    G.save_grid([{"player_id": 823008, "player": "Behrens, Adam", "team": None,
                  "strike_pct": "", "mod_command": None}],
                "2026-03-02", "cycle-1")

    # No team written (blank), no metric rows written (both blank/None) ->
    # upsert_daily never even called since daily_rows ends up empty.
    assert calls == []


def test_save_grid_tags_source_auto_vs_manual_vs_override(monkeypatch):
    """CRITICAL: an untouched AUTO cell must save as source='auto' (so
    Recompute can keep refreshing it), NOT a blanket 'manual' -- that would
    permanently defeat Recompute the first time a coach ever hits Save on a
    day with Trackman data."""
    monkeypatch.setattr("app.data.cauldron.read_scoring", lambda: _scoring_df())
    # strike_pct raw=60.0 -> score_value(60, threshold=55, gte) = points_met = 20.
    # That 20 is exactly what coach_grid pre-filled the cell with.
    monkeypatch.setattr("app.data.cauldron.compute_player_day",
                         lambda pid, play_date: {"strike_pct": 60.0})
    monkeypatch.setattr("app.data.cauldron.set_team", lambda *a, **k: None)
    captured = {}
    monkeypatch.setattr("app.data.cauldron.upsert_daily",
                         lambda rows, updated_by=None: captured.setdefault("rows", rows))

    G.save_grid([
        {"player_id": 823008, "player": "Behrens, Adam", "team": None,
         "strike_pct": 20,     # unchanged AUTO prefill (baseline == 20)
         "mod_command": 15},   # MANUAL metric, filled
        {"player_id": 900001, "player": "Other, Pitcher", "team": None,
         "strike_pct": -10,    # coach overrode the AUTO prefill (baseline == 20)
         "mod_command": ""},   # blank -> skipped
    ], "2026-03-02", "cycle-1")

    rows = {(r["player_id"], r["metric"]): r for r in captured["rows"]}
    assert len(captured["rows"]) == 3  # the blank mod_command cell was skipped

    unchanged_auto = rows[(823008, "strike_pct")]
    assert unchanged_auto["points"] == 20
    assert unchanged_auto["source"] == "auto"

    manual_metric = rows[(823008, "mod_command")]
    assert manual_metric["points"] == 15
    assert manual_metric["source"] == "manual"

    overridden_auto = rows[(900001, "strike_pct")]
    assert overridden_auto["points"] == -10
    assert overridden_auto["source"] == "manual"
