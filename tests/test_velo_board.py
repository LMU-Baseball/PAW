"""velo_board_entries storage layer (live DB): ensure_tables idempotency and
upsert-then-update-in-place semantics."""
import pandas as pd

from app.data import velo_board as V


def test_ensure_tables_idempotent():
    V.ensure_tables()
    V.ensure_tables()  # second call is a no-op, not an error


def test_board_rows_applies_override_and_reranks(monkeypatch):
    from app.data import pitching_caps
    roster = pd.DataFrame([{"PitcherId": 1, "Pitcher": "A"},
                           {"PitcherId": 2, "Pitcher": "B"}])
    monkeypatch.setattr(pitching_caps, "lmu_pitchers", lambda season=None: roster)
    lb = pd.DataFrame([
        {"pitcher_name": "A", "season_max": 100.0, "season_max_date": "2026-04-15",
         "season_avg": 89.0, "last_velo": 89.0, "last_date": "2026-05-15",
         "versus": "USD", "trend": 0.4},
        {"pitcher_name": "B", "season_max": 95.0, "season_max_date": "2026-04-28",
         "season_avg": 91.0, "last_velo": 91.0, "last_date": "2026-05-08",
         "versus": "SMC", "trend": 0.1},
    ])
    monkeypatch.setattr(V, "leaderboard", lambda s: lb)
    monkeypatch.setattr(V, "read_entries", lambda s, w=None: pd.DataFrame(
        [{"pitcher_id": 1, "velo_goal": 96.0, "assessment": 90.0}]))
    # A's 100.0 is a bad reading -> coach overrode season_max to 94.0 (avg untouched)
    monkeypatch.setattr(V, "read_overrides", lambda s: pd.DataFrame(
        [{"pitcher_id": 1, "season_max": 94.0, "season_avg": None}]))

    df = V.board_rows("2025/2026", "2026-05-11")
    by_id = {int(r["pitcher_id"]): r for _, r in df.iterrows()}
    assert by_id[1]["season_max"] == 94.0        # override applied
    assert by_id[1]["season_avg"] == 89.0        # None override -> keep computed
    assert by_id[1]["velo_goal"] == 96.0         # weekly goal merged in
    # re-ranked by effective season_max: B (95) now above the corrected A (94)
    assert int(df.iloc[0]["pitcher_id"]) == 2
    assert int(df.iloc[1]["pitcher_id"]) == 1


def test_set_override_roundtrip():
    V.ensure_tables()
    V.set_override(9990001, "TEST-OVR", season_max=93.5, season_avg=88.2, updated_by=1)
    ovr = V.read_overrides("TEST-OVR")
    row = ovr[ovr["pitcher_id"] == 9990001].iloc[0]
    assert float(row["season_max"]) == 93.5
    assert float(row["season_avg"]) == 88.2


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


def test_grid_rows_honors_stored_override_over_trackman():
    """Weekly rows are stored snapshots: once a coach saves a row for a
    (pitcher, season, week), grid_rows must return the STORED velo_max, not
    the value recomputed from Trackman (weekly_velo)."""
    from app.data import pitching_caps, seasons
    season = seasons.current_season()
    roster = pitching_caps.lmu_pitchers(season)
    assert not roster.empty
    pid = int(roster.iloc[0]["PitcherId"])
    name = str(roster.iloc[0]["Pitcher"])
    wk = "2030-01-07"  # a Monday far outside any real Trackman data --
                       # guarantees no pre-existing stored row to collide with
                       # and a recomputed Trackman value of None for contrast.
    row = {"pitcher_id": pid, "pitcher_name": name, "season_label": season,
           "week_start": wk, "velo_avg": 88.8, "velo_max": 111.1,
           "velo_goal": None, "assessment": None, "max_pr": 111.1}
    try:
        V.upsert_entries([row], updated_by=1)
        df = V.grid_rows(season, wk)
        r = df[df["pitcher_id"] == pid]
        assert len(r) == 1
        assert float(r.iloc[0]["velo_max"]) == 111.1
        assert float(r.iloc[0]["velo_avg"]) == 88.8
    finally:
        from app.db import get_engine
        from sqlalchemy import text
        with get_engine().begin() as c:
            c.execute(text("DELETE FROM velo_board_entries WHERE pitcher_id=:p AND week_start=:w"),
                      {"p": pid, "w": wk})


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
