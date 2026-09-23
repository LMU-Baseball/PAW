"""velo_board_entries storage layer (live DB): ensure_tables idempotency and
upsert-then-update-in-place semantics."""
import pandas as pd
import pytest

from app.data import velo_board as V


def test_ensure_tables_idempotent():
    V.ensure_tables()
    V.ensure_tables()  # second call is a no-op, not an error


def test_velo_cycle_for_date_switches_on_jan_1():
    assert V.velo_cycle_for_date("2026-08-01") == "Fall"
    assert V.velo_cycle_for_date("2026-12-31") == "Fall"
    assert V.velo_cycle_for_date("2027-01-01") == "Spring"
    assert V.velo_cycle_for_date("2027-07-31") == "Spring"


def test_velo_cycle_bounds_fall_and_spring():
    assert V.velo_cycle_bounds("2026/2027", "Fall") == ("2026-08-01", "2026-12-31")
    assert V.velo_cycle_bounds("2026/2027", "Spring") == ("2027-01-01", "2027-07-31")


def test_velo_cycle_bounds_rejects_winter():
    with pytest.raises(ValueError, match="unknown cycle"):
        V.velo_cycle_bounds("2026/2027", "Winter")


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
    # A's 100.0 is a bad reading -> coach overrode season_max to 94.0 (avg untouched)
    monkeypatch.setattr(V, "read_overrides", lambda s: pd.DataFrame(
        [{"pitcher_id": 1, "season_max": 94.0, "season_avg": None}]))
    # A's auto cycle-bullpen Assessment is 88.0; B has none (absent from dict)
    monkeypatch.setattr(V, "cycle_assessment", lambda s, c: {1: 88.0})
    monkeypatch.setattr(V, "read_cycle_overrides", lambda s, c: pd.DataFrame(
        [{"pitcher_id": 1, "velo_goal": 96.0, "assessment": None}]))

    df = V.board_rows("2025/2026", "Spring")
    by_id = {int(r["pitcher_id"]): r for _, r in df.iterrows()}
    assert by_id[1]["season_max"] == 94.0        # override applied
    assert by_id[1]["season_avg"] == 89.0        # None override -> keep computed
    assert by_id[1]["velo_goal"] == 96.0         # cycle-scoped goal merged in
    assert by_id[1]["cycle"] == "Spring"
    assert by_id[1]["assessment"] == 88.0        # auto cycle-bullpen max, no override
    assert pd.isna(by_id[2]["assessment"])       # no bullpen data this cycle
    # re-ranked by effective season_max: B (95) now above the corrected A (94)
    assert int(df.iloc[0]["pitcher_id"]) == 2
    assert int(df.iloc[1]["pitcher_id"]) == 1


def test_board_rows_assessment_override_beats_auto(monkeypatch):
    from app.data import pitching_caps
    roster = pd.DataFrame([{"PitcherId": 1, "Pitcher": "A"}])
    monkeypatch.setattr(pitching_caps, "lmu_pitchers", lambda season=None: roster)
    monkeypatch.setattr(V, "leaderboard", lambda s: pd.DataFrame(
        [{"pitcher_name": "A", "season_max": 90.0, "season_max_date": "2026-04-01",
          "season_avg": 88.0, "last_velo": 88.0, "last_date": "2026-04-01",
          "versus": "SMC", "trend": 0.0}]))
    monkeypatch.setattr(V, "read_overrides", lambda s: pd.DataFrame(
        columns=["pitcher_id", "season_max", "season_avg"]))
    monkeypatch.setattr(V, "cycle_assessment", lambda s, c: {1: 88.0})
    # coach corrected the auto 88.0 up to 91.0
    monkeypatch.setattr(V, "read_cycle_overrides", lambda s, c: pd.DataFrame(
        [{"pitcher_id": 1, "velo_goal": None, "assessment": 91.0}]))

    df = V.board_rows("2025/2026", "Spring")
    assert df.iloc[0]["assessment"] == 91.0


def test_clip_velo_outliers_drops_far_above_median():
    # a ~90 mph pitcher with a bullpen calibration glitch (~99-100)
    df = pd.DataFrame({"rel_speed": [90, 91, 92, 89, 90, 91, 99.98, 99.8, 99.6]})
    out = V._clip_velo_outliers(df)
    assert out["rel_speed"].max() < 95      # the glitch cluster is dropped
    assert len(out) == 6                      # the six ~90 readings kept


def test_clip_velo_outliers_keeps_genuine_hard_thrower():
    # median already high -> real velos stay under median + margin
    df = pd.DataFrame({"rel_speed": [98, 99, 100, 99, 98, 97, 99, 100]})
    assert len(V._clip_velo_outliers(df)) == 8


def test_clip_velo_outliers_untouched_when_too_few_readings():
    df = pd.DataFrame({"rel_speed": [99.9, 100.0]})   # < min sample
    assert len(V._clip_velo_outliers(df)) == 2


def test_leaderboard_clamps_bullpen_velo_outlier():
    """Live: Behrens' 99.98 bullpen glitch (real max ~94) must be clamped out of
    his Season Max on the board."""
    from app.data import seasons, cache
    cache.clear_all()
    lb = V.leaderboard(seasons.current_season())
    row = lb[lb["pitcher_name"].str.contains("Behrens", case=False, na=False)]
    if not row.empty and row.iloc[0]["season_max"] is not None:
        assert float(row.iloc[0]["season_max"]) < 97.0


def test_set_override_roundtrip():
    V.ensure_tables()
    V.set_override(9990001, "TEST-OVR", season_max=93.5, season_avg=88.2, updated_by=1)
    ovr = V.read_overrides("TEST-OVR")
    row = ovr[ovr["pitcher_id"] == 9990001].iloc[0]
    assert float(row["season_max"]) == 93.5
    assert float(row["season_avg"]) == 88.2


def test_set_cycle_override_roundtrip():
    V.ensure_tables()
    V.set_cycle_override(9990002, "TEST-OVR", "Fall", velo_goal=95.0, assessment=92.3,
                         updated_by=1)
    ovr = V.read_cycle_overrides("TEST-OVR", "Fall")
    row = ovr[ovr["pitcher_id"] == 9990002].iloc[0]
    assert float(row["velo_goal"]) == 95.0
    assert float(row["assessment"]) == 92.3
    # a different cycle for the same pitcher/season is untouched
    other = V.read_cycle_overrides("TEST-OVR", "Spring")
    assert other[other["pitcher_id"] == 9990002].empty


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
