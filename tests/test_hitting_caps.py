import math

import pandas as pd
from app.db import query_df
from app.data import hitting_caps, cache
from app.data.hitting import game_batting_line, swing_decisions_by_zone, plate_discipline

WADAS = 806253


def test_scoreboard_is_memoized(monkeypatch):
    """scoreboard() is @cached: a repeat call for the same game makes no query."""
    cache.clear_all()
    calls = []
    monkeypatch.setattr(hitting_caps, "query_df", lambda sql, params=None: (
        calls.append(1),
        pd.DataFrame([{"Date": "2026-03-01", "HomeTeam": "LMU", "AwayTeam": "USD",
                       "HomeTeamForeignID": hitting_caps.LMU_TEAM_ID,
                       "GameType": "Regular"}]))[1])
    a = hitting_caps.scoreboard("G-sb-1")
    b = hitting_caps.scoreboard("G-sb-1")
    assert a == b
    assert len(calls) == 1                 # second call served from cache
    assert a["loc"] == "vs" and a["opp"] == "USD"

# Returning veteran hitter with BOTH current/backfilled numeric GameIDs and
# legacy pre-2025 composite-string GameIDs (e.g.
# "20241023-LoyolaMarymount-Private-1") in GAMES -- verified live. Before the
# REGEXP '^[0-9]+$' guard, games_for_batter/last_n_pas crashed for this
# hitter with `ValueError: invalid literal for int() with base 10` the
# instant they tried `.astype(int)` / `int(...)` on a composite GameID.
VETERAN = 801956  # "Danos, Luca"


def _first_game(bid):
    g = hitting_caps.games_for_batter(bid)
    return int(g.iloc[0]["game_id"])


# NOTE: these were originally *_matches_warehouse parity tests comparing
# hitting_caps against the hitting_wh oracle. That oracle was the build-time
# proof and has since been deleted (Phase 3 warehouse drop), so each now makes
# a lightweight BEHAVIORAL assertion on the caps output for the Wadas fixture
# rather than comparing against exact warehouse numbers.


def test_game_pitches_feeds_batting_line():
    gid = _first_game(WADAS)
    df = hitting_caps.game_pitches(gid, WADAS)
    assert not df.empty
    line = game_batting_line(df)
    assert set(line) >= {"PA", "H", "SO", "BB", "QAB"}
    assert line["PA"] >= 1
    assert all(isinstance(v, int) for v in line.values())


def test_game_pitches_feeds_plate_discipline_and_zone():
    gid = _first_game(WADAS)
    df = hitting_caps.game_pitches(gid, WADAS)
    pd_out = plate_discipline(df)                 # must not raise
    assert list(pd_out.columns) == ["Zone", "Total", "Swing %", "Whiff %",
                                    "Take %", "Contact %"]
    zone_out = swing_decisions_by_zone(df)        # must not raise
    assert list(zone_out["Zone"]) == ["Heart", "Shadow", "Chase", "Waste"]
    assert zone_out["Total"].sum() >= 1


def test_season_pitches_non_empty():
    df = hitting_caps.season_pitches(WADAS)
    assert not df.empty
    assert "PlateLocSide" in df.columns


def test_range_pitches_over_full_span():
    # Drive range_pitches over Wadas's full season span so the range covers
    # every one of his games, then assert the batting line transform agrees
    # shape-wise and the frame carries pitches.
    g = hitting_caps.games_for_batter(WADAS)
    start, end = g["game_date"].min(), g["game_date"].max()
    df = hitting_caps.range_pitches(WADAS, start, end)
    assert not df.empty
    line = game_batting_line(df)
    assert set(line) >= {"PA", "H", "SO", "BB", "QAB"}
    assert line["PA"] >= 1


def test_games_for_batter_labels():
    df = hitting_caps.games_for_batter(WADAS)
    assert {"game_id", "game_date", "GameLabel"} <= set(df.columns)
    assert len(df) >= 1
    # every label is a non-empty formatted string like "05/12/24 vs Pepperdine"
    assert df["GameLabel"].map(lambda s: isinstance(s, str) and bool(s)).all()


