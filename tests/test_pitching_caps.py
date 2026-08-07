import pandas as pd
import pytest

from app.db import query_df
from app.data import pitching, pitching_caps

# Behrens, Adam: warehouse surrogate id 6 -> raw trackman id 823008, game_id 315
# (2026-05-15, LMU @ USD). Verified live: oracle's fact_tm_game_pitch pitch
# count for (game_id=315, pitcher_id=6) equals GAMES's row count for
# (GameID=315, PitcherId=823008) -- 106 pitches each -- confirming the two id
# spaces line up for this fixture.
SURROGATE_PID = 6
RAW_PID = 823008
GAME_ID = 315


def _oracle_and_caps_game_df():
    old = pitching.game_pitches_for(GAME_ID, SURROGATE_PID)
    new = pitching_caps.game_pitches_for(GAME_ID, RAW_PID)
    return old, new


def test_fixture_ids_bridge_correctly():
    # Sanity-check the bridge itself before trusting any downstream parity.
    assert pitching.pitcher_tm_id_for(SURROGATE_PID) == RAW_PID
    games = pitching.games_for_pitcher(SURROGATE_PID)
    assert GAME_ID in set(games["game_id"].astype(int))


def test_game_pitches_for_same_row_count():
    old, new = _oracle_and_caps_game_df()
    assert len(old) == len(new) > 0


def test_game_overall_line_matches_warehouse():
    old, new = _oracle_and_caps_game_df()
    assert pitching.game_overall_line(new) == pitching.game_overall_line(old)


def test_pitch_characteristics_matches_warehouse():
    old, new = _oracle_and_caps_game_df()
    pd.testing.assert_frame_equal(
        pitching.pitch_characteristics(new).reset_index(drop=True),
        pitching.pitch_characteristics(old).reset_index(drop=True),
        check_dtype=False,
    )


def test_pitch_usage_matches_warehouse():
    old, new = _oracle_and_caps_game_df()
    pd.testing.assert_frame_equal(
        pitching.pitch_usage(new).reset_index(drop=True),
        pitching.pitch_usage(old).reset_index(drop=True),
        check_dtype=False,
    )


def test_zone_location_matches_warehouse():
    # Proves the GAMES.Zone backfill from fact.izt_zone (Task 1): zone_location
    # reads df["izt_zone"], aliased here from GAMES.Zone.
    old, new = _oracle_and_caps_game_df()
    pd.testing.assert_frame_equal(
        pitching.zone_location(new).reset_index(drop=True),
        pitching.zone_location(old).reset_index(drop=True),
        check_dtype=False,
    )


def test_movement_summary_matches_warehouse():
    old, new = _oracle_and_caps_game_df()
    assert pitching.movement_summary(new) == pitching.movement_summary(old)


def test_header_stat_line_matches_warehouse():
    old, new = _oracle_and_caps_game_df()
    assert pitching.header_stat_line(new) == pitching.header_stat_line(old)


def test_process_and_outcome_metrics_match_warehouse():
    old, new = _oracle_and_caps_game_df()
    assert pitching.process_metrics(new) == pitching.process_metrics(old)
    assert pitching.outcome_metrics(new) == pitching.outcome_metrics(old)


def test_splits_by_batter_side_matches_warehouse():
    old, new = _oracle_and_caps_game_df()
    old_splits = pitching.splits_by_batter_side(old)
    new_splits = pitching.splits_by_batter_side(new)
    assert set(new_splits) == set(old_splits)
    for side in old_splits:
        assert new_splits[side]["overall"] == old_splits[side]["overall"]
        pd.testing.assert_frame_equal(
            new_splits[side]["usage"].reset_index(drop=True),
            old_splits[side]["usage"].reset_index(drop=True),
            check_dtype=False,
        )


def test_game_pitches_single_id_matches_row_count():
    # game_pitches (no sibling union) vs the oracle's single-surrogate-id read.
    old = pitching.game_pitches(GAME_ID, SURROGATE_PID)
    new = pitching_caps.game_pitches(GAME_ID, RAW_PID)
    assert len(old) == len(new) > 0
    assert pitching.game_overall_line(new) == pitching.game_overall_line(old)


