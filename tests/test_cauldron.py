"""Competitive Cauldron storage layer (live DB): ensure_tables idempotency,
scoring seed idempotency, daily upsert-then-update semantics, and team
upserts."""
from app.data import cauldron as C


def test_ensure_tables_idempotent():
    C.ensure_tables()
    C.ensure_tables()  # second call is a no-op, not an error


def test_daily_upsert_and_team_and_scoring_seed():
    C.ensure_tables()
    C.seed_default_scoring()
    C.seed_default_scoring()  # idempotent: re-seed must not error or duplicate

    sc = C.read_scoring()
    assert "strike_pct" in set(sc["metric"]) and len(sc) >= 10

    try:
        C.upsert_daily([{"player_id": 999999002, "play_date": "2026-03-02",
                         "metric": "strike_pct", "raw_value": 58.0, "points": 20,
                         "source": "auto"}], updated_by=1)
        d = C.read_daily("2026-03-02", 999999002)
        assert int(d.iloc[0]["points"]) == 20

        # same PK -> update in place, not a duplicate row
        C.upsert_daily([{"player_id": 999999002, "play_date": "2026-03-02",
                         "metric": "strike_pct", "raw_value": 40.0, "points": -10,
                         "source": "auto"}], updated_by=1)
        d2 = C.read_daily("2026-03-02", 999999002)
        assert len(d2) == 1 and int(d2.iloc[0]["points"]) == -10

        C.set_team(999999002, "2026-c1", "Team 1", updated_by=1)
        assert C.read_teams("2026-c1").query("player_id == 999999002").iloc[0]["team"] == "Team 1"
    finally:
        from app.db import get_engine
        from sqlalchemy import text
        with get_engine().begin() as c:
            for t in ("cauldron_daily", "cauldron_teams"):
                c.execute(text(f"DELETE FROM {t} WHERE player_id=999999002"))


def test_compute_player_day_standard_metrics():
    from app.data import cauldron as C, pitching_caps, seasons
    # pick a pitcher + a date they pitched (derive from _pitcher_velo_appearances)
    pid = int(pitching_caps.lmu_pitchers(seasons.current_season()).iloc[0]["PitcherId"])
    apps = pitching_caps._pitcher_velo_appearances(pid)
    date = str(apps.sort_values("game_date")["game_date"].iloc[-1])
    m = C.compute_player_day(pid, date)
    assert "strike_pct" in m and (m["strike_pct"] is None or 0 <= m["strike_pct"] <= 100)
    for stub in ("early_ahead", "pre2k_zone", "twok_kill", "count_work"):
        assert m.get(stub) is None   # not yet defined
    assert C.compute_player_day(pid, "1900-01-01") == {}   # no data