def test_games_for_batter_is_deterministically_ordered():
    # hitting_caps-only property (no oracle): rows are sorted by game_date
    # descending, and within an equal date, by game_id descending. This is an
    # intentional improvement over the old warehouse oracle, which had no
    # secondary sort key at all.
    df = hitting_caps.games_for_batter(WADAS)
    dates = pd.to_datetime(df["game_date"])
    assert list(dates) == sorted(dates, reverse=True)
    for _, grp in df.groupby("game_date"):
        ids = list(grp["game_id"])
        assert ids == sorted(ids, reverse=True)


def test_scoreboard_shape():
    gid = _first_game(WADAS)
    sb = hitting_caps.scoreboard(gid)
    assert set(sb) == {"date", "loc", "opp", "game_type"}
    assert sb["loc"] in ("vs", "@")
    assert isinstance(sb["date"], str) and sb["date"]


def test_player_profile_shape():
    prof = hitting_caps.player_profile(WADAS)
    assert set(prof) == {"name", "bats", "class_year", "position", "photo", "jersey"}
    assert prof["name"]                # non-empty for a real batter
    # photo/jersey come from the scraped roster_media.json (may or may not have
    # run); either way they must be strings, not None.
    assert isinstance(prof["photo"], str) and isinstance(prof["jersey"], str)


def test_season_qab_rate_is_sane():
    r = hitting_caps.season_qab_rate(WADAS)
    assert r is None or 0.0 <= r <= 1.0


def test_slash_line_shape_and_values():
    sl = hitting_caps.slash_line(WADAS)
    assert set(sl) == {"BA", "SLG", "OBP"}
    for k, v in sl.items():
        assert isinstance(v, str)
        if v != "—":
            float(v)  # parses as a number (e.g. ".326" or "1.021")


def test_slash_line_no_data_is_dashes():
    assert hitting_caps.slash_line(-1) == {"BA": "—", "SLG": "—", "OBP": "—"}


_SIDEBAR_KEYS = {"qab", "BA", "SLG", "OBP", "hard_hit_pct", "popup_pct", "xba"}


def _assert_live_kpi_shapes(sidebar):
    """HARD-HIT%/POP-UP% are percent strings ("—" or "NN.N%"); xBA is
    formatted exactly like BA ("—" or a bare decimal, e.g. ".312")."""
    for k in ("hard_hit_pct", "popup_pct"):
        v = sidebar[k]
        assert isinstance(v, str)
        assert v == "—" or v.endswith("%")
    xba = sidebar["xba"]
    assert isinstance(xba, str)
    if xba != "—":
        float(xba)


def test_sidebar_stats_matches_qab_and_slash():
    qab = hitting_caps.season_qab_rate(WADAS)
    slash = hitting_caps.slash_line(WADAS)
    sidebar = hitting_caps.sidebar_stats(WADAS)
    assert set(sidebar) == _SIDEBAR_KEYS
    assert sidebar["qab"] == qab
    assert sidebar["BA"] == slash["BA"]
    assert sidebar["SLG"] == slash["SLG"]
    assert sidebar["OBP"] == slash["OBP"]
    _assert_live_kpi_shapes(sidebar)


def test_lmu_hitters_shape_and_window():
    # Was a *_matches_warehouse superset/sibling parity test. The oracle is
    # gone, so this keeps only the caps-native invariants (all confirmed live):
    new = hitting_caps.lmu_hitters()

    # 1. SHAPE: one deduped row per hitter name, canonical int BatterId.
    assert list(new.columns) == ["Batter", "BatterId"]
    assert new["Batter"].is_unique
    assert new["BatterId"].is_unique
    assert WADAS in set(new["BatterId"])

    # 2. WINDOW BOUND: the ~12-month window is doing real work (fewer than the
    # full all-time LMU roster held in GAMES) and a known pre-window alumnus
    # (last game 2022-03-11) does not leak in.
    all_time = query_df(
        "SELECT COUNT(DISTINCT Batter) n FROM GAMES "
        "WHERE BatterTeam = :t AND BatterId IS NOT NULL",
        {"t": hitting_caps.LMU_BATTER_TEAM},
    ).iloc[0]["n"]
    assert len(new) < all_time
    assert "Hackman, Owen" not in set(new["Batter"])


