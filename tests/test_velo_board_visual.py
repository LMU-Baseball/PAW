"""Top Gun Velo Board visual layer: header renders the wordmark, the unified
board DataTable renders editable columns + heat-ranked rows."""
import pandas as pd

from app.dashboards.velo_board import visual as V


def test_board_table_editable_columns_hidden_id_and_trend_format():
    df = pd.DataFrame([
        {"pitcher_id": 1, "pitcher_name": "A", "season_max": 100.0,
         "season_max_date": "2026-04-15", "season_avg": 89.0, "last_velo": 89.3,
         "last_date": "2026-05-15", "versus": "USD", "trend": 0.4,
         "velo_goal": 96.0, "assessment": 90.0},
    ])
    dt = V.board_table(df)
    assert dt.id == "velo-grid"
    col_by_id = {c["id"]: c for c in dt.columns}
    # editable columns carry NO explicit editable flag (inherit the table's,
    # which the Edit button toggles); read-only columns are pinned False
    for cid in ("season_max", "season_avg", "velo_goal", "assessment"):
        assert "editable" not in col_by_id[cid]
    assert col_by_id["pitcher_name"]["editable"] is False
    # pitcher_id rides in the data but is not a visible column
    assert "pitcher_id" not in col_by_id
    assert dt.data[0]["pitcher_id"] == 1
    # trend rendered with a direction arrow
    assert dt.data[0]["trend"].startswith("▲")
    # table starts locked
    assert dt.editable is False


def test_board_table_empty_and_missing_values():
    # empty frame -> a DataTable with no rows (not a crash)
    dt = V.board_table(pd.DataFrame())
    assert dt.id == "velo-grid" and dt.data == []
    # missing read-only values format to em-dashes; date to M/D
    df = pd.DataFrame([{"pitcher_id": 1, "pitcher_name": "E, F", "season_max": 88.25,
                        "season_max_date": "2026-04-01", "season_avg": 85.0,
                        "last_velo": None, "last_date": None, "versus": None, "trend": None,
                        "velo_goal": None, "assessment": None}])
    rec = V.board_table(df).data[0]
    assert rec["last_velo"] == "—" and rec["last_date"] == "—"
    assert rec["season_max_date"] == "4/1"


def test_top_gun_header_has_wordmark():
    header = str(V.top_gun_header())
    assert "LMU" in header and "VELO BOARD" in header
