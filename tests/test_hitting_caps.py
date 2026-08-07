import pandas as pd
from app.db import query_df
from app.data import hitting_wh, hitting_caps
from app.data.hitting import game_batting_line, swing_decisions_by_zone, plate_discipline

WADAS = 806253

# Returning veteran hitter with BOTH current/backfilled numeric GameIDs and
# legacy pre-2025 composite-string GameIDs (e.g.
# "20241023-LoyolaMarymount-Private-1") in GAMES -- verified live. Before the
# REGEXP '^[0-9]+$' guard, games_for_batter/last_n_pas crashed for this
# hitter with `ValueError: invalid literal for int() with base 10` the
# instant they tried `.astype(int)` / `int(...)` on a composite GameID.
VETERAN = 801956  # "Danos, Luca"


def _first_game(bid):
    g = hitting_wh.wh_games_for_batter(bid)
    return int(g.iloc[0]["game_id"])


def test_game_pitches_matches_warehouse_batting_line():
    gid = _first_game(WADAS)
    old = hitting_wh.wh_game_pitches(gid, WADAS)
    new = hitting_caps.game_pitches(gid, WADAS)
    # same number of pitches, same core columns
    assert len(new) == len(old)
    # semantic parity: the batting line the UI shows is identical
    # (game_batting_line returns a dict, not a DataFrame -- compare directly)
    assert game_batting_line(new) == game_batting_line(old)


def test_game_pitches_matches_plate_discipline_and_zone():
    gid = _first_game(WADAS)
    old = hitting_wh.wh_game_pitches(gid, WADAS)
    new = hitting_caps.game_pitches(gid, WADAS)
    pd.testing.assert_frame_equal(plate_discipline(new).reset_index(drop=True),
                                  plate_discipline(old).reset_index(drop=True), check_dtype=False)
    pd.testing.assert_frame_equal(swing_decisions_by_zone(new).reset_index(drop=True),
                                  swing_decisions_by_zone(old).reset_index(drop=True), check_dtype=False)


def test_range_pitches_matches_season_pitch_count():
    old = hitting_wh.wh_season_pitches(WADAS)
    new = hitting_caps.season_pitches(WADAS)
    assert len(new) == len(old)


def test_range_pitches_matches_warehouse():
    # Real parity (not just a length check, unlike
    # test_range_pitches_matches_season_pitch_count above): drive both sides
    # over Wadas's full season span so the range covers every one of his
    # games, then assert the batting line transform agrees, plus row count.
    g = hitting_wh.wh_games_for_batter(WADAS)
    start, end = g["game_date"].min(), g["game_date"].max()
    old = hitting_wh.wh_range_pitches(WADAS, start, end)
    new = hitting_caps.range_pitches(WADAS, start, end)
    assert len(new) == len(old)
    assert game_batting_line(new) == game_batting_line(old)


def test_games_for_batter_matches_labels():
    # Order-independent: the warehouse oracle (wh_games_for_batter) has no
    # secondary ORDER BY, so its same-date (doubleheader) tie order is
    # DB-planner incidental, not a real contract -- comparing after sorting
    # both sides by game_id asserts the real parity (same games, same labels)
    # without depending on that noise.
    old = (hitting_wh.wh_games_for_batter(WADAS)[["game_id", "GameLabel"]]
           .sort_values("game_id").reset_index(drop=True))
    new = (hitting_caps.games_for_batter(WADAS)[["game_id", "GameLabel"]]
           .sort_values("game_id").reset_index(drop=True))
    pd.testing.assert_frame_equal(new, old, check_dtype=False)


def test_games_for_batter_is_deterministically_ordered():
    # hitting_caps-only property (no oracle): rows are sorted by game_date
    # descending, and within an equal date, by game_id descending. This is an
    # intentional improvement over the warehouse oracle, which has no
    # secondary sort key at all.
    df = hitting_caps.games_for_batter(WADAS)
    dates = pd.to_datetime(df["game_date"])
    assert list(dates) == sorted(dates, reverse=True)
    for _, grp in df.groupby("game_date"):
        ids = list(grp["game_id"])
        assert ids == sorted(ids, reverse=True)


def test_scoreboard_matches_warehouse():
    gid = _first_game(WADAS)
    old = hitting_wh.wh_scoreboard(gid)
    new = hitting_caps.scoreboard(gid)
    assert new == old