def test_lmu_hitters_scopes_by_date():
    # Task 5: the Hitter dropdown on the game dashboards must narrow to
    # players with data in the selected date range (nested inside the season).
    from app.data import seasons
    season = seasons.current_season()
    s, e = seasons.season_bounds(season)
    full = set(hitting_caps.lmu_hitters(season)["BatterId"])
    ranged = set(hitting_caps.lmu_hitters(season, start=str(s), end=str(e))["BatterId"])
    assert ranged <= full
    assert ranged == full          # start/end == the season's own bounds
    empty = hitting_caps.lmu_hitters(season, start="1900-01-01", end="1900-01-02")
    assert empty.empty


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


def test_lmu_hitters_unions_roster_placeholders_including_catchers(monkeypatch):
    from app.data import lmu_roster
    cache.clear_all()
    monkeypatch.setattr(lmu_roster, "load_roster", lambda season: pd.DataFrame([
        {"roster_id": 9101, "first_name": "Test", "last_name": "Infielder",
         "class_year": "FR", "position": "SS"},
        {"roster_id": 9102, "first_name": "Test", "last_name": "Catcher",
         "class_year": "SO", "position": "C"},
        {"roster_id": 9103, "first_name": "Test", "last_name": "Pitcheronly",
         "class_year": "JR", "position": "RHP"},
    ]))
    df = hitting_caps.lmu_hitters("1899/1900")
    assert (df["BatterId"] == -9101).any()
    assert (df["BatterId"] == -9102).any()          # catchers also appear here
    assert not (df["BatterId"] == -9103).any()       # pitcher-only does not
    cache.clear_all()


def test_lmu_hitters_ranged_call_excludes_roster_placeholders(monkeypatch):
    from app.data import lmu_roster
    cache.clear_all()
    monkeypatch.setattr(lmu_roster, "load_roster", lambda season: pd.DataFrame([
        {"roster_id": 9104, "first_name": "Test", "last_name": "Infielder2",
         "class_year": "FR", "position": "SS"},
    ]))
    df = hitting_caps.lmu_hitters("1899/1900", start="1899-08-01", end="1899-08-02")
    assert not (df["BatterId"] == -9104).any() if not df.empty else True
    cache.clear_all()


def _first_bip_game(bid):
    """First game (by games_for_batter order) with >=1 ball in play."""
    for gid in hitting_caps.games_for_batter(bid)["game_id"]:
        if not hitting_caps.bip_points(bid, int(gid)).empty:
            return int(gid)
    raise AssertionError("no BIP game found for WADAS fixture")


def test_bip_points_shape_and_math():
    # GAMES stores a real launch angle in `Angle` (unlike the pitch-level
    # transforms, which NaN it via _finish) so bip_points reads it directly.
    # Assert the spray coordinate math (x = sin(bearing)*distance) for a
    # fully-populated row rather than comparing against a deleted oracle.
    gid = _first_bip_game(WADAS)
    df = hitting_caps.bip_points(WADAS, gid)
    assert len(df) > 0
    for c in ["hit_type", "x", "y", "rx", "ry", "exit_speed", "la"]:
        assert c in df.columns
    row = df.dropna(subset=["bearing", "distance"]).iloc[0]
    exp_x = math.sin(math.radians(row["bearing"])) * row["distance"]
    assert abs(row["x"] - exp_x) < 1e-6


def test_bip_points_empty_game_list():
    df = hitting_caps.bip_points(WADAS, [])
    assert df.empty and "hit_type" in df.columns


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


