"""lmu_roster: the LMU-only active-roster table that backs placeholder rows
in the Trackman-derived lmu_pitchers/lmu_hitters/lmu_catchers rosters. Uses
season label "1899/1900" throughout -- guaranteed to never be a real season,
so these tests can freely write/read against the live analytics DB without
colliding with real data."""
import pandas as pd

from app.data import lmu_roster as LR

SEASON = "1899/1900"


def test_ensure_table_idempotent():
    LR.ensure_table()
    LR.ensure_table()  # second call is a no-op, not an error


def test_position_group_mapping():
    assert LR._position_group("RHP") == "pitcher"
    assert LR._position_group("LHP") == "pitcher"
    assert LR._position_group("C") == "catcher"
    assert LR._position_group("1B") == "hitter"
    assert LR._position_group("SS") == "hitter"
    assert LR._position_group("") == "hitter"
    assert LR._position_group(None) == "hitter"


def test_upsert_then_load_roster_roundtrip():
    LR.ensure_table()
    n = LR.upsert_season_roster(SEASON, [
        {"first_name": "Test", "last_name": "Playerone", "class_year": "FR", "position": "RHP"},
        {"first_name": "Test", "last_name": "Playertwo", "class_year": "SR", "position": "C"},
    ])
    assert n == 2
    df = LR.load_roster(SEASON)
    names = set(zip(df["first_name"], df["last_name"]))
    assert ("Test", "Playerone") in names
    assert ("Test", "Playertwo") in names


def test_upsert_is_idempotent_and_keeps_same_roster_id():
    LR.ensure_table()
    LR.upsert_season_roster(SEASON, [
        {"first_name": "Stable", "last_name": "Idcheck", "class_year": "FR", "position": "OF"},
    ])
    before = LR.load_roster(SEASON)
    rid_before = int(before.loc[before["last_name"] == "Idcheck", "roster_id"].iloc[0])

    # Re-run with an edited class_year/position -- must update in place, not
    # insert a second row or change roster_id (placeholder ids elsewhere in
    # the app are -roster_id and must never shift under a re-seed).
    LR.upsert_season_roster(SEASON, [
        {"first_name": "Stable", "last_name": "Idcheck", "class_year": "SO", "position": "SS"},
    ])
    after = LR.load_roster(SEASON)
    matches = after[after["last_name"] == "Idcheck"]
    assert len(matches) == 1
    assert int(matches.iloc[0]["roster_id"]) == rid_before
    assert matches.iloc[0]["class_year"] == "SO"
    assert matches.iloc[0]["position"] == "SS"


def test_load_roster_empty_season_returns_empty_frame():
    df = LR.load_roster("1800/1801")  # never seeded
    assert df.empty
    assert list(df.columns) == ["roster_id", "first_name", "last_name", "class_year", "position"]


def test_placeholder_rows_shape_and_negative_ids(monkeypatch):
    monkeypatch.setattr(LR, "load_roster", lambda season: pd.DataFrame([
        {"roster_id": 501, "first_name": "Test", "last_name": "Rhp", "class_year": "FR", "position": "RHP"},
        {"roster_id": 502, "first_name": "Test", "last_name": "Inf", "class_year": "SO", "position": "SS"},
    ]))
    df = LR.placeholder_rows(SEASON, ("pitcher",), "PitcherId", "Pitcher")
    assert list(df.columns) == ["PitcherId", "Pitcher"]
    assert len(df) == 1
    assert df.iloc[0]["PitcherId"] == -501
    assert df.iloc[0]["Pitcher"] == "Rhp, Test"


def test_placeholder_rows_empty_when_no_roster(monkeypatch):
    monkeypatch.setattr(LR, "load_roster", lambda season: pd.DataFrame(
        columns=["roster_id", "first_name", "last_name", "class_year", "position"]))
    df = LR.placeholder_rows(SEASON, ("pitcher",), "PitcherId", "Pitcher")
    assert df.empty