def test_player_profile_matches_warehouse():
    old = hitting_wh.wh_player_profile(WADAS)
    new = hitting_caps.player_profile(WADAS)
    assert new["name"] == old["name"]
    assert new["bats"] == old["bats"]
    assert new == old


def test_season_qab_rate_matches_warehouse():
    old = hitting_wh.wh_season_qab_rate(WADAS)
    new = hitting_caps.season_qab_rate(WADAS)
    assert new == old


def test_slash_line_matches_warehouse():
    old = hitting_wh.wh_slash_line(WADAS)
    new = hitting_caps.slash_line(WADAS)
    assert new == old


def test_sidebar_stats_matches_qab_and_slash():
    qab = hitting_caps.season_qab_rate(WADAS)
    slash = hitting_caps.slash_line(WADAS)
    sidebar = hitting_caps.sidebar_stats(WADAS)
    assert set(sidebar) == {"qab", "BA", "SLG", "OBP"}
    assert sidebar["qab"] == qab
    assert sidebar["BA"] == slash["BA"]
    assert sidebar["SLG"] == slash["SLG"]
    assert sidebar["OBP"] == slash["OBP"]


def test_lmu_hitters_matches_warehouse():
    # NOT a byte-identical row-set, by design (fix-round 1 decision): GAMES
    # holds full CAPS history back to 2022, while fact_tm_game_pitch (the
    # wh_lmu_hitters source) only covers the current warehouse-synced season
    # (2025-11-22+). An earlier version of hitting_caps.lmu_hitters() was
    # unscoped and leaked 50+ retired alumni into the list, so it's now
    # windowed to the last ~12 months of GAMES data (anchored to the newest
    # GAMES date, not "today" -- see lmu_hitters docstring for why).
    #
    # Three real invariants, all confirmed live:
    old = hitting_wh.wh_lmu_hitters()
    new = hitting_caps.lmu_hitters()

    # 1. SUPERSET: every current-season warehouse hitter is present.
    assert set(old["Batter"]) <= set(new["Batter"])

    # 2. WINDOW BOUND: the window is doing real work (33 caps vs 80 unscoped)
    # and a known pre-window alumnus (last game 2022-03-11) does not leak in.
    all_time = query_df(
        "SELECT COUNT(DISTINCT Batter) n FROM GAMES "
        "WHERE BatterTeam = :t AND BatterId IS NOT NULL",
        {"t": hitting_caps.LMU_BATTER_TEAM},
    ).iloc[0]["n"]
    assert len(new) < all_time
    assert "Hackman, Owen" not in set(new["Batter"])

    # 3. canonical-id sibling check: for hitters the warehouse DOES know, its
    # chosen id must be a valid *sibling* of the id hitting_caps picked as
    # canonical for that name -- downstream stats (game_pitches/
    # season_pitches/etc.) resolve any of a name's ids to the same sibling-id
    # union via _sibling_ids, so which specific id wins hitting_caps's
    # "most-tracked" tiebreak is interchangeable. (Windowing the COUNT(*)
    # tiebreak to the last 12 months also fixed a quirk found in the unscoped
    # version, where Dunn, JD and Casale, Johnny got an old pre-2025 id
    # because GAMES had more career pitches under it -- both now resolve to
    # their current-season id, matching the warehouse exactly.)
    new_by_name = dict(zip(new["Batter"], new["BatterId"]))
    for _, row in old.iterrows():
        siblings = hitting_caps._sibling_ids(int(row["BatterId"]))
        assert new_by_name[row["Batter"]] in siblings


def test_lmu_hitters_all_have_numeric_game_id_rows():
    # No-ghost property (mirrors catching_caps/pitching_caps's regression):
    # lmu_hitters used to scope purely by the date-only _RECENT_WINDOW_CLAUSE,
    # so a hitter whose only in-window games carried legacy composite-string
    # GameIDs would be listed while every numeric-GameID-guarded data function
    # (games_for_batter, season_pitches, etc.) returned empty for them.
    # Checked as a single SQL set-membership query rather than N per-id round
    # trips.
    ids = set(hitting_caps.lmu_hitters()["BatterId"].astype(int))
    current_ids = set(query_df(
        "SELECT DISTINCT BatterId FROM GAMES "
        "WHERE BatterTeam = :t AND BatterId IS NOT NULL "
        "AND GameID REGEXP '^[0-9]+$'",
        {"t": hitting_caps.LMU_BATTER_TEAM},
    )["BatterId"].astype(int))
    assert ids <= current_ids


