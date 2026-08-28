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
    # Pinned to the actual latest season with real GAMES data ("2025/2026")
    # rather than current_season() (now always today's calendar season, which
    # has zero real Trackman rows yet).
    from app.data import seasons
    season = "2025/2026"
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


def test_lmu_catchers_unions_roster_placeholders(monkeypatch):
    from app.data import lmu_roster, cache
    cache.clear_all()
    monkeypatch.setattr(lmu_roster, "load_roster", lambda season: pd.DataFrame([
        {"roster_id": 9201, "first_name": "Test", "last_name": "Backstop",
         "class_year": "FR", "position": "C"},
        {"roster_id": 9202, "first_name": "Test", "last_name": "Infielder3",
         "class_year": "SO", "position": "SS"},
    ]))
    df = catching_caps.lmu_catchers("1899/1900")
    assert (df["CatcherId"] == -9201).any()
    assert not (df["CatcherId"] == -9202).any()   # non-catcher position excluded
    cache.clear_all()


def test_lmu_catchers_ranged_call_excludes_roster_placeholders(monkeypatch):
    from app.data import lmu_roster, cache
    cache.clear_all()
    monkeypatch.setattr(lmu_roster, "load_roster", lambda season: pd.DataFrame([
        {"roster_id": 9203, "first_name": "Test", "last_name": "Backstop2",
         "class_year": "FR", "position": "C"},
    ]))
    df = catching_caps.lmu_catchers("1899/1900", start="1899-08-01", end="1899-08-02")
    assert not (df["CatcherId"] == -9203).any() if not df.empty else True
    cache.clear_all()


def test_lmu_catchers_full_season_bounds_explicit_still_includes_placeholders(monkeypatch):
    # Pinning the exact bug Fix 2/3's review found: passing the season's own
    # full bounds EXPLICITLY must behave identically to no start/end at all --
    # placeholders still included.
    from app.data import lmu_roster, cache, seasons
    cache.clear_all()
    monkeypatch.setattr(lmu_roster, "load_roster", lambda season: pd.DataFrame([
        {"roster_id": 9204, "first_name": "Test", "last_name": "Backstop3",
         "class_year": "FR", "position": "C"},
    ]))
    s, e = seasons.season_bounds("1899/1900")
    df = catching_caps.lmu_catchers("1899/1900", start=s, end=e)
    assert (df["CatcherId"] == -9204).any()
    cache.clear_all()


def test_catcher_name_resolves_placeholder_via_lmu_roster(monkeypatch):
    # Fix 1: a placeholder id (negative) has zero GAMES rows, so catcher_name
    # must resolve via lmu_roster FIRST, not fall through to the raw id.
    from app.data import lmu_roster
    monkeypatch.setattr(lmu_roster, "query_df", lambda sql, params=None: pd.DataFrame(
        [{"first_name": "Test", "last_name": "Backstop4"}]))
    assert catching_caps.catcher_name(-9205) == "Backstop4, Test"


def test_catcher_name_falls_through_to_games_for_real_id(monkeypatch):
    # A real (non-negative) id must never be short-circuited by lmu_roster.
    from app.data import lmu_roster
    called = {"query_df": False}

    def fake_query_df(sql, params=None):
        called["query_df"] = True
        return pd.DataFrame(columns=["first_name", "last_name"])
    monkeypatch.setattr(lmu_roster, "query_df", fake_query_df)
    name = catching_caps.catcher_name(RAW_CID)
    assert name != str(RAW_CID)
    assert not called["query_df"]  # placeholder_name short-circuits on cid >= 0


def test_lmu_catchers_all_have_numeric_game_id_rows():
    # No-ghost property, as a single SQL set-membership check rather than N
    # per-id queries: every id lmu_catchers lists must have at least one
    # numeric-GameID GAMES row -- the exact universe games_for_catcher/
    # framing_season_tiles can actually serve.
    # Pinned to "2025/2026" (the actual latest season with real GAMES data)
    # rather than the default (current_season(), now always today's calendar
    # season, which has zero real Trackman rows yet).
    from app.db import query_df
    ids = set(catching_caps.lmu_catchers("2025/2026")["CatcherId"].astype(int))
    current_ids = set(query_df(
        "SELECT DISTINCT CatcherId FROM GAMES "
        "WHERE PitcherTeam = :t AND CatcherId IS NOT NULL "
        f"AND {catching_caps._NUMERIC_GAME_ID_CLAUSE}",
        {"t": catching_caps.LMU_PITCHER_TEAM},
    )["CatcherId"].astype(int))
    assert ids <= current_ids


