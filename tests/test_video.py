# tests/test_video.py
"""Live-DB tests for the pitch-video data helper."""
import pandas as pd
import pytest

from app.data import video
from app.db import query_df


@pytest.fixture(scope="module")
def sample():
    """A (game_id, pitcher_tm_id, batter_tm_id, catcher_tm_id) that has video.

    Sourced from CAPS (video_clips joined to GAMES on PitchUID). The three ids
    are RAW trackman ids (== GAMES.PitcherId/BatterId/CatcherId, what the
    dashboards+report pass post-cutover); the `_tm_id` dict keys are kept only
    to avoid churning every consuming test. Deliberately warehouse-free -- the
    only remaining tm_* dependency in this file is the Phase-3 parity oracle in
    test_parity_caps_matches_warehouse_oracle.
    """
    row = query_df(
        """
        SELECT g.GameID AS game_id, g.PitcherId AS pitcher_tm_id,
               g.BatterId AS batter_tm_id, g.CatcherId AS catcher_tm_id
          FROM video_clips v
          JOIN GAMES g ON g.PitchUID = v.pitch_uid
         WHERE g.CatcherId IS NOT NULL AND g.BatterId IS NOT NULL
           AND g.PitcherId IS NOT NULL
         LIMIT 1
        """
    ).iloc[0]
    return dict(game_id=int(row["game_id"]), pitcher_tm_id=int(row["pitcher_tm_id"]),
                batter_tm_id=int(row["batter_tm_id"]), catcher_tm_id=int(row["catcher_tm_id"]))


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
    c = video.pitch_video_df(sample["game_id"], catcher_id=sample["catcher_tm_id"])
    assert not b.empty and b["pitch_uid"].is_unique
    assert not c.empty and c["pitch_uid"].is_unique


def test_game_id_list_unions(sample):
    one = video.pitch_video_df(sample["game_id"], catcher_id=sample["catcher_tm_id"])
    many = video.pitch_video_df([sample["game_id"]], catcher_id=sample["catcher_tm_id"])
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
    assert col == "PitcherId"
    assert sample["pitcher_tm_id"] in sib


def test_pitcher_video_returns_data_for_raw_trackman_id(sample):
    """End-to-end regression for the id-space flip: a RAW pitcher id (what the
    pitching dashboard/report now pass post-cutover) must still find video."""
    df = video.pitch_video_df(sample["game_id"], pitcher_id=sample["pitcher_tm_id"])
    assert not df.empty
    assert sample["game_id"] in video.games_with_video(
        [sample["game_id"]], pitcher_id=sample["pitcher_tm_id"])


def test_sibling_ids_catcher_uses_raw_column_and_catching_caps(sample):
    """Regression: the catcher subject must resolve siblings via catching_caps
    (raw GAMES.CatcherId space) and filter fact_tm_game_pitch.catcher_tm_id --
    not the warehouse surrogate catcher_id column, which a raw trackman id
    (what the post-cutover catching dashboard now passes) would never match.
    That mismatch would silently blank the Outing Video tab + the game
    dropdown's "has video" badge for every catcher."""
    col, sib = video._sibling_ids(batter_id=None, pitcher_id=None,
                                  catcher_id=sample["catcher_tm_id"])
    assert col == "CatcherId"
    assert sample["catcher_tm_id"] in sib


def test_catcher_video_returns_data_for_raw_trackman_id(sample):
    """End-to-end regression for the id-space flip: a RAW catcher id (what the
    catching dashboard now passes post-cutover) must still find video."""
    df = video.pitch_video_df(sample["game_id"], catcher_id=sample["catcher_tm_id"])
    assert not df.empty
    assert sample["game_id"] in video.games_with_video(
        [sample["game_id"]], catcher_id=sample["catcher_tm_id"])


def test_video_source_is_caps_only():
    """After the CAPS cutover, video.py must not reference any warehouse
    object. This is the Phase-3 unblocker: video is the last module off tm_*."""
    import inspect
    from app.data import video as _v
    src = inspect.getsource(_v)
    for forbidden in ("vw_pitch_video", "fact_tm_game_pitch", "hitting_wh"):
        assert forbidden not in src, f"video.py still references {forbidden}"


def test_parity_caps_matches_warehouse_oracle(sample):
    """CAPS output == the old warehouse path, per pitch AND value-for-value.

    The migration swapped the VALUE source (GAMES vs the fact/view), so this
    checks the displayed metadata per pitch_uid -- not merely which pitches came
    back. The oracle reproduces the pre-migration query faithfully: it unions
    the SAME sibling id list pitch_video_df uses (via video._sibling_ids), so
    the two are truly comparable and the sibling-union path is exercised. This
    oracle is the LAST warehouse dependency in the video tests; it is deleted in
    Phase 3 together with tm_*/vw_pitch_video.
    """
    fact_col = {"BatterId": "batter_tm_id", "PitcherId": "pitcher_tm_id",
                "CatcherId": "catcher_tm_id"}
    for subj_col, subj_kw, subj_val in [
        ("BatterId", "batter_id", sample["batter_tm_id"]),
        ("PitcherId", "pitcher_id", sample["pitcher_tm_id"]),
        ("CatcherId", "catcher_id", sample["catcher_tm_id"]),
    ]:
        col, sib = video._sibling_ids(
            batter_id=subj_val if subj_kw == "batter_id" else None,
            pitcher_id=subj_val if subj_kw == "pitcher_id" else None,
            catcher_id=subj_val if subj_kw == "catcher_id" else None)
        assert col == subj_col
        sph = ", ".join(f":s{i}" for i in range(len(sib)))
        params = {f"s{i}": s for i, s in enumerate(sib)}
        params["g"] = sample["game_id"]
        oracle = query_df(
            f"""
            SELECT v.pitch_uid, v.pitch_no, v.inning, v.balls, v.strikes,
                   v.tagged_pitch_type, f.rel_speed, f.izt_zone
              FROM vw_pitch_video v
              JOIN fact_tm_game_pitch f ON f.pitch_uid = v.pitch_uid
             WHERE f.game_id = :g AND f.{fact_col[subj_col]} IN ({sph})
            """,
            params,
        ).drop_duplicates("pitch_uid").set_index("pitch_uid")
        new_df = video.pitch_video_df(
            sample["game_id"], **{subj_kw: subj_val}).set_index("pitch_uid")

        # Same pitches came back...
        assert set(new_df.index) == set(oracle.index)
        assert len(oracle.index)  # sanity: the sample actually has video
        # ...and the DISPLAYED values agree (GAMES value source == fact/view).
        for uid in oracle.index:
            o, n = oracle.loc[uid], new_df.loc[uid]
            assert int(n["Pitch"]) == int(o["pitch_no"])
            assert int(n["Inn"]) == int(o["inning"])
            assert n["Count"] == f"{int(o['balls'])}-{int(o['strikes'])}"
            nt, ot = n["Type"], o["tagged_pitch_type"]
            assert (pd.isna(nt) and pd.isna(ot)) or nt == ot
            z = o["izt_zone"]
            expected_zone = "—" if z is None or (isinstance(z, float) and pd.isna(z)) else str(z)
            assert n["Zone"] == expected_zone
            rs = o["rel_speed"]
            if pd.isna(rs):
                assert n["Velo"] == "—"
            else:
                assert n["Velo"] != "—" and abs(float(n["Velo"]) - float(rs)) < 0.06