def test_range_pitches_for_matches_warehouse_span():
    games = pitching.games_for_pitcher(SURROGATE_PID)
    start, end = games["game_date"].min(), games["game_date"].max()
    old = pitching.range_pitches_for(SURROGATE_PID, start, end)
    new = pitching_caps.range_pitches_for(RAW_PID, start, end)
    assert len(old) == len(new) > 0


def test_sibling_pitcher_ids_includes_raw_id():
    ids = pitching_caps._sibling_pitcher_ids(RAW_PID)
    assert RAW_PID in ids


def test_game_context_matches_warehouse_shape_and_score():
    old_gid = SURROGATE_PID  # unused; game_context keys off game_id, not pitcher
    old = pitching.game_context(229)  # a game_id present in BOTH id-spaces (see fixture probe)
    # NOTE: dim_tm_game.game_id and GAMES.GameID share the same numbering for
    # backfilled games (verified live across multiple pitchers/games), so 229
    # is readable from both oracle and caps directly.
    new = pitching_caps.game_context(229)
    assert set(new) == set(old)
    assert new["home_team"] == old["home_team"]
    assert new["away_team"] == old["away_team"]
    assert new["lmu_is_home"] == old["lmu_is_home"]
    assert new["lmu_runs"] == old["lmu_runs"]
    assert new["opp_runs"] == old["opp_runs"]
    assert str(new["game_date"])[:10] == str(old["game_date"])[:10]


def test_game_context_derives_season_label_format():
    ctx = pitching_caps.game_context(GAME_ID)
    # GAMES has no season_label column; caps derives "Spring 2026"/"Fall 2025"
    # from Date using the same Jan-Jun/Jul-Dec split as
    # app.dashboards.date_range.season_block. Game 315 is 2026-05-15.
    assert ctx["season_label"] == "Spring 2026"


def test_batters_faced_max_equals_pa_count():
    old, new = _oracle_and_caps_game_df()
    old_bf = int(old["batters_faced"].max())
    new_bf = int(new["batters_faced"].max())
    assert new_bf == old_bf
    assert new_bf == pitching._pa_count(new)


# --------------------------- velo views -----------------------------------
#
# NOTE (documented divergence): GAMES carries more historical seasons for
# this fixture pitcher than the warehouse's fact_tm_game_pitch does (which
# only goes back to Spring 2026 for pitcher_id=6/823008) -- verified live.
# recent_outings' n=5 window falls entirely inside the shared season, so it
# compares row-for-row; velo_trend restricts the comparison to the shared
# season (Spring 2026) since caps naturally returns more history. This is a
# data-coverage difference, not a filter-logic bug: for the season+games both
# id-spaces know about, values match exactly.

def test_recent_outings_matches_warehouse_velo():
    old = pitching.recent_outings(SURROGATE_PID, GAME_ID)
    new = pitching_caps.recent_outings(RAW_PID, GAME_ID)
    assert len(old) == len(new) == 5
    assert list(old["game_id"].astype(int)) == list(new["game_id"].astype(int))
    assert [str(d) for d in old["game_date"]] == [str(d) for d in new["game_date"]]
    for col in ("appearance_avg_velo", "appearance_max_velo",
                "appearance_min_velo", "pitch_count"):
        pd.testing.assert_series_equal(
            old[col].reset_index(drop=True), new[col].reset_index(drop=True),
            check_names=False, check_dtype=False, rtol=1e-6,
        )


def test_recent_outings_team_names_from_games():
    new = pitching_caps.recent_outings(RAW_PID, GAME_ID)
    assert (new["home_team_name"].str.len() > 0).all()
    assert (new["away_team_name"].str.len() > 0).all()


def test_recent_outings_empty_for_unknown_pitcher():
    df = pitching_caps.recent_outings(999999999, GAME_ID)
    assert df.empty
    assert list(df.columns) == [
        "game_id", "game_date", "season_label", "game_type",
        "home_team_name", "away_team_name", "appearance_avg_velo",
        "appearance_max_velo", "appearance_min_velo", "pitch_count",
    ]


