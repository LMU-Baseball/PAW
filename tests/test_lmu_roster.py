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
