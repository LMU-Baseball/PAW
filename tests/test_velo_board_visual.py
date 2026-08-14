"""Top Gun Velo Board visual layer: header renders the wordmark, leaderboard
table renders ranked rows."""
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


def test_leaderboard_view_renders_rows_and_header():
    lb = pd.DataFrame([
        {"pitcher_name": "A, B", "season_max": 95.8, "season_max_date": "2026-03-15",
         "season_avg": 92.8, "last_velo": 93.0, "last_date": "2026-03-21",
         "versus": "Portland", "trend": -0.5},
        {"pitcher_name": "C, D", "season_max": 90.0, "season_max_date": "2026-02-10",
         "season_avg": 87.0, "last_velo": 85.3, "last_date": "2026-03-03",
         "versus": "UCSB", "trend": 2.3},
    ])
    view = V.leaderboard_view(lb)
    s = str(view)
    header = str(V.top_gun_header())
    assert "LMU" in header and "VELO BOARD" in header
    assert "A, B" in s and "Portland" in s


def test_leaderboard_view_handles_empty_df():
    lb = pd.DataFrame(columns=["pitcher_name", "season_max", "season_max_date",
                                "season_avg", "last_velo", "last_date", "versus", "trend"])
    view = V.leaderboard_view(lb)
    assert view is not None


def test_leaderboard_view_formats_dates_and_missing_values():
    lb = pd.DataFrame([
        {"pitcher_name": "E, F", "season_max": 88.25, "season_max_date": "2026-04-01",
         "season_avg": 85.0, "last_velo": None, "last_date": None,
         "versus": None, "trend": None},
    ])
    s = str(V.leaderboard_view(lb))
    assert "4/1" in s
    assert "—" in s
