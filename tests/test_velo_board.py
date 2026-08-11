"""velo_board_entries storage layer (live DB): ensure_tables idempotency and
upsert-then-update-in-place semantics."""
from app.data import velo_board as V


def test_ensure_tables_idempotent():
    V.ensure_tables()
    V.ensure_tables()  # second call is a no-op, not an error


def test_upsert_inserts_then_updates():
    V.ensure_tables()
    row = {"pitcher_id": 999999001, "pitcher_name": "Test, Guy",
           "season_label": "2025/2026", "week_start": "2026-03-02",
           "velo_avg": 90.1, "velo_max": 93.0, "velo_goal": 95.0,
           "assessment": 91.0, "max_pr": 93.0}
    try:
        V.upsert_entries([row], updated_by=1)
        got = V.read_entries("2025/2026", "2026-03-02")
        r = got[got["pitcher_id"] == 999999001]
        assert len(r) == 1 and float(r.iloc[0]["velo_goal"]) == 95.0

        row["velo_goal"] = 96.0
        V.upsert_entries([row], updated_by=1)          # same PK -> update, not dup
        got2 = V.read_entries("2025/2026", "2026-03-02")
        r2 = got2[got2["pitcher_id"] == 999999001]
        assert len(r2) == 1 and float(r2.iloc[0]["velo_goal"]) == 96.0
    finally:
        from app.db import get_engine
        from sqlalchemy import text
        with get_engine().begin() as c:
            c.execute(text("DELETE FROM velo_board_entries WHERE pitcher_id=999999001"))


def test_week_start_is_monday():
    assert V.week_start_for("2026-03-04") == "2026-03-02"   # Wed -> Mon


def test_grid_rows_prefills_auto_velo_for_roster():
    from app.data import seasons
    season = seasons.current_season()
    # a week inside the season that has data; use the season end week
    _, e = seasons.season_bounds(season)
    wk = V.week_start_for(e)
    df = V.grid_rows(season, wk)
    assert set(["pitcher_id", "pitcher_name", "velo_avg", "velo_max", "velo_goal",
                "assessment", "max_pr", "change_avg", "change_max"]).issubset(df.columns)
    assert len(df) > 0   # roster present