def test_union_with_roster_adds_unmatched_and_dedupes_matched(monkeypatch):
    monkeypatch.setattr(LR, "load_roster", lambda season: pd.DataFrame([
        {"roster_id": 1, "first_name": "adam", "last_name": "BEHRENS",  # same player as real row, different case
         "class_year": "SR", "position": "RHP"},
        {"roster_id": 2, "first_name": "New", "last_name": "Guy", "class_year": "FR", "position": "RHP"},
    ]))
    real = pd.DataFrame({"PitcherId": [123], "Pitcher": ["Behrens, Adam"]})
    out = LR.union_with_roster(real, SEASON, ("pitcher",), "PitcherId", "Pitcher")
    assert list(out["PitcherId"]).count(123) == 1        # real row not duplicated
    assert (out["PitcherId"] == -2).any()                 # non-matching roster row added
    assert not (out["PitcherId"] == -1).any()              # matching roster row suppressed
    assert len(out) == 2


def test_union_with_roster_returns_df_unchanged_when_no_placeholders(monkeypatch):
    monkeypatch.setattr(LR, "load_roster", lambda season: pd.DataFrame(
        columns=["roster_id", "first_name", "last_name", "class_year", "position"]))
    real = pd.DataFrame({"PitcherId": [123], "Pitcher": ["Behrens, Adam"]})
    out = LR.union_with_roster(real, SEASON, ("pitcher",), "PitcherId", "Pitcher")
    assert out is real


def test_reconcile_ids_migrates_matched_pitcher_and_is_idempotent(monkeypatch):
    from app.data import cauldron, velo_board
    cauldron.ensure_tables()
    velo_board.ensure_tables()

    monkeypatch.setattr(LR, "load_roster", lambda season: pd.DataFrame([
        {"roster_id": 9301, "first_name": "Recon", "last_name": "Cilable",
         "class_year": "FR", "position": "RHP"},
        {"roster_id": 9302, "first_name": "Still", "last_name": "Unmatched",
         "class_year": "SO", "position": "RHP"},
    ]))
    monkeypatch.setattr(LR.pitching_caps, "lmu_pitchers", lambda season: pd.DataFrame(
        {"PitcherId": [777001], "Pitcher": ["Cilable, Recon"]}))

    placeholder_id = -9301
    try:
        cauldron.set_team(placeholder_id, "TEST-RECON-c1", "Team 1")
        velo_board.set_override(placeholder_id, SEASON, season_max=95.0)

        migrated = LR.reconcile_ids(SEASON)
        assert migrated == 2  # one cauldron_teams row + one velo_board_overrides row

        teams = cauldron.read_teams("TEST-RECON-c1")
        ids = set(teams["player_id"].astype(int))
        assert 777001 in ids
        assert placeholder_id not in ids

        overrides = velo_board.read_overrides(SEASON)
        ov_ids = set(overrides["pitcher_id"].astype(int))
        assert 777001 in ov_ids
        assert placeholder_id not in ov_ids

        again = LR.reconcile_ids(SEASON)
        assert again == 0  # idempotent -- nothing left under the placeholder id
    finally:
        from app.db import get_engine
        from sqlalchemy import text
        with get_engine().begin() as c:
            c.execute(text("DELETE FROM cauldron_teams WHERE cycle_id='TEST-RECON-c1' "
                            "AND player_id IN (:p1, :p2)"), {"p1": placeholder_id, "p2": 777001})
            c.execute(text("DELETE FROM velo_board_overrides WHERE season_label=:s "
                            "AND pitcher_id IN (:p1, :p2)"),
                      {"s": SEASON, "p1": placeholder_id, "p2": 777001})