def _framing_fixture_df():
    """A small mocked `range_pitches_for`-shaped frame with known framing +
    caught-stealing counts, used to pin the fresh-per-pull tile math
    (fix-round-1: framing_season_tiles no longer touches precalc at all).

    Framing rows (add_framing_cols's CallType, matching the Framing tab's own
    box test): 2 "Stolen Strike" (out-of-zone StrikeCalled, across 2 games),
    1 "Lost Strike" (in-zone BallCalled), 1 "Correct Call" (in-zone
    StrikeCalled -- not counted either way). Caught-stealing rows: 2 attempts
    (1 caught) on play_result, with null loc (irrelevant to framing).
    Distinct game_id count = 2.
    """
    return pd.DataFrame([
        {"game_id": "1", "plate_loc_side": 2.0, "plate_loc_height": 2.5,
         "tagged_pitch_type": "Fastball", "pitch_call": "StrikeCalled",
         "play_result": None, "pop_time": None},
        {"game_id": "2", "plate_loc_side": -2.0, "plate_loc_height": 2.5,
         "tagged_pitch_type": "Fastball", "pitch_call": "StrikeCalled",
         "play_result": None, "pop_time": None},
        {"game_id": "1", "plate_loc_side": 0.0, "plate_loc_height": 2.5,
         "tagged_pitch_type": "Fastball", "pitch_call": "BallCalled",
         "play_result": None, "pop_time": None},
        {"game_id": "1", "plate_loc_side": 0.0, "plate_loc_height": 2.5,
         "tagged_pitch_type": "Fastball", "pitch_call": "StrikeCalled",
         "play_result": None, "pop_time": None},
        {"game_id": "1", "plate_loc_side": None, "plate_loc_height": None,
         "tagged_pitch_type": "Fastball", "pitch_call": "InPlay",
         "play_result": "CaughtStealing", "pop_time": 2.0},
        {"game_id": "2", "plate_loc_side": None, "plate_loc_height": None,
         "tagged_pitch_type": "Fastball", "pitch_call": "InPlay",
         "play_result": "StolenBase", "pop_time": None},
    ])


def test_framing_season_tiles_computes_fresh_from_one_pull(monkeypatch):
    """GAMES/STRIKES/STRIKES_LOST/STEAL% all come off ONE `range_pitches_for`
    pull -- no precalc read at all (fix-round-1). Pin the exact tile values
    against the fixture's known framing/caught-stealing counts."""
    calls = []
    def _fake_range_pitches_for(c, s, e):
        calls.append((c, s, e))
        return _framing_fixture_df()
    monkeypatch.setattr(catching_caps, "range_pitches_for", _fake_range_pitches_for)
    out = catching_caps.framing_season_tiles(RAW_CID)
    assert out == {"games": "2", "strikes": "2", "strikes_lost": "1", "cs_pct": "50.0%"}
    assert len(calls) == 1  # exactly one pull feeds all four tiles


def test_framing_season_tiles_empty_pull_renders_no_data(monkeypatch):
    monkeypatch.setattr(catching_caps, "range_pitches_for", lambda c, s, e: pd.DataFrame())
    out = catching_caps.framing_season_tiles(RAW_CID)
    assert out == {"games": "—", "strikes": "—", "strikes_lost": "—", "cs_pct": "—"}


