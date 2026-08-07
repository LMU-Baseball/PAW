"""Tests for roster media loading/matching (pure + file-backed; no network)."""
import json

import pytest

from app.data import roster_media as rm


# --------------------------- name normalization ---------------------------

def test_norm_name_matches_warehouse_and_roster_forms():
    # "Last, First" (warehouse) and "First Last [suffix]" (roster) collapse equal.
    assert rm._norm_name("Carmona, Jose") == rm._norm_name("Jose Carmona Jr.")
    assert rm._norm_name("Wadas, Zach") == rm._norm_name("Zach Wadas")
    assert rm._norm_name("Ghiorso, DJ") == rm._norm_name("DJ Ghiorso")


def test_norm_name_distinguishes_different_people():
    assert rm._norm_name("Malone, Noah") != rm._norm_name("Mhoon, Andrew")


def test_norm_name_blank():
    assert rm._norm_name("") == ""


def test_name_parts_last_first_initial():
    # nickname fallback key = (last, first-initial); nicknames share it.
    assert rm._name_parts("Champion, Matthew") == ("matthew", "champion")
    assert rm._name_parts("Matt Champion")[1] == "champion"
    assert rm._name_parts("Champion, Matthew")[0][:1] == rm._name_parts("Matt Champion")[0][:1]
    assert rm._name_parts("Klosek, Richard")[1] == rm._name_parts("Richie Klosek")[1]


# --------------------------- file-backed loader ---------------------------

@pytest.fixture
def media_file(tmp_path, monkeypatch):
    data = {"806253": {"jersey": "34",
                       "photo_url": "https://x/Zach_Wadas.jpg?width=360",
                       "name": "Zach Wadas"}}
    path = tmp_path / "roster_media.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(rm, "media_path", lambda: str(path))
    monkeypatch.setattr(rm, "_cache", None)  # bypass any cached load
    return path


def test_player_media_returns_entry(media_file):
    m = rm.player_media(806253)
    assert m == {"jersey": "34", "photo_url": "https://x/Zach_Wadas.jpg?width=360"}


def test_player_media_unknown_id_is_blank(media_file):
    assert rm.player_media(999999) == {"jersey": "", "photo_url": ""}


def test_load_roster_media_missing_file_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(rm, "media_path", lambda: str(tmp_path / "nope.json"))
    monkeypatch.setattr(rm, "_cache", None)
    assert rm.load_roster_media(force=True) == {}


# --------------------------- profile merge --------------------------------

def test_player_profile_merges_media(monkeypatch):
    # hitting_caps.player_profile pulls name/bats from GAMES (query_df), class
    # year/position from hitting._roster_lookup, and photo/jersey from
    # roster_media.player_media, then merges all three into one profile dict.
    # player_profile binds these three names into the hitting_caps namespace at
    # import time (`from ... import`), so they must be patched there to take
    # effect.
    from app.data import hitting_caps
    import pandas as pd
    monkeypatch.setattr("app.data.hitting_caps.query_df",
                        lambda *a, **k: pd.DataFrame(
                            [{"Batter": "Wadas, Zach", "BatterSide": "Left"}]))
    monkeypatch.setattr("app.data.hitting_caps._roster_lookup",
                        lambda n: ("Junior", "OF/1B"))
    monkeypatch.setattr("app.data.hitting_caps.player_media",
                        lambda b: {"jersey": "34", "photo_url": "https://x/w.jpg"})
    prof = hitting_caps.player_profile(806253)
    # all three sources merged into one profile dict
    assert prof["name"] == "Wadas, Zach"
    assert prof["bats"] == "Left"
    assert prof["class_year"] == "Junior"
    assert prof["position"] == "OF/1B"
    assert prof["photo"] == "https://x/w.jpg"
    assert prof["jersey"] == "34"


# --------------------------- roster scrape: players + collisions ----------

def test_lmu_players_includes_pitchers():
    from scripts import scrape_roster_media as s
    players = s.lmu_players()
    assert players and len(players[0]) == 3  # (id, name, n_pitches)
    names = {n for _, n, _ in players}
    # A known LMU pitcher name is present in the union (not hitters-only).
    assert any("Bender" in n for n in names)


def test_build_media_prefers_dominant_identity():
    from scripts import scrape_roster_media as s
    cards = [
        {"name": "Zach Bender", "jersey": "42", "photo_url": "bender.jpg"},
        {"name": "Noah Malone", "jersey": "4", "photo_url": "malone.jpg"},
    ]
    # Same raw id 832473 claimed by a 1-pitch Malone stray AND the full Bender pitcher.
    players = [(832473, "Malone, Noah", 1), (832473, "Bender, Zachary", 500),
               (832474, "Malone, Noah", 300)]
    media, _, _ = s.build_media(players, cards)
    assert media["832473"]["name"] == "Zach Bender"   # dominant identity won
    assert media["832473"]["jersey"] == "42"
    assert media["832474"]["name"] == "Noah Malone"


def test_build_media_unmatched_dominant_does_not_inherit_stray_face():
    # An id whose DOMINANT identity has no roster card must stay unmatched, even
    # when a lighter colliding identity on the same id does match a card.
    from scripts import scrape_roster_media as s
    cards = [{"name": "Noah Malone", "jersey": "4", "photo_url": "malone.jpg"}]
    players = [(900001, "Malone, Noah", 1),          # light, matches a card
               (900001, "Nomatch, Ghost", 500)]      # dominant, no card
    media, _, _ = s.build_media(players, cards)
    assert "900001" not in media  # did NOT inherit Malone's face


def test_player_media_by_name(monkeypatch):
    from app.data import roster_media
    monkeypatch.setattr(roster_media, "load_roster_media", lambda: {
        "813709": {"jersey": "27", "photo_url": "u.jpg", "name": "Tanner Warady"},
    })
    got = roster_media.player_media_by_name("Tanner Warady")
    assert got["jersey"] == "27" and got["photo_url"] == "u.jpg"
    # unmatched -> blanks
    assert roster_media.player_media_by_name("Nobody Here") == {"jersey": "", "photo_url": ""}
    assert roster_media.player_media_by_name("") == {"jersey": "", "photo_url": ""}
