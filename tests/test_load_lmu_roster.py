"""scripts/load_lmu_roster.py: seeds lmu_roster from a committed JSON file."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data import lmu_roster as LR
from scripts.load_lmu_roster import main as load_main

SEASON = "1899/1900"


def _write_fixture(tmp_path, players):
    p = tmp_path / "roster.json"
    p.write_text(json.dumps(players), encoding="utf-8")
    return str(p)


def test_load_main_seeds_all_players(tmp_path):
    path = _write_fixture(tmp_path, [
        {"first_name": "Load", "last_name": "Testone", "class_year": "FR", "position": "RHP"},
        {"first_name": "Load", "last_name": "Testtwo", "class_year": "SR", "position": "C"},
    ])
    rc = load_main(path, SEASON)
    assert rc == 0
    df = LR.load_roster(SEASON)
    names = set(zip(df["first_name"], df["last_name"]))
    assert ("Load", "Testone") in names
    assert ("Load", "Testtwo") in names


def test_load_main_is_idempotent(tmp_path):
    path = _write_fixture(tmp_path, [
        {"first_name": "Idem", "last_name": "Potent", "class_year": "FR", "position": "OF"},
    ])
    load_main(path, SEASON)
    before = LR.load_roster(SEASON)
    rid = int(before.loc[before["last_name"] == "Potent", "roster_id"].iloc[0])
    load_main(path, SEASON)  # re-run unchanged -- must not duplicate or renumber
    after = LR.load_roster(SEASON)
    matches = after[after["last_name"] == "Potent"]
    assert len(matches) == 1
    assert int(matches.iloc[0]["roster_id"]) == rid


def test_real_2026_2027_fixture_loads_47_players():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(repo_root, "data", "rosters", "2026-2027.json")
    with open(path, encoding="utf-8") as fh:
        players = json.load(fh)
    assert len(players) == 47
    for p in players:
        assert p["first_name"] and p["last_name"] and p["position"]
