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

def test_wh_player_profile_merges_media(monkeypatch):
    from app.data import hitting_wh
    import pandas as pd
    monkeypatch.setattr("app.data.hitting_wh.query_df",
                        lambda *a, **k: pd.DataFrame(
                            [{"batter_name": "Wadas, Zach", "batter_side": "Left"}]))
    monkeypatch.setattr("app.data.hitting_wh._roster_lookup", lambda n: ("Junior", "OF/1B"))
    monkeypatch.setattr("app.data.hitting_wh.player_media",
                        lambda b: {"jersey": "34", "photo_url": "https://x/w.jpg"})
    prof = hitting_wh.wh_player_profile(806253)
    assert prof["photo"] == "https://x/w.jpg"
    assert prof["jersey"] == "34"
    assert prof["name"] == "Wadas, Zach"
