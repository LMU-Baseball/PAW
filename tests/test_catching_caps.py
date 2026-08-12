import pandas as pd
import pytest

from app.data import catching, catching_caps, pitching_caps

# Lyall, Jake: raw trackman id 832465, game_id 68 (2026-03-24, LMU @ UCLA).
# GAMES.CatcherId IS the raw trackman id (no warehouse surrogate mapping in the
# CAPS era). This game has 187 pitches and 4 caught-stealing events, making the
# caught-stealing checks meaningful. GAMES also carries a sibling raw CatcherId
# (10305395) for "Lyall, Jake" under legacy composite-string GameIDs
# (pre-CAPS-migration scrimmages) -- irrelevant to this single-game fixture but
# exercises the sibling-union machinery for whole-career queries.
RAW_CID = 832465
GAME_ID = 68


def test_sibling_catcher_ids_includes_raw_id():
    ids = catching_caps._sibling_catcher_ids(RAW_CID)
    assert RAW_CID in ids


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
# GAMES.Catcher is verified live as "Last, First" (e.g. "Lyall, Jake").

def test_catcher_tm_id_for_is_identity():
    assert catching_caps.catcher_tm_id_for(RAW_CID) == RAW_CID


def test_lmu_catchers_columns():
    df = catching_caps.lmu_catchers()
    assert list(df.columns) == ["CatcherId", "Catcher"]


# ------------------------- season-scoping + opaque-GameID --------------------
#
# Post-refactor lmu_catchers is scoped by SEASON DATE-BOUNDS, not by the old
# date-only _RECENT_WINDOW + numeric-GameID guard. A catcher whose only
# appearances are legacy composite-string GameIDs (pre-CAPS-migration) is now
# EXCLUDED from the current-season roster because those games fall in an
# earlier season -- NOT because a numeric-GameID guard hides them. And under
# the opaque-GameID contract, games_for_catcher now SURFACES those composite
# games (the exact opposite of the pre-refactor numeric-only behavior), so
# picking such a catcher in their own past season yields real data.

def test_lmu_catchers_excludes_out_of_season_legacy_catcher():
    # CatcherId 801901 ("Ayers, Robbie") has 13,398 GAMES rows (max Date
    # 2025-05-16), ALL under legacy composite GameIDs -- an earlier season than
    # current_season(), verified live. He must NOT appear in the current
    # season's roster.
    GHOST_ID = 801901
    ids = catching_caps.lmu_catchers()["CatcherId"].values
    assert GHOST_ID not in ids
    # Opaque-GameID contract: games_for_catcher NO LONGER filters to numeric
    # surrogate ids, so his legacy composite-string games now come back (this
    # was the blocker being fixed -- the frame used to be empty for him). The
    # game_id column is opaque strings, NOT int-castable.
    g = catching_caps.games_for_catcher(GHOST_ID)
    assert not g.empty
    with pytest.raises((ValueError, TypeError)):
        g["game_id"].astype(int)


# ------------------- caught-stealing Inn/Pitcher regression -----------------
#
# _CATCHER_SELECT didn't alias GAMES.Inning/GAMES.Pitcher, but the caught-
# stealing tab renders per-attempt "Inn"/"Pitcher" columns via
# ev.get("inning")/ev.get("pitcher_name"). The caps SELECT dropped them
# silently (no crash -- .get() on a missing column just renders blank).

def test_caught_stealing_events_have_inning_and_pitcher_name():
    new = catching_caps.game_pitches_for(GAME_ID, RAW_CID)
    ev = catching.caught_stealing_events(new)
    assert not ev.empty  # fixture game has 4 CS attempts
    assert "inning" in ev.columns
    assert "pitcher_name" in ev.columns
    assert ev["inning"].notna().any()
    assert ev["pitcher_name"].notna().any()


def test_games_for_catcher_has_no_numeric_game_id_guard():
    # Cheaper, DB-independent companion to the regression test above: pin down
    # the mechanism of the opaque-GameID refactor -- the numeric-GameID guard
    # (_NUMERIC_GAME_ID_CLAUSE / "GameID REGEXP") is GONE from games_for_catcher,
    # so games are scoped by date only and composite-id games list.
    import inspect
    src = inspect.getsource(catching_caps.games_for_catcher)
    assert "_NUMERIC_GAME_ID_CLAUSE" not in src
    assert "GameID REGEXP" not in src


def test_lmu_catchers_scopes_by_date():
    # Task 5: the Catcher dropdown on the game dashboards must narrow to
    # players with data in the selected date range (nested inside the season).
    from app.data import seasons
    season = seasons.current_season()
    s, e = seasons.season_bounds(season)
    full = set(catching_caps.lmu_catchers(season)["CatcherId"])
    ranged = set(catching_caps.lmu_catchers(season, start=str(s), end=str(e))["CatcherId"])
    assert ranged <= full
    assert ranged == full          # start/end == the season's own bounds
    empty = catching_caps.lmu_catchers(season, start="1900-01-01", end="1900-01-02")
    assert empty.empty


def test_lmu_catchers_has_no_numeric_game_id_guard_and_is_season_scoped():
    # lmu_catchers is now scoped by season date-bounds, not by the numeric-
    # GameID guard or the ~12-month recent window.
    import inspect
    src = inspect.getsource(catching_caps.lmu_catchers)
    assert "_NUMERIC_GAME_ID_CLAUSE" not in src
    assert "_RECENT_WINDOW_CLAUSE" not in src
    assert "season_bounds" in src


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


