"""Tests for the warehouse hitting data layer (live DB, unguarded)."""
import numpy as np
import pandas as pd
import pytest

from app.data import hitting_wh as wh
from app.db import query_df


@pytest.fixture(scope="module")
def top_batter():
    df = query_df(
        """
        SELECT batter_tm_id FROM fact_tm_game_pitch
         WHERE batter_team='LOY_LIO' AND batter_tm_id IS NOT NULL
         GROUP BY batter_tm_id ORDER BY COUNT(*) DESC LIMIT 1
        """
    )
    return int(df.loc[0, "batter_tm_id"])


@pytest.fixture(scope="module")
def top_game(top_batter):
    df = query_df(
        """
        SELECT game_id FROM fact_tm_game_pitch WHERE batter_tm_id=:b
         GROUP BY game_id ORDER BY COUNT(*) DESC LIMIT 1
        """,
        {"b": top_batter},
    )
    return int(df.loc[0, "game_id"])


def test_attack_zone_boundaries():
    assert wh.attack_zone(0.0, 2.5) == "Heart"       # dead center
    assert wh.attack_zone(1.0, 2.5) == "Shadow"      # ~12in side
    assert wh.attack_zone(1.6, 2.5) == "Chase"       # ~19in side
    assert wh.attack_zone(3.0, 2.5) == "Waste"       # far outside


def test_wh_lmu_hitters(top_batter):
    df = wh.wh_lmu_hitters()
    assert list(df.columns) == ["Batter", "BatterId"]
    assert df["BatterId"].is_unique
    assert top_batter in set(df["BatterId"])


def test_wh_games_for_batter(top_batter):
    df = wh.wh_games_for_batter(top_batter)
    assert {"game_id", "game_date", "GameLabel"} <= set(df.columns)
    assert len(df) >= 1
    # newest first
    assert list(df["game_date"]) == sorted(df["game_date"], reverse=True)


def test_wh_game_pitches_has_aliased_and_computed_cols(top_game, top_batter):
    df = wh.wh_game_pitches(top_game, top_batter)
    assert len(df) > 0
    for c in ("PlateLocSide", "PitchCall", "PlayResult", "KorBB", "TaggedHitType",
              "TaggedPitchType", "ExitSpeed", "Inning", "PAofInning", "PitchofPA",
              "PitchNo", "Balls", "Strikes", "RunsScored", "BatterSide", "Pitcher",
              "GameID", "Zone", "QC", "PathQ", "Angle", "PitchCat"):
        assert c in df.columns
    assert set(df["Zone"]).issubset({"Heart", "Shadow", "Chase", "Waste", ""})
    assert df["QC"].isna().all()


def test_attack_zone_missing_coords_excluded():
    from app.data import hitting
    assert wh.attack_zone(None, 2.5) == ""
    assert wh.attack_zone(2.0, None) == ""
    assert wh.attack_zone(float("nan"), float("nan")) == ""
    assert "" not in hitting.ZONE_LEVELS


def test_wh_game_pitches_feeds_reused_transforms(top_game, top_batter):
    from app.data import hitting
    df = wh.wh_game_pitches(top_game, top_batter)
    line = hitting.game_batting_line(df)          # must not raise
    assert set(line) >= {"PA", "H", "SO", "BB", "QAB"}
    pd_zone = hitting.plate_discipline(df, by="zone")
    assert list(pd_zone["Zone"]) == ["Heart", "Shadow", "Chase", "Waste"]


def test_wh_player_profile_and_scoreboard(top_batter, top_game):
    prof = wh.wh_player_profile(top_batter)
    assert set(prof) == {"name", "bats", "class_year", "position", "photo", "jersey"}
    assert prof["name"]                # non-empty for a real batter
    # photo/jersey come from the scraped roster_media.json (may or may not have run);
    # either way they must be strings, not None.
    assert isinstance(prof["photo"], str) and isinstance(prof["jersey"], str)
    sb = wh.wh_scoreboard(top_game)
    assert set(sb) == {"date", "loc", "opp", "game_type"}
    assert sb["loc"] in ("vs", "@")


def test_wh_season_qab_rate(top_batter):
    r = wh.wh_season_qab_rate(top_batter)
    assert r is None or 0.0 <= r <= 1.0


def test_wh_lmu_hitters_names_deduped():
    # Players with two Trackman ids must appear only ONCE (merged by name).
    df = wh.wh_lmu_hitters()
    assert df["Batter"].is_unique


def test_wh_slash_line_shape_and_values(top_batter):
    sl = wh.wh_slash_line(top_batter)
    assert set(sl) == {"BA", "SLG", "OBP"}
    # a real hitter has a computable line; each is "—" or a numeric-looking string
    for k, v in sl.items():
        assert isinstance(v, str)
        if v != "—":
            float(v)  # parses as a number (e.g. ".326" or "1.021")
    # top batter has plate appearances -> BA should be computed, not "—"
    assert sl["BA"] != "—"


def test_wh_slash_line_no_data_is_dashes():
    assert wh.wh_slash_line(-1) == {"BA": "—", "SLG": "—", "OBP": "—"}


def test_hitting_games_date_filter_and_range():
    from app.data import hitting_wh as H
    hitters = H.wh_lmu_hitters()
    if hitters.empty:
        import pytest; pytest.skip("no hitters")
    bid = int(hitters.iloc[0]["BatterId"])
    allg = H.wh_games_for_batter(bid)
    if allg.empty:
        import pytest; pytest.skip("no games")
    lo, hi = str(allg["game_date"].min()), str(allg["game_date"].max())
    assert len(H.wh_games_for_batter(bid, start=lo, end=hi)) == len(allg)
    pooled = H.wh_range_pitches(bid, lo, hi)
    single = sum(len(H.wh_game_pitches(int(g), bid)) for g in allg["game_id"])
    assert len(pooled) == single
