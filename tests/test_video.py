# tests/test_video.py
"""Live-DB tests for the pitch-video data helper."""
import pandas as pd
import pytest

from app.data import video
from app.db import query_df


@pytest.fixture(scope="module")
def sample():
    """A (game_id, pitcher_tm_id, batter_id, catcher_id) that has video.

    pitcher_tm_id is the RAW trackman id (== GAMES.PitcherId, what the
    pitching dashboard/report pass post-cutover) -- NOT the warehouse
    surrogate f.pitcher_id, which video._sibling_ids no longer accepts for
    the pitcher subject (see test_sibling_ids_pitcher_uses_raw_column_and_
    pitching_caps below).
    """
    row = query_df(
        """
        SELECT f.game_id, f.pitcher_tm_id, f.batter_tm_id, f.catcher_id
          FROM vw_pitch_video v
          JOIN fact_tm_game_pitch f ON f.pitch_uid = v.pitch_uid
         WHERE f.catcher_id IS NOT NULL AND f.batter_tm_id IS NOT NULL
           AND f.pitcher_tm_id IS NOT NULL
         LIMIT 1
        """
    ).iloc[0]
    return dict(game_id=int(row["game_id"]), pitcher_tm_id=int(row["pitcher_tm_id"]),
                batter_tm_id=int(row["batter_tm_id"]), catcher_id=int(row["catcher_id"]))


def test_constants_shape():
    assert [a for a, _ in video.ANGLES] == ["HomeBehind", "HomeRight", "HomeLeft", "Broadcast"]
    assert video.URL_COL["HomeBehind"] == "url_homebehind"
    assert video.DISPLAY_COLS[0] == "Pitch"


def test_pitcher_filter_one_row_per_pitch(sample):
    df = video.pitch_video_df(sample["game_id"], pitcher_id=sample["pitcher_tm_id"])
    assert not df.empty
    # one row per pitch (pivoted), not one per (pitch, angle)
    assert df["pitch_uid"].is_unique
    for col in video.DISPLAY_COLS:
        assert col in df.columns
    for a in video.URL_COL.values():
        assert a in df.columns
    # at least one angle url present somewhere
    assert df[list(video.URL_COL.values())].notna().any().any()


def test_batter_and_catcher_filters(sample):
    b = video.pitch_video_df(sample["game_id"], batter_id=sample["batter_tm_id"])
    c = video.pitch_video_df(sample["game_id"], catcher_id=sample["catcher_id"])
    assert not b.empty and b["pitch_uid"].is_unique
    assert not c.empty and c["pitch_uid"].is_unique


def test_game_id_list_unions(sample):
    one = video.pitch_video_df(sample["game_id"], catcher_id=sample["catcher_id"])
    many = video.pitch_video_df([sample["game_id"]], catcher_id=sample["catcher_id"])
    assert len(one) == len(many)


def test_empty_game_returns_full_columns(sample):
    df = video.pitch_video_df(-1, pitcher_id=sample["pitcher_tm_id"])
    assert df.empty
    assert list(df.columns)  # full column set present
    assert "Pitch" in df.columns and "url_homebehind" in df.columns


def test_missing_angle_urls_are_none_not_nan(sample):
    df = video.pitch_video_df(sample["game_id"], pitcher_id=sample["pitcher_tm_id"])
    import math
    for col in video.URL_COL.values():
        for v in df[col]:
            # every cell is either a real string url or exactly None (never NaN)
            assert v is None or isinstance(v, str)
            assert not (isinstance(v, float) and math.isnan(v))


def test_requires_exactly_one_subject(sample):
    with pytest.raises(ValueError):
        video.pitch_video_df(sample["game_id"])
    with pytest.raises(ValueError):
        video.pitch_video_df(sample["game_id"], pitcher_id=1, batter_id=2)


def test_empty_game_list_returns_empty(sample):
    df = video.pitch_video_df([], pitcher_id=sample["pitcher_tm_id"])
    assert df.empty
    assert "Pitch" in df.columns and "url_homebehind" in df.columns


def test_sibling_ids_pitcher_uses_raw_column_and_pitching_caps(sample):
    """Regression: the pitcher subject must resolve siblings via pitching_caps
    (raw GAMES.PitcherId space) and filter fact_tm_game_pitch.pitcher_tm_id --
    not the warehouse surrogate pitcher_id column, which a raw trackman id
    (what the post-cutover pitching dashboard/report now pass) would never
    match. That mismatch silently blanked the Outing Video tab + the game
    dropdown's "has video" badge for every pitcher."""
    col, sib = video._sibling_ids(batter_id=None, pitcher_id=sample["pitcher_tm_id"],
                                  catcher_id=None)
    assert col == "pitcher_tm_id"
    assert sample["pitcher_tm_id"] in sib


def test_pitcher_video_returns_data_for_raw_trackman_id(sample):
    """End-to-end regression for the id-space flip: a RAW pitcher id (what the
    pitching dashboard/report now pass post-cutover) must still find video."""
    df = video.pitch_video_df(sample["game_id"], pitcher_id=sample["pitcher_tm_id"])
    assert not df.empty
    assert sample["game_id"] in video.games_with_video(
        [sample["game_id"]], pitcher_id=sample["pitcher_tm_id"])
