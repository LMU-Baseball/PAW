import math

import pandas as pd
from app.db import query_df
from app.data import hitting_caps
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


def test_sidebar_stats_matches_qab_and_slash():
    qab = hitting_caps.season_qab_rate(WADAS)
    slash = hitting_caps.slash_line(WADAS)
    sidebar = hitting_caps.sidebar_stats(WADAS)
    assert set(sidebar) == {"qab", "BA", "SLG", "OBP"}
    assert sidebar["qab"] == qab
    assert sidebar["BA"] == slash["BA"]
    assert sidebar["SLG"] == slash["SLG"]
    assert sidebar["OBP"] == slash["OBP"]


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
    (no season load) mapped to the {qab,BA,SLG,OBP} contract."""
    from app.data import precalc
    sentinel = {"batter_id": WADAS, "batter_name": "X", "season_label": "2026",
                "qab_pct": 0.512, "ba": ".321", "obp": ".401", "slg": ".540",
                "pa": 10, "ab": 9, "h": 3, "doubles": 1, "triples": 0,
                "hr": 1, "bb": 1, "so": 2}
    monkeypatch.setattr(precalc, "read_hitting_season", lambda b: sentinel)
    assert hitting_caps.sidebar_stats(WADAS) == {
        "qab": 0.512, "BA": ".321", "SLG": ".540", "OBP": ".401"}
    assert hitting_caps.season_qab_rate(WADAS) == 0.512
    assert hitting_caps.slash_line(WADAS) == {"BA": ".321", "SLG": ".540", "OBP": ".401"}


def test_sidebar_stats_falls_back_to_compute_when_missing(monkeypatch):
    """With no rollup row, the reads fall back to on-the-fly compute (correct,
    just slower) so correctness never depends on a rebuild having run."""
    from app.data import precalc
    monkeypatch.setattr(precalc, "read_hitting_season", lambda b: None)
    out = hitting_caps.sidebar_stats(WADAS)
    assert set(out) == {"qab", "BA", "SLG", "OBP"}
    assert out["BA"] != "" and out["OBP"] != ""
    # matches the compute path directly
    comp = hitting_caps._compute_season_rollup(WADAS)
    assert out == {"qab": comp["qab_pct"], "BA": comp["ba"],
                   "SLG": comp["slg"], "OBP": comp["obp"]}