def test_reconcile_ids_survives_a_collision_and_still_migrates_other_pitchers(monkeypatch):
    """A row can already exist under a pitcher's real id for a table's other
    key dimensions (e.g. a coach re-assigned the real id's Cauldron team
    before flask roster-reconcile next ran) -- the raw UPDATE would then hit a
    duplicate-key violation. reconcile_ids must isolate that one collision
    (per table, per pitcher) with a SAVEPOINT, drop the now-stale placeholder
    row instead of raising, and keep migrating every other pitcher in the same
    call -- one collision must never abort the whole run."""
    from app.data import cauldron
    cauldron.ensure_tables()

    monkeypatch.setattr(LR, "load_roster", lambda season: pd.DataFrame([
        {"roster_id": 9401, "first_name": "Colliding", "last_name": "Pitcher",
         "class_year": "FR", "position": "RHP"},
        {"roster_id": 9402, "first_name": "Clean", "last_name": "Migrator",
         "class_year": "SO", "position": "RHP"},
    ]))
    monkeypatch.setattr(LR.pitching_caps, "lmu_pitchers", lambda season: pd.DataFrame(
        {"PitcherId": [777011, 777012],
         "Pitcher": ["Pitcher, Colliding", "Migrator, Clean"]}))

    placeholder_collide = -9401
    placeholder_clean = -9402
    cycle = "TEST-RECON-c2"

    try:
        # Colliding pitcher: a row already exists under the REAL id (more current
        # state -- it should win), plus a stale placeholder row that must be
        # dropped rather than migrated on top of it.
        cauldron.set_team(777011, cycle, "Team 2")
        cauldron.set_team(placeholder_collide, cycle, "Team 1")
        # Non-colliding pitcher: only a placeholder row exists -- must still
        # migrate cleanly even though it's processed in the same call as the
        # collision above.
        cauldron.set_team(placeholder_clean, cycle, "Team 3")

        migrated = LR.reconcile_ids(SEASON)  # must not raise
        assert migrated == 1  # only the clean pitcher's cauldron_teams row counts

        teams = cauldron.read_teams(cycle)
        by_id = {int(pid): team for pid, team in zip(teams["player_id"], teams["team"])}

        # Real-id row for the colliding pitcher is untouched; its placeholder is gone.
        assert by_id.get(777011) == "Team 2"
        assert placeholder_collide not in by_id

        # Non-colliding pitcher migrated to its real id.
        assert by_id.get(777012) == "Team 3"
        assert placeholder_clean not in by_id
    finally:
        from app.db import get_engine
        from sqlalchemy import text
        with get_engine().begin() as c:
            c.execute(text("DELETE FROM cauldron_teams WHERE cycle_id=:cy "
                            "AND player_id IN (:p1, :p2, :p3, :p4)"),
                      {"cy": cycle, "p1": placeholder_collide, "p2": placeholder_clean,
                       "p3": 777011, "p4": 777012})


def test_reconcile_ids_does_not_self_migrate_its_own_unioned_placeholder(monkeypatch):
    """`real = pitching_caps.lmu_pitchers(season_label)` is an UNSCOPED call
    (no start/end), so per lmu_pitchers's own union logic it includes
    placeholder rows too -- simulate that here by having the monkeypatched
    lmu_pitchers return ONLY the placeholder's own negative id under its own
    name (exactly what an unscoped/unioned call would incorrectly hand back
    pre-fix). Without the `real["PitcherId"] > 0` filter, this pitcher would
    match itself in real_by_name and reconcile_ids would attempt a
    self-referential no-op UPDATE ... SET col = -13 WHERE col = -13 -- fixed
    by never even reaching the UPDATE for this pitcher (real_by_name has no
    entry for it once positive-only filtering is applied)."""
    from app.data import cauldron
    cauldron.ensure_tables()

    monkeypatch.setattr(LR, "load_roster", lambda season: pd.DataFrame([
        {"roster_id": 9501, "first_name": "Selfmatch", "last_name": "Placeholder",
         "class_year": "FR", "position": "RHP"},
    ]))
    # Simulate an unscoped lmu_pitchers call returning only this placeholder's
    # own negative id under its own name (as the union would, pre-fix).
    monkeypatch.setattr(LR.pitching_caps, "lmu_pitchers", lambda season: pd.DataFrame(
        {"PitcherId": [-9501], "Pitcher": ["Placeholder, Selfmatch"]}))

    placeholder_id = -9501
    cycle = "TEST-RECON-c3"
    try:
        cauldron.set_team(placeholder_id, cycle, "Team 1")

        migrated = LR.reconcile_ids(SEASON)
        assert migrated == 0  # never reached the UPDATE for this pitcher

        teams = cauldron.read_teams(cycle)
        ids = set(teams["player_id"].astype(int))
        assert placeholder_id in ids  # untouched -- no self-referential update ran
    finally:
        from app.db import get_engine
        from sqlalchemy import text
        with get_engine().begin() as c:
            c.execute(text("DELETE FROM cauldron_teams WHERE cycle_id=:cy AND player_id=:p"),
                      {"cy": cycle, "p": placeholder_id})