def test_games_for_batter_includes_legacy_composite_game_ids_for_veteran():
    # Opaque-GameID contract: games_for_batter no longer filters to numeric
    # surrogate ids. A returning veteran's legacy composite-string games (e.g.
    # "20241023-LoyolaMarymount-Private-1") now come back too, so the hitting
    # dashboard can display them. game_id is an opaque string -- NOT int-
    # castable -- and this test proves the composite ids flow all the way
    # through (the exact opposite of the pre-refactor numeric-only behavior).
    import pytest
    df = hitting_caps.games_for_batter(VETERAN)
    assert not df.empty
    with pytest.raises((ValueError, TypeError)):
        df["game_id"].astype(int)


def test_games_for_batter_has_no_numeric_game_id_guard():
    # Cheaper, DB-independent companion: pin down the mechanism of the
    # opaque-GameID refactor -- the SQL-level REGEXP numeric guard is GONE, so
    # games are scoped by date only and composite-id games list.
    import inspect
    src = inspect.getsource(hitting_caps.games_for_batter)
    assert "GameID REGEXP" not in src


def test_game_label_is_nat_safe():
    # Opaque-GameID contract surfaces legacy composite games, some of which
    # carry an empty/unparseable Date. The dropdown label must not crash on
    # those (NaT.strftime raises) -- it drops the date prefix instead.
    assert hitting_caps._game_label("", "vs", "USC") == "vs USC"
    assert hitting_caps._game_label(None, "@", "UCLA") == "@ UCLA"
    assert hitting_caps._game_label("2025-05-17", "vs", "Pepp") == "05/17/25 vs Pepp"


def test_games_for_batter_unscoped_does_not_crash_for_veteran():
    # Regression: a veteran with an empty-Date legacy composite game crashed
    # the unscoped game list at the GameLabel strftime (live-verified on the
    # committed pilot). Now it renders string labels without raising.
    g = hitting_caps.games_for_batter(VETERAN)
    assert not g.empty
    assert g["GameLabel"].map(lambda s: isinstance(s, str)).all()


def test_last_n_pas_does_not_crash_for_veteran_with_legacy_game_ids():
    # RED before the fix: last_n_pas's `all_df["GameID"]` (selected via
    # _PITCH_COLS, unfiltered) carries the same composite legacy GameIDs
    # through to `int(g)` inside the mask comprehension, crashing with the
    # identical ValueError as games_for_batter above -- CAST(...AS UNSIGNED)
    # in the ORDER BY only truncates, it doesn't protect this later int()
    # call on the raw column.
    df = hitting_caps.last_n_pas(VETERAN, 27)
    assert not df.empty


def test_last_n_pas_shape():
    df = hitting_caps.last_n_pas(WADAS, 27)
    # same column shape as a game df (goes through _finish)
    assert "PlateLocSide" in df.columns and "PAofInning" in df.columns
    # at most 27 distinct PAs
    if not df.empty:
        pas = df[["GameID", "Inning", "PAofInning"]].drop_duplicates()
        assert len(pas) <= 27


def test_compute_season_rollup_matches_current_compute():
    """_compute_season_rollup (Phase 4 rollup source) reproduces the current
    on-the-fly compute exactly, so precalc == compute is guaranteed."""
    from app.data.hitting import qab_frame, _slash_from_pas, _slash_counts
    r = hitting_caps._compute_season_rollup(WADAS)
    assert r["batter_id"] == WADAS and r["batter_name"]
    q = qab_frame(hitting_caps.season_pitches(WADAS))
    slash = _slash_from_pas(q)
    counts = _slash_counts(q)
    assert (r["ba"], r["obp"], r["slg"]) == (slash["BA"], slash["OBP"], slash["SLG"])
    assert r["qab_pct"] == (round(float(q["QAB"].sum()) / len(q), 3) if len(q) else None)
    for k in ("pa", "ab", "h", "doubles", "triples", "hr", "bb", "so"):
        assert r[k] == counts[k], k
    assert r["pa"] >= r["ab"] >= 0
    assert r["h"] >= r["doubles"] + r["triples"] + r["hr"]


