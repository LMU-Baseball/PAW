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


# --------------------------- identity + roster -----------------------------
#
# GAMES.Catcher is verified live as "Last, First" (e.g. "Lyall, Jake"), the
# SAME format catching.catcher_name already builds from tm_player -- unlike
# the pitching slice, no First/Last reordering is needed here.

def test_catcher_name_matches_oracle_format():
    old = catching.catcher_name(SURROGATE_CID)
    new = catching_caps.catcher_name(RAW_CID)
    assert new == old == "Lyall, Jake"


def test_catcher_name_unknown_id_falls_back_to_str():
    old = catching.catcher_name(999999999)
    new = catching_caps.catcher_name(999999999)
    assert new == old == "999999999"


def test_catcher_tm_id_for_is_identity():
    assert catching_caps.catcher_tm_id_for(RAW_CID) == RAW_CID


def test_catcher_profile_matches_oracle():
    old = catching.catcher_profile(SURROGATE_CID)
    new = catching_caps.catcher_profile(RAW_CID)
    assert new["name"] == old["name"] == "Lyall, Jake"
    assert new["position"] == old["position"] == "C"
    assert new["class_year"] == old["class_year"] == ""
    assert new["throws"] == old["throws"] == ""
    assert new["jersey"] == old["jersey"]
    assert new["photo"] == old["photo"]


def test_catcher_profile_unknown_id():
    old = catching.catcher_profile(999999999)
    new = catching_caps.catcher_profile(999999999)
    assert new == old


def test_lmu_catchers_matches_oracle():
    # Superset + window-bound, mirroring pitching_caps.lmu_pitchers's parity
    # test: GAMES holds full CAPS history back to 2022 while the warehouse
    # oracle (fact_tm_game_pitch) only covers the current synced season, so
    # an unscoped caps query would leak retired alumni. lmu_catchers windows
    # to the trailing ~12 months (anchored to the newest GAMES date), reusing
    # pitching_caps's shared window clause (same GAMES table/PitcherTeam col).
    from app.db import query_df
    old = catching.wh_lmu_catchers()
    new = catching_caps.lmu_catchers()

    # 1. SUPERSET: every current-season warehouse catcher is present by name.
    assert set(old["Catcher"]) <= set(new["Catcher"])

    # 2. WINDOW BOUND: scoping is doing real work.
    all_time = query_df(
        "SELECT COUNT(DISTINCT Catcher) n FROM GAMES "
        "WHERE PitcherTeam = :t AND CatcherId IS NOT NULL",
        {"t": catching_caps.LMU_PITCHER_TEAM},
    ).iloc[0]["n"]
    assert len(new) < all_time

    # 3. canonical-id sibling check, mirroring pitching_caps's.
    new_by_name = dict(zip(new["Catcher"], new["CatcherId"]))
    for _, row in old.iterrows():
        raw = catching.catcher_tm_id_for(int(row["CatcherId"]))
        siblings = catching_caps._sibling_catcher_ids(new_by_name[row["Catcher"]])
        assert raw in siblings


def test_lmu_catchers_columns():
    df = catching_caps.lmu_catchers()
    assert list(df.columns) == ["CatcherId", "Catcher"]


def test_games_for_catcher_unbounded_matches_labels():
    old = (catching.games_for_catcher(SURROGATE_CID)[["game_id", "GameLabel"]]
           .sort_values("game_id").reset_index(drop=True))
    new = (catching_caps.games_for_catcher(RAW_CID)[["game_id", "GameLabel"]]
           .sort_values("game_id").reset_index(drop=True))
    old["game_id"] = old["game_id"].astype(int)
    new["game_id"] = new["game_id"].astype(int)
    pd.testing.assert_frame_equal(new, old, check_dtype=False)


def test_games_for_catcher_date_range_filters():
    games = catching.games_for_catcher(SURROGATE_CID)
    start, end = games["game_date"].min(), games["game_date"].max()
    old = catching.games_for_catcher(SURROGATE_CID, start, end)[["game_id", "GameLabel"]].copy()
    new = catching_caps.games_for_catcher(RAW_CID, start, end)[["game_id", "GameLabel"]].copy()
    old["game_id"] = old["game_id"].astype(int)
    new["game_id"] = new["game_id"].astype(int)
    old = old.sort_values("game_id").reset_index(drop=True)
    new = new.sort_values("game_id").reset_index(drop=True)
    pd.testing.assert_frame_equal(new, old, check_dtype=False)


# ----------------------------- season tiles ---------------------------------
#
# framing_season_tiles has no game_id-driven date bound, so GAMES's pre-CAPS-
# migration composite-string-GameID rows (see games_for_catcher's docstring)
# would otherwise inflate whole-career totals beyond the warehouse oracle's
# synced-season scope. Restricting to numeric GameIDs (same clause
# games_for_catcher uses) reproduces the oracle's totals exactly for this
# fixture (verified live: games=32/pitches=4838/net_strikes=23/steal_pct=2.8%
# either way) -- real equality, not documented divergence.

def test_framing_season_tiles_matches_oracle():
    old = catching.framing_season_tiles(SURROGATE_CID)
    new = catching_caps.framing_season_tiles(RAW_CID)
    assert new == old == {"games": "32", "pitches": "4838",
                           "net_strikes": "23", "steal_pct": "2.8%"}


def test_framing_season_tiles_zero_for_unknown_catcher():
    old = catching.framing_season_tiles(999999999)
    new = catching_caps.framing_season_tiles(999999999)
    assert new == old == {"games": "0", "pitches": "0",
                           "net_strikes": "0", "steal_pct": "—"}


# ------------------------- ghost-player regression ---------------------------
#
# lmu_catchers scoped its list with a date-only _RECENT_WINDOW_CLAUSE but,
# before this fix, no numeric-GameID guard -- so a catcher whose only
# in-window GAMES rows carry legacy composite-string GameIDs (pre-CAPS-
# migration) would be LISTED here while every numeric-GameID-guarded data
# function (games_for_catcher, framing_season_tiles) returned empty for them:
# a coach picking that name from the dropdown got a blank dashboard.

def test_lmu_catchers_excludes_ghost_with_only_legacy_games():
    # CatcherId 801901 ("Ayers, Robbie") has 13,398 in-window GAMES rows (max
    # Date 2025-05-16, just inside the ~12-month window), ALL under legacy
    # composite GameIDs, and zero numeric-GameID rows -- verified live.
    GHOST_ID = 801901
    ids = catching_caps.lmu_catchers()["CatcherId"].values
    assert GHOST_ID not in ids
    # Confirm he really WAS a ghost (the data function is empty for him), not
    # merely absent from the roster for some unrelated reason.
    assert catching_caps.games_for_catcher(GHOST_ID).empty


def test_lmu_catchers_all_have_numeric_game_id_rows():
    # No-ghost property, as a single SQL set-membership check rather than N
    # per-id queries: every id lmu_catchers lists must have at least one
    # numeric-GameID GAMES row -- the exact universe games_for_catcher/
    # framing_season_tiles can actually serve.
    from app.db import query_df
    ids = set(catching_caps.lmu_catchers()["CatcherId"].astype(int))
    current_ids = set(query_df(
        "SELECT DISTINCT CatcherId FROM GAMES "
        "WHERE PitcherTeam = :t AND CatcherId IS NOT NULL "
        f"AND {catching_caps._NUMERIC_GAME_ID_CLAUSE}",
        {"t": catching_caps.LMU_PITCHER_TEAM},
    )["CatcherId"].astype(int))
    assert ids <= current_ids
