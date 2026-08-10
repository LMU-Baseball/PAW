"""CAPS pitching data-access tests.

This file used to hold warehouse-vs-CAPS *parity* tests (each comparing the
``app.data.pitching`` warehouse oracle against ``app.data.pitching_caps``).
The warehouse oracle query functions were removed in the Phase-3 warehouse
drop, so every oracle-comparison test was deleted; what remains here are the
standalone CAPS regression tests that exercise ``pitching_caps`` directly
against the live ``GAMES`` table.
"""
import pandas as pd
import pytest

from app.db import query_df
from app.data import pitching_caps

# Behrens, Adam: raw trackman id 823008, game_id 315 (2026-05-15, LMU @ USD).
RAW_PID = 823008
GAME_ID = 315


def test_sibling_pitcher_ids_includes_raw_id():
    ids = pitching_caps._sibling_pitcher_ids(RAW_PID)
    assert RAW_PID in ids


def test_game_context_derives_season_label_format():
    ctx = pitching_caps.game_context(GAME_ID)
    # GAMES has no season_label column; caps derives "Spring 2026"/"Fall 2025"
    # from Date using the same Jan-Jun/Jul-Dec split as
    # app.dashboards.date_range.season_block. Game 315 is 2026-05-15.
    assert ctx["season_label"] == "Spring 2026"


# --------------------------- velo views -----------------------------------

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


def test_velo_trend_chronological_order():
    new = pitching_caps.velo_trend(RAW_PID)
    dates = list(new["game_date"].astype(str))
    assert dates == sorted(dates)


def test_velo_trend_empty_for_unknown_pitcher():
    df = pitching_caps.velo_trend(999999999)
    assert df.empty
    assert list(df.columns) == ["game_date", "avg_velo", "max_velo", "pitch_count", "velo_change"]


def test_report_data_version_none_for_unknown_pitcher():
    assert pitching_caps.report_data_version(999999999) == "none"


# --------------------------- identity + roster -----------------------------

def test_pitcher_name_unknown_id_placeholder():
    assert pitching_caps.pitcher_name(999999999) == "Pitcher 999999999"


def test_pitcher_tm_id_for_is_identity():
    assert pitching_caps.pitcher_tm_id_for(RAW_PID) == RAW_PID


def test_lmu_pitchers_columns():
    df = pitching_caps.lmu_pitchers()
    assert list(df.columns) == ["PitcherId", "Pitcher"]


def test_lmu_pitchers_all_have_numeric_game_id_rows():
    # No-ghost property (mirrors catching_caps/hitting_caps's regression):
    # lmu_pitchers is now scoped by the current season's Date bounds
    # (seasons.season_bounds), and the current season is the warehouse-
    # backfilled one whose games all carry numeric surrogate GameIDs. So every
    # listed pitcher should still have >=1 numeric-GameID row -- i.e. no
    # "ghost" whose only in-season games are legacy composite-string GameIDs
    # (which would leave every game-level data function empty for them).
    # Checked as a single SQL set-membership query rather than N per-id round
    # trips (the module no longer exposes a _NUMERIC_GAME_ID_CLAUSE constant,
    # so the numeric REGEXP is inlined here, mirroring test_hitting_caps).
    ids = set(pitching_caps.lmu_pitchers()["PitcherId"].astype(int))
    current_ids = set(query_df(
        "SELECT DISTINCT PitcherId FROM GAMES "
        "WHERE PitcherTeam = :t AND PitcherId IS NOT NULL "
        "AND GameID REGEXP '^[0-9]+$'",
        {"t": pitching_caps.LMU_PITCHER_TEAM},
    )["PitcherId"].astype(int))
    assert ids <= current_ids


def test_games_for_pitcher_has_no_numeric_game_id_guard():
    # Opaque-GameID contract (mirrors test_hitting_caps.
    # test_games_for_batter_has_no_numeric_game_id_guard): games_for_pitcher no
    # longer filters to numeric surrogate ids. The SQL-level REGEXP numeric
    # guard is GONE, so outings are scoped by date only and a returning
    # veteran's legacy composite-string games (e.g. "20241019-LoyolaMarymount-1")
    # list too. game_id is an opaque string -- never int-cast.
    import inspect
    src = inspect.getsource(pitching_caps.games_for_pitcher)
    assert "GameID REGEXP" not in src
    assert "astype(int)" not in src


