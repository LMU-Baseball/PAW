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


def test_leaderboard_sorted_and_has_opponent_for_games():
    from app.data import seasons
    lb = V.leaderboard(seasons.current_season())
    assert list(lb.columns) == ["pitcher_name", "season_max", "season_max_date",
                                 "season_avg", "last_velo", "last_date", "versus", "trend"]
    assert len(lb) > 0   # roster present
    # sorted desc by season_max (nulls last)
    vals = lb["season_max"].dropna().tolist()
    assert vals == sorted(vals, reverse=True)
    is_null = lb["season_max"].isna().tolist()
    if any(is_null):
        first_null = is_null.index(True)
        assert all(is_null[first_null:])   # once nulls start, no more real values follow


def test_leaderboard_opponent_is_real_name_for_pitcher_with_a_game():
    # Spot-check against an actual opponent (excludes intrasquad "Live ABs"
    # scrimmages, where GAMES legitimately has home_team == away_team == "LMU"
    # -- not a bug, just not useful for verifying opponent detection).
    from app.data import seasons
    lb = V.leaderboard(seasons.current_season())
    has_game = lb[lb["last_date"].notna() & lb["versus"].notna()]
    real_opponent = has_game[has_game["versus"] != "LMU"]
    if real_opponent.empty:
        return  # no in-season vs.-other-team game appearances in this fixture
    versus = real_opponent.iloc[0]["versus"]
    assert isinstance(versus, str) and versus.strip() != ""
    assert "LMU" not in versus and "Loyola Marymount" not in versus