def test_framing_season_tiles_steal_pct_is_caught_stealing_not_lost_rate(monkeypatch):
    # Coach feedback: STEAL% must be caught / attempts (caught_stealing_summary's
    # cs_pct), NOT the legacy lost/valid_loc rate. Build a fixture where the two
    # would clearly disagree: 1 framing "Lost Strike" pitch out of 4 total pitches
    # with valid loc (legacy rate would be 25.0%), but the caught-stealing rows
    # give cs_pct = 33.3% (1 caught / 3 attempts) -- assert the tile shows the
    # caught-stealing number, not the legacy one.
    df = pd.DataFrame([
        {"game_id": "1", "plate_loc_side": 2.0, "plate_loc_height": 2.5,
         "tagged_pitch_type": "Fastball", "pitch_call": "StrikeCalled",
         "play_result": None, "pop_time": None},
        {"game_id": "1", "plate_loc_side": 0.0, "plate_loc_height": 2.5,
         "tagged_pitch_type": "Fastball", "pitch_call": "BallCalled",
         "play_result": None, "pop_time": None},
        {"game_id": "1", "plate_loc_side": 0.0, "plate_loc_height": 2.5,
         "tagged_pitch_type": "Fastball", "pitch_call": "StrikeCalled",
         "play_result": None, "pop_time": None},
        {"game_id": "1", "plate_loc_side": 0.0, "plate_loc_height": 2.5,
         "tagged_pitch_type": "Fastball", "pitch_call": "StrikeCalled",
         "play_result": None, "pop_time": None},
        {"game_id": "1", "plate_loc_side": None, "plate_loc_height": None,
         "tagged_pitch_type": "Fastball", "pitch_call": "InPlay",
         "play_result": "CaughtStealing", "pop_time": 2.0},
        {"game_id": "1", "plate_loc_side": None, "plate_loc_height": None,
         "tagged_pitch_type": "Fastball", "pitch_call": "InPlay",
         "play_result": "StolenBase", "pop_time": None},
        {"game_id": "1", "plate_loc_side": None, "plate_loc_height": None,
         "tagged_pitch_type": "Fastball", "pitch_call": "InPlay",
         "play_result": "StolenBase", "pop_time": None},
    ])
    # Sanity: the legacy (now-dead) lost/valid_loc formula would read 25.0%,
    # confirming this fixture actually distinguishes the two metrics.
    legacy = catching.framing_table(df)
    assert legacy["steal_pct"] == 25.0
    monkeypatch.setattr(catching_caps, "range_pitches_for", lambda c, s, e: df)
    out = catching_caps.framing_season_tiles(RAW_CID)
    assert out["cs_pct"] == "33.3%"
    assert out["cs_pct"] != f"{legacy['steal_pct']}%"


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
    """The fresh pandas-pull path's counts agree with the SQL box-test
    aggregate (_rollup_over, unchanged/precalc-only now) over the same
    window: GAMES matches exactly, and STRIKES - STRIKES_LOST (the net)
    matches _rollup_over's net_strikes -- both derive the stolen/lost counts
    from the identical strike-zone box rule, just in pandas vs SQL, so their
    difference (the only thing _rollup_over still exposes) must agree.

    Scoped to the CURRENT SEASON's own games (not the catcher's full,
    cross-season history): the season is fully numeric-GameID-backfilled, so
    `range_pitches_for`'s `_NUMERIC_GAME_ID_CLAUSE` guard (which `_rollup_over`
    does NOT apply) can't exclude anything here, keeping the two paths'
    universes identical -- exactly what the real date-range picker also
    guarantees (it's bounded to the season)."""
    # Pinned to "2025/2026" (the actual latest season with real GAMES data)
    # rather than current_season() (now always today's calendar season, which
    # has zero real Trackman rows yet).
    from app.data import seasons
    season = "2025/2026"
    s_b, e_b = seasons.season_bounds(season)
    g = catching_caps.games_for_catcher(RAW_CID, start=s_b, end=e_b)
    g = g[g["game_date"].astype(str) != ""]
    start, end = str(g["game_date"].min()), str(g["game_date"].max())
    if (start, end) == (s_b, e_b):
        pytest.skip("fixture's in-season game span equals the season bounds; not a sub-range")
    out = catching_caps.framing_season_tiles(RAW_CID, season, start=start, end=end)
    r = catching_caps._rollup_over(RAW_CID, start, end)
    assert out["games"] != "—"
    assert out["games"] == r["games"]
    assert int(out["strikes"]) - int(out["strikes_lost"]) == int(r["net_strikes"])