def test_velo_trend_matches_warehouse_for_shared_season():
    old = pitching.velo_trend(SURROGATE_PID).reset_index(drop=True)
    new = pitching_caps.velo_trend(RAW_PID)
    start = str(old["game_date"].min())
    new_shared = new[new["game_date"].astype(str) >= start].reset_index(drop=True)
    assert len(new_shared) == len(old) > 0
    for col in ("avg_velo", "max_velo", "velo_change"):
        pd.testing.assert_series_equal(
            old[col], new_shared[col], check_names=False, rtol=1e-6,
        )
    pd.testing.assert_series_equal(
        old["pitch_count"], new_shared["pitch_count"],
        check_names=False, check_dtype=False,
    )
    # First appearance of the (only) season in the oracle df has no prior
    # appearance to diff against; caps resets velo_change the same way at
    # its own season boundary.
    assert pd.isna(new_shared["velo_change"].iloc[0])


def test_velo_trend_chronological_order():
    new = pitching_caps.velo_trend(RAW_PID)
    dates = list(new["game_date"].astype(str))
    assert dates == sorted(dates)


def test_velo_trend_empty_for_unknown_pitcher():
    df = pitching_caps.velo_trend(999999999)
    assert df.empty
    assert list(df.columns) == ["game_date", "avg_velo", "max_velo", "pitch_count", "velo_change"]


def test_report_data_version_matches_warehouse_max_date():
    old = pitching.report_data_version(SURROGATE_PID)
    new = pitching_caps.report_data_version(RAW_PID)
    expected = str(pitching_caps._pitcher_velo_appearances(RAW_PID)["game_date"].max())
    assert new == expected
    # The oracle's max date (bounded by the warehouse's narrower fact-table
    # history) must still fall within caps' broader GAMES history.
    assert old <= new


def test_report_data_version_none_for_unknown_pitcher():
    assert pitching_caps.report_data_version(999999999) == "none"


# --------------------------- identity + roster -----------------------------
#
# GAMES.Pitcher is verified live as "Last, First" (e.g. "Behrens, Adam"), the
# same format pitching.wh_lmu_pitchers/pitchers_for_game build from tm_player.
# pitching.pitcher_name, though, builds "First Last" -- so
# pitching_caps.pitcher_name must split "Last, First" -> "First Last" while
# pitching_caps.lmu_pitchers/pitchers_for_game read GAMES.Pitcher as-is.

def test_pitcher_name_matches_warehouse_first_last_format():
    old = pitching.pitcher_name(SURROGATE_PID)
    new = pitching_caps.pitcher_name(RAW_PID)
    assert new == old == "Adam Behrens"


def test_pitcher_name_unknown_id_placeholder():
    assert pitching_caps.pitcher_name(999999999) == "Pitcher 999999999"


def test_pitcher_tm_id_for_is_identity():
    assert pitching_caps.pitcher_tm_id_for(RAW_PID) == RAW_PID


def test_pitcher_profile_matches_warehouse():
    old = pitching.pitcher_profile(SURROGATE_PID)
    new = pitching_caps.pitcher_profile(RAW_PID)
    assert new["name"] == old["name"] == "Adam Behrens"
    assert new["throws"] == old["throws"]
    assert new["jersey"] == old["jersey"]
    assert new["photo"] == old["photo"]
    assert new["class_year"] == old["class_year"] == ""
    assert new["position"] == old["position"] == ""


