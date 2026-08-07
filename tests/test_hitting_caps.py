import pandas as pd
from app.data import hitting_wh, hitting_caps
from app.data.hitting import game_batting_line, swing_decisions_by_zone, plate_discipline

WADAS = 806253


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