def test_sidebar_stats_uses_precalc_when_present(monkeypatch):
    """When a rollup row exists, sidebar_stats returns it as a pure 1-row read
    (no season load, no live batted-ball pull) mapped to the full 7-key
    contract -- HARD-HIT%/POP-UP%/xBA now come straight off the precalc row
    itself (Task 4), not a second live compute, so this also proves the
    season-default path never touches `_live_batted_ball_kpis`."""
    from app.data import precalc
    sentinel = {"batter_id": WADAS, "batter_name": "X", "season_label": "2026",
                "qab_pct": 0.512, "ba": ".321", "obp": ".401", "slg": ".540",
                "pa": 10, "ab": 9, "h": 3, "doubles": 1, "triples": 0,
                "hr": 1, "bb": 1, "so": 2,
                "hard_hit_pct": "50.0%", "popup_pct": "20.0%", "xba": ".345"}
    monkeypatch.setattr(precalc, "read_hitting_season", lambda b, season=None: sentinel)

    def _boom(*a, **k):
        raise AssertionError("season-default path must not compute live batted-ball KPIs")
    monkeypatch.setattr(hitting_caps, "_live_batted_ball_kpis", _boom)

    sidebar = hitting_caps.sidebar_stats(WADAS)
    assert sidebar == {"qab": 0.512, "BA": ".321", "SLG": ".540", "OBP": ".401",
                        "hard_hit_pct": "50.0%", "popup_pct": "20.0%", "xba": ".345"}
    assert set(sidebar) == _SIDEBAR_KEYS
    assert hitting_caps.season_qab_rate(WADAS) == 0.512
    assert hitting_caps.slash_line(WADAS) == {"BA": ".321", "SLG": ".540", "OBP": ".401"}


def test_sidebar_stats_falls_back_when_precalc_row_missing_kpi_columns(monkeypatch):
    """A precalc row being non-None doesn't guarantee hard_hit_pct/popup_pct/
    xba are actually populated on it -- a DB restore, a fresh environment, or
    the in-flight window of a rebuild (columns added by `ensure_tables` but
    not yet repopulated by `_replace_rows`) can leave a row that exists but
    is missing/None on just these columns. sidebar_stats must detect that and
    fall back to a live batted-ball pull for the three KPIs (same as the
    row-absent case), not KeyError or silently return a None value."""
    from app.data import precalc
    partial = {"batter_id": WADAS, "batter_name": "X", "season_label": "2026",
               "qab_pct": 0.512, "ba": ".321", "obp": ".401", "slg": ".540",
               "pa": 10, "ab": 9, "h": 3, "doubles": 1, "triples": 0,
               "hr": 1, "bb": 1, "so": 2,
               "hard_hit_pct": None, "popup_pct": "20.0%", "xba": ".345"}
    monkeypatch.setattr(precalc, "read_hitting_season", lambda b, season=None: partial)

    live_sentinel = {"hard_hit_pct": "77.0%", "popup_pct": "11.0%", "xba": ".199"}
    calls = []
    monkeypatch.setattr(hitting_caps, "_live_batted_ball_kpis",
                        lambda b, s, e, ab: (calls.append((b, s, e, ab)), live_sentinel)[1])

    out = hitting_caps.sidebar_stats(WADAS)
    assert len(calls) == 1, "expected the live KPI fallback to fire exactly once"
    assert calls[0][0] == WADAS and calls[0][3] == partial["ab"]
    # The slash/QAB numbers still come from the (otherwise-valid) precalc row;
    # only the three KPIs are replaced by the live fallback's values.
    assert out == {"qab": 0.512, "BA": ".321", "SLG": ".540", "OBP": ".401",
                    **live_sentinel}


