"""Top Gun Velo Board coach grid: editable DataTable component + the
save-week -> upsert_entries row mapping."""
from app.dashboards.velo_board import grid as G


def test_coach_grid_is_editable_and_save_maps_rows(monkeypatch):
    comp = G.coach_grid("2025/2026", "2026-03-02")
    s = str(comp)
    assert "velo-grid" in s and "velo-save" in s
    assert "velo-season" in s and "velo-week" in s

    def _fake_upsert(rows, updated_by=None):
        captured["rows"] = rows
        captured["updated_by"] = updated_by

    captured = {}
    monkeypatch.setattr("app.data.velo_board.upsert_entries", _fake_upsert)

    G.save_rows([{"pitcher_id": 823008, "pitcher_name": "Behrens, Adam",
                  "velo_avg": 90.0, "velo_max": 93.0, "velo_goal": 95.0,
                  "assessment": 91.0, "max_pr": 93.0}],
                "2025/2026", "2026-03-02", updated_by=1)

    assert captured["rows"][0]["season_label"] == "2025/2026"
    assert captured["rows"][0]["week_start"] == "2026-03-02"
    assert captured["rows"][0]["pitcher_id"] == 823008
    assert captured["updated_by"] == 1


def test_save_rows_coerces_blank_numeric_to_none(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "app.data.velo_board.upsert_entries",
        lambda rows, updated_by=None: captured.setdefault("rows", rows))

    G.save_rows([{"pitcher_id": 823008, "pitcher_name": "Behrens, Adam",
                  "velo_avg": 90.0, "velo_max": 93.0, "velo_goal": "",
                  "assessment": None, "max_pr": 93.0}],
                "2025/2026", "2026-03-02")

    row = captured["rows"][0]
    assert row["velo_goal"] is None
    assert row["assessment"] is None
