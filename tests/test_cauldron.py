"""Competitive Cauldron storage layer (live DB): ensure_tables idempotency,
scoring seed idempotency, daily upsert-then-update semantics, and team
upserts."""
from app.data import cauldron as C


def test_ensure_tables_idempotent():
    C.ensure_tables()
    C.ensure_tables()  # second call is a no-op, not an error


def test_read_scoring_seeded_content_after_fresh_ensure_tables():
    """CRITICAL: a fresh deploy must not ship an inert board. read_scoring()
    lazily calls ensure_tables() itself (matches precalc's lazy-DDL pattern,
    so a missing table 500s never happen on first page load), and after
    seed_default_scoring() the config rows it seeds must actually be there,
    with a sane FIXED-vs-manual split."""
    C.ensure_tables()
    C.seed_default_scoring()

    sc = C.read_scoring()
    by_metric = {row["metric"]: row for _, row in sc.iterrows()}

    assert "strike_pct" in by_metric
    row = by_metric["strike_pct"]
    assert row["direction"] == "gte" and float(row["threshold"]) == 55.0
    assert not bool(row["is_manual"])

    assert "mod_command" in by_metric
    assert bool(by_metric["mod_command"]["is_manual"])

    # sort_order is a dense 1..N sequence matching read_scoring's own ORDER BY.
    orders = sorted(int(o) for o in sc["sort_order"])
    assert orders == list(range(1, len(sc) + 1))


def test_read_daily_and_read_teams_lazily_ensure_tables(monkeypatch):
    """read_daily/read_teams must never bare-SELECT against a table that
    might not exist yet on a fresh DB -- each calls ensure_tables() first."""
    calls = []
    monkeypatch.setattr(C, "ensure_tables", lambda engine=None: calls.append(engine))

    C.read_daily("2026-03-02")
    C.read_teams("cycle-1")

    assert len(calls) == 2


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


def test_score_value_fixed_and_manual_not_clobbered():
    row_gte = {"direction": "gte", "threshold": 55.0, "points_met": 20, "points_missed": -10, "min_sample": 0}
    assert C.score_value("strike_pct", 58.0, row_gte) == 20
    assert C.score_value("strike_pct", 50.0, row_gte) == -10
    row_lte = {"direction": "lte", "threshold": 6.0, "points_met": 15, "points_missed": -15, "min_sample": 0}
    assert C.score_value("bb_pct", 4.0, row_lte) == 15
    assert C.score_value("bb_pct", 9.0, row_lte) == -15
    assert C.score_value("x", None, row_gte) is None


def test_score_value_guards_manual_or_none_direction_row():
    """HARDEN: a manual-metric scoring row (direction=None, threshold=None)
    must return None, not raise -- score_value should never be called this
    way in practice (score_day/save_grid both skip is_manual rows before
    scoring), but a defensive guard keeps a future caller from crashing."""
    manual_row = {"direction": None, "threshold": None, "points_met": 20, "points_missed": -10}
    assert C.score_value("mod_command", 58.0, manual_row) is None
    bad_direction_row = {"direction": "eq", "threshold": 5.0, "points_met": 20, "points_missed": -10}
    assert C.score_value("x", 5.0, bad_direction_row) is None


def test_score_day_never_clobbers_manual(monkeypatch):
    import pandas as pd

    pid = 999999003
    play_date = "2026-03-03"
    metric = "strike_pct"

    C.ensure_tables()
    C.seed_default_scoring()
    try:
        # Coach enters a manual override for this (player, day, metric).
        C.upsert_daily([{"player_id": pid, "play_date": play_date, "metric": metric,
                         "raw_value": 99.0, "points": 777, "source": "manual"}], updated_by=1)

        # Force score_day's roster + compute to hand back exactly this
        # (synthetic) pitcher with a fresh raw value for the same metric --
        # if the manual guard didn't work, this would overwrite points=777.
        monkeypatch.setattr(
            C.pitching_caps, "lmu_pitchers",
            lambda season=None, start=None, end=None: pd.DataFrame(
                {"PitcherId": [pid], "Pitcher": ["Synthetic, Test"]}))
        monkeypatch.setattr(C, "compute_player_day", lambda p, d: {metric: 10.0})

        written = C.score_day(play_date, season="9999/0000")
        assert written == 0

        d = C.read_daily(play_date, pid)
        row = d[d["metric"] == metric].iloc[0]
        assert int(row["points"]) == 777
        assert row["source"] == "manual"
    finally:
        from app.db import get_engine
        from sqlalchemy import text
        with get_engine().begin() as c:
            c.execute(text("DELETE FROM cauldron_daily WHERE player_id=:p"), {"p": pid})


def test_score_day_smoke():
    from app.data import pitching_caps, seasons
    season = seasons.current_season()
    pid = int(pitching_caps.lmu_pitchers(season).iloc[0]["PitcherId"])
    apps = pitching_caps._pitcher_velo_appearances(pid)
    date = str(apps.sort_values("game_date")["game_date"].iloc[-1])

    C.ensure_tables()
    C.seed_default_scoring()
    written = C.score_day(date, season=season)
    assert isinstance(written, int) and written >= 0


def test_player_and_team_totals(monkeypatch):
    cycle_id = "9999-smoke"
    p1, p2 = 999999004, 999999005
    play_date = "2026-03-04"
    try:
        C.set_team(p1, cycle_id, "Team 1", updated_by=1)
        C.set_team(p2, cycle_id, "Team 2", updated_by=1)
        C.upsert_daily([
            {"player_id": p1, "play_date": play_date, "metric": "strike_pct",
             "raw_value": 58.0, "points": 20, "source": "auto"},
            {"player_id": p1, "play_date": play_date, "metric": "bb_pct",
             "raw_value": 4.0, "points": 15, "source": "auto"},
            {"player_id": p2, "play_date": play_date, "metric": "strike_pct",
             "raw_value": 40.0, "points": -10, "source": "auto"},
        ], updated_by=1)

        pt = C.player_totals(cycle_id)
        assert int(pt.loc[pt["player_id"] == p1, "total"].iloc[0]) == 35
        assert int(pt.loc[pt["player_id"] == p2, "total"].iloc[0]) == -10

        tt = C.team_totals(cycle_id)
        assert int(tt.loc[tt["team"] == "Team 1", "total"].iloc[0]) == 35
        assert int(tt.loc[tt["team"] == "Team 2", "total"].iloc[0]) == -10
    finally:
        from app.db import get_engine
        from sqlalchemy import text
        with get_engine().begin() as c:
            for t in ("cauldron_daily", "cauldron_teams"):
                c.execute(text(f"DELETE FROM {t} WHERE player_id IN (:p1, :p2)"),
                          {"p1": p1, "p2": p2})