def _first_bip_game(bid):
    """First game (by wh_games_for_batter order) with >=1 ball in play."""
    for gid in hitting_wh.wh_games_for_batter(bid)["game_id"]:
        if not hitting_wh.wh_bip_points(bid, int(gid)).empty:
            return int(gid)
    raise AssertionError("no BIP game found for WADAS fixture")


def test_bip_points_matches_warehouse_math():
    # GAMES stores a real launch angle in `Angle` (unlike the pitch-level
    # transforms, which NaN it via _finish) so the warehouse's spray/radial
    # math should reproduce exactly here -- x/y/rx/ry must match, not just
    # be close-ish.
    gid = _first_bip_game(WADAS)
    old = hitting_wh.wh_bip_points(WADAS, gid)
    new = hitting_caps.bip_points(WADAS, gid)
    assert len(new) == len(old) > 0
    cols = ["hit_type", "x", "y", "rx", "ry"]
    pd.testing.assert_frame_equal(
        new[cols].reset_index(drop=True), old[cols].reset_index(drop=True),
        check_dtype=False)


def test_veteran_fixture_has_both_numeric_and_legacy_game_ids():
    # Sanity-check the fixture itself: guards against DB drift silently
    # making the regression tests below meaningless (e.g. if the legacy rows
    # were ever purged, the crash they'd otherwise trigger just wouldn't
    # happen and the tests would pass for the wrong reason).
    df = query_df(
        "SELECT GameID FROM GAMES WHERE BatterId = :b", {"b": VETERAN})
    ids = df["GameID"].astype(str)
    assert (ids.str.match(r"^[0-9]+$")).any(), "expected some numeric GameIDs"
    assert (~ids.str.match(r"^[0-9]+$")).any(), "expected some legacy composite GameIDs"


def test_games_for_batter_returns_only_numeric_game_ids_for_veteran():
    # RED before the fix: GAMES holds legacy composite-string GameIDs (e.g.
    # "20241023-LoyolaMarymount-Private-1") for this veteran alongside his
    # current numeric ones. Without the REGEXP '^[0-9]+$' guard in the SQL,
    # `df["game_id"] = df["game_id"].astype(int)` inside games_for_batter
    # raises ValueError the moment a composite id comes back from the query
    # -- this crashed the live hitting dashboard for any returning veteran.
    df = hitting_caps.games_for_batter(VETERAN)
    assert not df.empty
    # The line below is exactly what games_for_batter itself executes
    # internally; if it didn't raise, every game_id must already be
    # int-castable -- i.e. no composite legacy id leaked through.
    df["game_id"].astype(int)


def test_games_for_batter_sql_guards_non_numeric_game_ids():
    # Cheaper, DB-independent companion to the regression test above: pin
    # down the actual mechanism of the fix (a SQL-level REGEXP filter),
    # mirroring pitching_caps.games_for_pitcher's fix for the identical bug.
    import inspect
    src = inspect.getsource(hitting_caps.games_for_batter)
    assert "GameID REGEXP '^[0-9]+$'" in src


def test_last_n_pas_does_not_crash_for_veteran_with_legacy_game_ids():
    # RED before the fix: last_n_pas's `all_df["GameID"]` (selected via
    # _PITCH_COLS, unfiltered) carries the same composite legacy GameIDs
    # through to `int(g)` inside the mask comprehension, crashing with the
    # identical ValueError as games_for_batter above -- CAST(...AS UNSIGNED)
    # in the ORDER BY only truncates, it doesn't protect this later int()
    # call on the raw column.
    df = hitting_caps.last_n_pas(VETERAN, 27)
    assert not df.empty


def test_last_n_pas_matches_warehouse_keys():
    old = hitting_wh.wh_last_n_pas(WADAS, 27)
    new = hitting_caps.last_n_pas(WADAS, 27)
    assert len(new) == len(old)
    old_keys = set(zip(old["GameID"].astype(int), old["Inning"].astype(int),
                        old["PAofInning"].astype(int)))
    new_keys = set(zip(new["GameID"].astype(int), new["Inning"].astype(int),
                        new["PAofInning"].astype(int)))
    assert new_keys == old_keys