def test_lmu_pitchers_matches_warehouse():
    # Superset + window-bound, mirroring hitting_caps.lmu_hitters's parity
    # test: GAMES holds full CAPS history back to 2022 while the warehouse
    # oracle (fact_tm_game_pitch) only covers the current synced season, so
    # an unscoped caps query would leak retired alumni. lmu_pitchers windows
    # to the trailing ~12 months (anchored to the newest GAMES date).
    old = pitching.wh_lmu_pitchers()
    new = pitching_caps.lmu_pitchers()

    # 1. SUPERSET: every current-season warehouse pitcher is present by name.
    assert set(old["Pitcher"]) <= set(new["Pitcher"])

    # 2. WINDOW BOUND: scoping is doing real work.
    all_time = query_df(
        "SELECT COUNT(DISTINCT Pitcher) n FROM GAMES "
        "WHERE PitcherTeam = :t AND PitcherId IS NOT NULL",
        {"t": pitching_caps.LMU_PITCHER_TEAM},
    ).iloc[0]["n"]
    assert len(new) < all_time

    # 3. canonical-id sibling check: whichever raw id the warehouse's chosen
    # surrogate id maps to must be a sibling of whatever id lmu_pitchers
    # picked as canonical for that name (both resolve to the same union via
    # _sibling_pitcher_ids downstream, so the specific "most-tracked" id is
    # interchangeable).
    new_by_name = dict(zip(new["Pitcher"], new["PitcherId"]))
    for _, row in old.iterrows():
        raw = pitching.pitcher_tm_id_for(int(row["PitcherId"]))
        siblings = pitching_caps._sibling_pitcher_ids(new_by_name[row["Pitcher"]])
        assert raw in siblings


def test_lmu_pitchers_columns():
    df = pitching_caps.lmu_pitchers()
    assert list(df.columns) == ["PitcherId", "Pitcher"]


def test_lmu_pitchers_all_have_numeric_game_id_rows():
    # No-ghost property (mirrors catching_caps/hitting_caps's regression):
    # lmu_pitchers used to scope purely by the date-only _RECENT_WINDOW_CLAUSE,
    # so a pitcher whose only in-window games carried legacy composite-string
    # GameIDs would be listed while every numeric-GameID-guarded data function
    # (games_for_pitcher, season_summary, range_summary, velo views) returned
    # empty for them. Checked as a single SQL set-membership query rather than
    # N per-id round trips.
    ids = set(pitching_caps.lmu_pitchers()["PitcherId"].astype(int))
    current_ids = set(query_df(
        "SELECT DISTINCT PitcherId FROM GAMES "
        "WHERE PitcherTeam = :t AND PitcherId IS NOT NULL "
        f"AND {pitching_caps._NUMERIC_GAME_ID_CLAUSE}",
        {"t": pitching_caps.LMU_PITCHER_TEAM},
    )["PitcherId"].astype(int))
    assert ids <= current_ids


def test_games_for_pitcher_unbounded_matches_labels():
    # GAMES carries this raw id's rows back to 2024 via pre-CAPS-migration
    # composite string GameIDs (e.g. "20241019-LoyolaMarymount-1") that
    # games_for_pitcher excludes via a numeric-GameID filter (both to avoid
    # crashing on the int-cast and because that filter happens to coincide
    # exactly with the warehouse oracle's synced-season boundary) -- so this
    # is real equality, not a superset, even unbounded.
    old = (pitching.games_for_pitcher(SURROGATE_PID)[["game_id", "GameLabel"]]
           .sort_values("game_id").reset_index(drop=True))
    new = (pitching_caps.games_for_pitcher(RAW_PID)[["game_id", "GameLabel"]]
           .sort_values("game_id").reset_index(drop=True))
    pd.testing.assert_frame_equal(new, old, check_dtype=False)


def test_games_for_pitcher_date_range_filters():
    # Real, exact parity (bridging the data-coverage gap above): bounded to
    # the oracle's own outing span, both sides see the same games, order-
    # independent like hitting's test_games_for_batter_matches_labels (the
    # oracle has no secondary ORDER BY, so same-date tie order is DB-planner
    # incidental, not a real contract).
    games = pitching.games_for_pitcher(SURROGATE_PID)
    start, end = games["game_date"].min(), games["game_date"].max()
    old = pitching.games_for_pitcher(SURROGATE_PID, start, end)[["game_id", "GameLabel"]].copy()
    new = pitching_caps.games_for_pitcher(RAW_PID, start, end)[["game_id", "GameLabel"]].copy()
    old["game_id"] = old["game_id"].astype(int)
    new["game_id"] = new["game_id"].astype(int)
    old = old.sort_values("game_id").reset_index(drop=True)
    new = new.sort_values("game_id").reset_index(drop=True)
    pd.testing.assert_frame_equal(new, old, check_dtype=False)


