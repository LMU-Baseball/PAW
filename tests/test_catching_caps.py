import pandas as pd
import pytest

from app.data import catching, catching_caps, pitching_caps

# Lyall, Jake: warehouse surrogate catcher_id 34 -> raw trackman id 832465,
# game_id 68 (2026-03-24, LMU @ UCLA). Verified live: GAMES row count for
# (GameID=68, CatcherId=832465) equals the oracle's fact_tm_game_pitch row
# count for (game_id=68, catcher_id=34) -- 187 pitches each -- confirming the
# two id spaces line up for this fixture. This game also has 4 caught-stealing
# events, making the caught_stealing_summary parity check meaningful. GAMES
# additionally carries a sibling raw CatcherId (10305395) for "Lyall, Jake"
# under legacy composite-string GameIDs (pre-CAPS-migration scrimmages) --
# irrelevant to this single-game fixture but exercises the sibling-union
# machinery for whole-career queries in later tasks.
SURROGATE_CID = 34
RAW_CID = 832465
GAME_ID = 68


def _oracle_and_caps_game_df():
    old = catching.game_pitches_for(GAME_ID, SURROGATE_CID)
    new = catching_caps.game_pitches_for(GAME_ID, RAW_CID)
    return old, new


def test_fixture_ids_bridge_correctly():
    assert catching.catcher_tm_id_for(SURROGATE_CID) == RAW_CID
    games = catching.games_for_catcher(SURROGATE_CID)
    assert GAME_ID in set(games["game_id"].astype(int))


def test_game_pitches_for_same_row_count():
    old, new = _oracle_and_caps_game_df()
    assert len(old) == len(new) > 0


def test_sibling_catcher_ids_includes_raw_id():
    ids = catching_caps._sibling_catcher_ids(RAW_CID)
    assert RAW_CID in ids


def test_framing_table_matches_oracle():
    old, new = _oracle_and_caps_game_df()
    old_ft = catching.framing_table(catching.add_framing_cols(old))
    new_ft = catching.framing_table(catching.add_framing_cols(new))
    assert new_ft == old_ft


def test_call_type_value_counts_match_oracle():
    old, new = _oracle_and_caps_game_df()
    old_counts = catching.add_framing_cols(old)["CallType"].value_counts().sort_index()
    new_counts = catching.add_framing_cols(new)["CallType"].value_counts().sort_index()
    pd.testing.assert_series_equal(new_counts, old_counts, check_names=False)


def test_caught_stealing_summary_matches_oracle():
    old, new = _oracle_and_caps_game_df()
    old_summary = catching.caught_stealing_summary(old)
    new_summary = catching.caught_stealing_summary(new)
    assert new_summary == old_summary
    # Sanity: this fixture game actually has caught-stealing attempts, so the
    # assertion above is exercising real data, not two empty dicts.
    assert old_summary["attempts"] > 0


def test_apply_framing_filters_bat_side_right_matches_oracle():
    old, new = _oracle_and_caps_game_df()
    old_f = catching.apply_framing_filters(catching.add_framing_cols(old), bat_side="Right")
    new_f = catching.apply_framing_filters(catching.add_framing_cols(new), bat_side="Right")
    old_ft = catching.framing_table(old_f)
    new_ft = catching.framing_table(new_f)
    assert new_ft == old_ft
    assert len(old_f) == len(new_f) > 0


def test_range_pitches_for_matches_oracle_row_count():
    games = catching.games_for_catcher(SURROGATE_CID)
    start, end = games["game_date"].min(), games["game_date"].max()
    old = catching.range_pitches_for(SURROGATE_CID, start, end)
    new = catching_caps.range_pitches_for(RAW_CID, start, end)
    assert len(old) == len(new) > 0


def test_game_pitches_season_nonempty_for_fixture():
    df = catching_caps.game_pitches_season(RAW_CID)
    assert not df.empty
    assert GAME_ID in set(df["game_id"].astype(int))


def test_game_context_delegates_to_pitching_caps():
    old = pitching_caps.game_context(GAME_ID)
    new = catching_caps.game_context(GAME_ID)
    assert new == old