def test_sidebar_stats_live_kpis_use_monkeypatched_seams(monkeypatch):
    """A genuine SUB-RANGE selection still computes HARD-HIT%/POP-UP%/xBA
    from a live batted-ball pull with a known frame, and xBA is derived from
    a MONKEYPATCHED `xba_hit_prob_sum` seam (per the brief) so the numerator
    is deterministic and doesn't depend on the real lookup/DB. One ball is a
    sacrifice fly (an InPlay ball, but never an AB) -- it must still count
    toward hard-hit%/pop-up%'s denominators (those are batted-ball rates) but
    must be EXCLUDED from the xBA numerator population (an AB rate), per the
    final-review fix that aligns xBA's numerator with the same population
    `_slash_counts` counts into AB.

    Task 4 moved the SEASON-DEFAULT path onto the precalc row directly (see
    test_sidebar_stats_uses_precalc_when_present), so this now exercises the
    one branch that still computes these live -- a genuine sub-range -- with
    `_rollup_over` monkeypatched (instead of `precalc.read_hitting_season`,
    which the sub-range branch never calls) so `ab` is deterministic."""
    from app.data import xba as xba_mod, seasons
    rollup = {"batter_id": WADAS, "batter_name": "X",
              "qab_pct": 0.5, "ba": ".300", "obp": ".400", "slg": ".500",
              "pa": 10, "ab": 4, "h": 3, "doubles": 0, "triples": 0,
              "hr": 0, "bb": 1, "so": 2}
    monkeypatch.setattr(hitting_caps, "_rollup_over", lambda b, s, e: rollup)
    monkeypatch.setattr(hitting_caps, "games_for_batter",
                        lambda b, s, e: pd.DataFrame({"game_id": ["g1"]}))
    # 4 batted balls: EV [96, 94, 110, nan] -> hard-hit = 2/3 known-EV rows;
    # hit_type [Popup, FlyBall, Popup, GroundBall] -> popup = 2/4 (the
    # SacFly ball's Popup/EV=110 both still count in these two denominators).
    # PlayResult [Out, Single, SacFly, FieldersChoice] -> AB-qualifying =
    # Out/Single/FieldersChoice (3 rows); SacFly is excluded (starts "Sac").
    bb = pd.DataFrame({
        "exit_speed": [96.0, 94.0, 110.0, float("nan")],
        "la": [10.0, 20.0, 30.0, 40.0],
        "hit_type": ["Popup", "FlyBall", "Popup", "GroundBall"],
        "PlayResult": ["Out", "Single", "SacFly", "FieldersChoice"],
    })
    monkeypatch.setattr(hitting_caps, "bip_points", lambda b, gids: bb)
    # Content-aware xBA-numerator mock (1.0 "probability" per row PASSED IN):
    # proves the sac row was filtered out before reaching this seam, not
    # merely that a constant flowed through untouched.
    monkeypatch.setattr(xba_mod, "xba_hit_prob_sum", lambda df, lookup=None: float(len(df)))

    season = seasons.current_season()
    s, e = seasons.season_bounds(season)
    out = hitting_caps.sidebar_stats(WADAS, season, start=str(s), end=str(s))  # single-day sub-range
    assert out["hard_hit_pct"] == "66.7%"     # the sac ball's EV=110 still counts
    assert out["popup_pct"] == "50.0%"        # the sac ball's Popup still counts
    assert out["xba"] == ".750"               # numerator = 3 AB-qualifying rows / ab(4)


def test_sidebar_stats_range_equals_season_matches_rollup():
    """The default 'This Season' view (date range == season bounds) must be
    byte-identical to the season-scoped rollup -- the fast precalc path must
    not regress when the range Inputs are wired in."""
    from app.data import seasons
    season = seasons.current_season()
    s, e = seasons.season_bounds(season)
    full = hitting_caps.sidebar_stats(WADAS, season)
    ranged = hitting_caps.sidebar_stats(WADAS, season, start=str(s), end=str(e))
    assert ranged == full


def test_sidebar_stats_subrange_is_scoped():
    """A genuine sub-range (narrower than the season) computes on the fly and
    still returns the same 7-key contract without error."""
    from app.data import seasons
    season = seasons.current_season()
    s, e = seasons.season_bounds(season)
    narrow = hitting_caps.sidebar_stats(WADAS, season, start=str(s), end=str(s))
    assert set(narrow) == _SIDEBAR_KEYS
    _assert_live_kpi_shapes(narrow)