def test_framing_season_tiles_uses_precalc_when_present(monkeypatch):
    # The precalc row's `pitches`/`net_strikes` columns are repurposed (same
    # schema, no rebuild) to hold the framing STRIKES-gained/STRIKES-LOST
    # counts -- framing_season_tiles surfaces them under their new sidebar
    # names. STEAL% is no longer read off the precalc row at all (its
    # `steal_pct` column is dead going forward); it's always a fresh
    # caught-stealing computation, so an empty pitches frame here yields "—".
    from app.data import precalc
    sentinel = {"catcher_id": RAW_CID, "catcher_name": "Lyall, Jake",
                "games": "12", "pitches": "800", "net_strikes": "15",
                "steal_pct": "4.2%"}
    monkeypatch.setattr(precalc, "read_catching_season", lambda c, season=None: sentinel)
    monkeypatch.setattr(catching_caps, "range_pitches_for", lambda c, s, e: pd.DataFrame())
    assert catching_caps.framing_season_tiles(RAW_CID) == {
        "games": "12", "strikes": "800", "strikes_lost": "15", "cs_pct": "—"}


def test_framing_season_tiles_falls_back_to_compute_when_missing(monkeypatch):
    from app.data import precalc
    monkeypatch.setattr(precalc, "read_catching_season", lambda c, season=None: None)
    out = catching_caps.framing_season_tiles(RAW_CID)
    assert set(out) == {"games", "strikes", "strikes_lost", "cs_pct"}


def test_framing_season_tiles_steal_pct_is_caught_stealing_not_lost_rate(monkeypatch):
    # Coach feedback: STEAL% must be caught / attempts (caught_stealing_summary's
    # cs_pct), NOT the legacy lost/valid_loc rate that used to live on the
    # precalc row's `steal_pct` column. Pin a precalc row whose (now-repurposed
    # and now-unused) steal_pct clearly disagrees with a deliberately different,
    # mocked caught-stealing frame, and assert the tile shows the latter.
    from app.data import precalc
    sentinel = {"catcher_id": RAW_CID, "catcher_name": "Lyall, Jake",
                "games": "12", "pitches": "50", "net_strikes": "10",
                "steal_pct": "20.0%"}
    monkeypatch.setattr(precalc, "read_catching_season", lambda c, season=None: sentinel)
    # 3 caught-stealing attempts, 1 caught -> cs_pct = 33.3%, != legacy 20.0%.
    cs_df = pd.DataFrame({
        "play_result": ["CaughtStealing", "StolenBase", "StolenBase"],
        "pop_time": [2.0, None, None],
    })
    monkeypatch.setattr(catching_caps, "range_pitches_for", lambda c, s, e: cs_df)
    out = catching_caps.framing_season_tiles(RAW_CID)
    assert out == {"games": "12", "strikes": "50", "strikes_lost": "10", "cs_pct": "33.3%"}


def test_compute_season_rollup_uses_rollup_over():
    """_compute_season_rollup is now a thin wrapper over _rollup_over with the
    season's bounds -- pin down the delegation so the two paths can't drift."""
    from app.data import seasons
    season = seasons.current_season()
    s, e = seasons.season_bounds(season)
    direct = catching_caps._rollup_over(RAW_CID, s, e)
    via_season = catching_caps._compute_season_rollup(RAW_CID, season)
    assert via_season == {**direct, "season_label": season}


def test_framing_tiles_range_equals_season_matches():
    """The default 'This Season' view (date range == season bounds) must be
    byte-identical to the season-scoped tiles -- the fast precalc path must
    not regress when the range Inputs are wired in."""
    from app.data import seasons
    cid = int(catching_caps.lmu_catchers().iloc[0]["CatcherId"])
    season = seasons.current_season()
    s, e = seasons.season_bounds(season)
    assert catching_caps.framing_season_tiles(cid, season, str(s), str(e)) \
        == catching_caps.framing_season_tiles(cid, season)


def test_framing_tiles_subrange_is_scoped():
    """A genuine sub-range (narrower than the season) computes on the fly and
    still returns the same 4-key contract without error."""
    from app.data import seasons
    season = seasons.current_season()
    s, e = seasons.season_bounds(season)
    narrow = catching_caps.framing_season_tiles(RAW_CID, season, start=str(s), end=str(s))
    assert set(narrow) == {"games", "strikes", "strikes_lost", "cs_pct"}


def test_framing_tiles_subrange_matches_rollup_over():
    """The range path's numbers agree exactly with _rollup_over over the same
    window -- single source of truth for the framing-tile math."""
    g = catching_caps.games_for_catcher(RAW_CID)
    # A few legacy composite-GameID rows carry a blank Date (see games_for_catcher's
    # docstring); drop them so min/max reflect real game dates, not "".
    g = g[g["game_date"].astype(str) != ""]
    start, end = str(g["game_date"].min()), str(g["game_date"].max())
    from app.data import seasons
    season = seasons.current_season()
    s_b, e_b = seasons.season_bounds(season)
    if (start, end) == (s_b, e_b):
        pytest.skip("fixture's full game span equals the season bounds; not a sub-range")
    out = catching_caps.framing_season_tiles(RAW_CID, season, start=start, end=end)
    r = catching_caps._rollup_over(RAW_CID, start, end)
    cs = catching.caught_stealing_summary(catching_caps.range_pitches_for(RAW_CID, start, end))
    expected_cs = "—" if cs["cs_pct"] is None else f"{cs['cs_pct']}%"
    assert out == {"games": r["games"], "strikes": r["pitches"],
                   "strikes_lost": r["net_strikes"], "cs_pct": expected_cs}