def test_lmu_pitchers_scopes_by_date():
    # Task 5: the Pitcher dropdown on the game dashboards must narrow to
    # players with data in the selected date range (nested inside the season).
    from app.data import seasons
    season = seasons.current_season()
    s, e = seasons.season_bounds(season)
    full = set(pitching_caps.lmu_pitchers(season)["PitcherId"])
    ranged = set(pitching_caps.lmu_pitchers(season, start=str(s), end=str(e))["PitcherId"])
    assert ranged <= full
    assert ranged == full          # start/end == the season's own bounds
    empty = pitching_caps.lmu_pitchers(season, start="1900-01-01", end="1900-01-02")
    assert empty.empty


def test_lmu_pitchers_season_scoped_and_past_seasons_surface():
    # The season-dropdown blocker: a PAST season's roster + outings used to be
    # invisible because the numeric-GameID guard hid legacy composite-GameID
    # games. lmu_pitchers(season) is now date-scoped (seasons.season_bounds),
    # so passing no arg == current season, and a past season returns its own
    # roster whose pitchers' outings surface.
    from app.data import seasons
    assert pitching_caps.lmu_pitchers().equals(
        pitching_caps.lmu_pitchers(seasons.current_season()))
    past = [s for s in seasons.available_seasons() if s != seasons.current_season()]
    if not past:
        pytest.skip("no past season in GAMES to exercise the season dropdown")
    roster = pitching_caps.lmu_pitchers(past[0])
    assert list(roster.columns) == ["PitcherId", "Pitcher"]
    if roster.empty:
        pytest.skip("past-season roster empty")
    pid = int(roster.iloc[0]["PitcherId"])
    g = pitching_caps.games_for_pitcher(pid, *seasons.season_bounds(past[0]))
    assert not g.empty  # past-season outings now surface (were hidden pre-fix)
    # game_id is opaque: string values, not necessarily int-castable
    assert all(isinstance(v, str) for v in g["game_id"])


def test_report_data_version_present():
    assert hasattr(pitching_caps, "report_data_version")
    assert pitching_caps.report_data_version(RAW_PID) != "none"


def test_range_summary_uses_precalc_when_range_matches_season_bounds(monkeypatch):
    """A range that exactly matches an academic season's bounds (the Season
    dropdown's default range) reads that (pitcher, season) rollup instead of
    loading the season."""
    from app.data import precalc, seasons
    s_b, e_b = seasons.season_bounds(seasons.current_season())
    sentinel = {"min_date": "2025-11-01", "max_date": "2026-05-16",
                "appearances": "7", "ip": "12.1", "k_pct": "30.0%",
                "bb_pct": "6.0%", "barrel_pct": "5.0%"}
    monkeypatch.setattr(precalc, "read_pitching_season", lambda p, season=None: sentinel)
    out = pitching_caps.range_summary(RAW_PID, s_b, e_b)
    assert out == {"appearances": "7", "ip": "12.1", "k_pct": "30.0%",
                   "bb_pct": "6.0%", "barrel_pct": "5.0%"}


def test_range_summary_falls_back_to_compute_when_missing(monkeypatch):
    """No rollup row -> compute on the fly (correct, just slower)."""
    from app.data import precalc
    monkeypatch.setattr(precalc, "read_pitching_season", lambda p: None)
    out = pitching_caps.range_summary(RAW_PID)
    assert set(out) == {"appearances", "ip", "k_pct", "bb_pct", "barrel_pct"}


def test_pitchers_for_game_columns_lmu_and_ordering():
    """Correctness guard for the perf rewrite (correlated ORDER BY subquery ->
    GROUP BY): same columns, pitch-order = ascending first-pitch, alpha-order =
    name-sorted, and both sorts return the same pitcher set."""
    g = pitching_caps.recent_games(5)
    gid = int(g.iloc[0]["game_id"])
    df = pitching_caps.pitchers_for_game(gid, sort="pitch")
    assert list(df.columns) == ["game_id", "player_id", "display_name"]
    assert not df.empty
    # pitch order = ascending MIN(PitchNo) per pitcher (computed independently)
    mins = {}
    for pid in df["player_id"]:
        m = query_df("SELECT MIN(PitchNo) AS mn FROM GAMES WHERE GameID = :g AND PitcherId = :p",
                     {"g": str(gid), "p": int(pid)})
        mins[int(pid)] = int(m.iloc[0]["mn"])
    order = [mins[int(p)] for p in df["player_id"]]
    assert order == sorted(order)
    # alpha = same set of pitchers, name-sorted
    da = pitching_caps.pitchers_for_game(gid, sort="alpha")
    assert set(da["player_id"]) == set(df["player_id"])
    assert list(da["display_name"]) == sorted(da["display_name"])