def test_pitchers_for_game_matches_warehouse_pitch_order():
    old = pitching.pitchers_for_game(GAME_ID, "pitch")
    new = pitching_caps.pitchers_for_game(GAME_ID, "pitch")
    assert list(new["display_name"]) == list(old["display_name"])
    old_raw_ids = [pitching.pitcher_tm_id_for(int(pid)) for pid in old["player_id"]]
    assert list(new["player_id"].astype(int)) == old_raw_ids


def test_pitchers_for_game_alpha_sort():
    old = pitching.pitchers_for_game(GAME_ID, "alpha")
    new = pitching_caps.pitchers_for_game(GAME_ID, "alpha")
    assert list(new["display_name"]) == list(old["display_name"])
    names = list(new["display_name"])
    assert names == sorted(names)


def test_recent_games_matches_warehouse():
    old = pitching.recent_games(10)
    new = pitching_caps.recent_games(10)
    assert len(new) == len(old) == 10
    assert list(new["game_id"].astype(int)) == list(old["game_id"].astype(int))
    assert [str(d) for d in new["game_date"]] == [str(d) for d in old["game_date"]]
    assert list(new["season_label"]) == list(old["season_label"])
    assert list(new["home_team"]) == list(old["home_team"])
    assert list(new["away_team"]) == list(old["away_team"])


# --------------------------- season / range summaries -----------------------
#
# Unlike the velo views / games_for_pitcher, season_summary and range_summary
# have NO game_id-driven date bound, so GAMES's pre-CAPS-migration composite-
# string-GameID scrimmage rows (see games_for_pitcher's docstring) would
# otherwise inflate whole-career totals beyond the warehouse oracle's synced-
# season scope. Both apply the same numeric-GameID restriction
# games_for_pitcher uses -- verified live for this fixture pitcher (raw id
# 823008) that doing so reproduces the oracle's totals exactly (1296 pitches/
# 20 apps/56 K/19 BB either way), so these are real equality assertions, not
# documented divergence.

def test_season_summary_matches_warehouse():
    old = pitching.season_summary(SURROGATE_PID)
    new = pitching_caps.season_summary(RAW_PID)
    assert new == old == {"appearances": "20", "pitches": "1296", "k": "56", "bb": "19"}


def test_season_summary_zero_for_unknown_pitcher():
    old = pitching.season_summary(999999999)
    new = pitching_caps.season_summary(999999999)
    assert new == old == {"appearances": "0", "pitches": "0", "k": "—", "bb": "—"}


def test_range_summary_matches_warehouse_for_full_span():
    games = pitching.games_for_pitcher(SURROGATE_PID)
    start, end = games["game_date"].min(), games["game_date"].max()
    old = pitching.range_summary(SURROGATE_PID, start, end)
    new = pitching_caps.range_summary(RAW_PID, start, end)
    assert new == old


def test_range_summary_unbounded_matches_warehouse():
    # No start/end: both sides fall back to their respective "whole career"
    # scope, which -- for this fixture -- coincides exactly with the bounded
    # span above (the warehouse fact table and GAMES's numeric-GameID rows
    # cover the same seasons for this pitcher).
    old = pitching.range_summary(SURROGATE_PID)
    new = pitching_caps.range_summary(RAW_PID)
    assert new == old


def test_range_summary_empty_for_unknown_pitcher():
    old = pitching.range_summary(999999999)
    new = pitching_caps.range_summary(999999999)
    expected = {"appearances": "—", "ip": "—", "k_pct": "—",
                "bb_pct": "—", "barrel_pct": "—"}
    assert new == old == expected


def test_report_data_version_present():
    # Confirms Task 3 already wired this up; Task 5 just double-checks it's
    # still here alongside the new summaries.
    assert hasattr(pitching_caps, "report_data_version")
    assert pitching_caps.report_data_version(RAW_PID) != "none"
