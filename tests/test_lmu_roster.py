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