def test_sidebar_stats_subrange_matches_rollup_over():
    """The range path's slash/QAB numbers agree exactly with _rollup_over over
    the same window -- single source of truth for that math. The three live
    KPIs agree with `_live_batted_ball_kpis` computed directly over the same
    window and AB."""
    g = hitting_caps.games_for_batter(WADAS)
    start, end = str(g["game_date"].min()), str(g["game_date"].max())
    from app.data import seasons
    season = seasons.current_season()
    s_b, e_b = seasons.season_bounds(season)
    if (start, end) == (s_b, e_b):
        import pytest
        pytest.skip("fixture's full game span equals the season bounds; not a sub-range")
    out = hitting_caps.sidebar_stats(WADAS, season, start=start, end=end)
    r = hitting_caps._rollup_over(WADAS, start, end)
    assert {k: out[k] for k in ("qab", "BA", "SLG", "OBP")} == {
        "qab": r["qab_pct"], "BA": r["ba"], "SLG": r["slg"], "OBP": r["obp"]}
    live = hitting_caps._live_batted_ball_kpis(WADAS, start, end, r["ab"])
    assert {k: out[k] for k in ("hard_hit_pct", "popup_pct", "xba")} == live


def test_compute_season_rollup_uses_rollup_over():
    """_compute_season_rollup is now a thin wrapper over _rollup_over
    (slash/QAB) PLUS `_live_batted_ball_kpis` (the three batted-ball KPIs,
    Task 4) with the season's bounds -- pin down the delegation so the paths
    can't drift."""
    from app.data import seasons
    season = seasons.current_season()
    s, e = seasons.season_bounds(season)
    direct = hitting_caps._rollup_over(WADAS, s, e)
    live = hitting_caps._live_batted_ball_kpis(WADAS, s, e, direct["ab"])
    via_season = hitting_caps._compute_season_rollup(WADAS, season)
    assert via_season == {**direct, **live, "season_label": season}


def test_compute_season_rollup_includes_batted_ball_kpis(monkeypatch):
    """The precalc rollup dict must carry hard_hit_pct/popup_pct/xba so
    rebuild_hitting can persist them -- previously these were always
    recomputed live even on the season-default path."""
    from app.data import xba as xba_mod
    # 2 batted balls: EV [96, 80] -> hard-hit = 1/2 known-EV rows;
    # hit_type [LineDrive, Popup] -> popup = 1/2.
    bb = pd.DataFrame({
        "exit_speed": [96.0, 80.0],
        "la": [10.0, 20.0],
        "hit_type": ["LineDrive", "Popup"],
        "PlayResult": ["Single", "Out"],
    })
    monkeypatch.setattr(hitting_caps, "games_for_batter",
                        lambda b, s, e: pd.DataFrame({"game_id": ["g1"]}))
    monkeypatch.setattr(hitting_caps, "bip_points", lambda b, gids: bb)
    monkeypatch.setattr(xba_mod, "xba_hit_prob_sum", lambda df, lookup=None: 1.0)

    r = hitting_caps._compute_season_rollup(WADAS)
    assert {"hard_hit_pct", "popup_pct", "xba"} <= set(r)
    _assert_live_kpi_shapes(r)
    assert r["hard_hit_pct"] == "50.0%"
    assert r["popup_pct"] == "50.0%"


def test_sidebar_stats_falls_back_to_compute_when_missing(monkeypatch):
    """With no rollup row, the reads fall back to on-the-fly compute (correct,
    just slower) so correctness never depends on a rebuild having run."""
    from app.data import precalc
    monkeypatch.setattr(precalc, "read_hitting_season", lambda b, season=None: None)
    out = hitting_caps.sidebar_stats(WADAS)
    assert set(out) == _SIDEBAR_KEYS
    assert out["BA"] != "" and out["OBP"] != ""
    _assert_live_kpi_shapes(out)
    # matches the compute path directly
    comp = hitting_caps._compute_season_rollup(WADAS)
    assert {k: out[k] for k in ("qab", "BA", "SLG", "OBP")} == {
        "qab": comp["qab_pct"], "BA": comp["ba"],
        "SLG": comp["slg"], "OBP": comp["obp"]}
