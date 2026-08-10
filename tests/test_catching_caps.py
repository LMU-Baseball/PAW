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
    from app.data import precalc
    sentinel = {"catcher_id": RAW_CID, "catcher_name": "Lyall, Jake",
                "games": "12", "pitches": "800", "net_strikes": "15",
                "steal_pct": "4.2%"}
    monkeypatch.setattr(precalc, "read_catching_season", lambda c, season=None: sentinel)
    assert catching_caps.framing_season_tiles(RAW_CID) == {
        "games": "12", "pitches": "800", "net_strikes": "15", "steal_pct": "4.2%"}


def test_framing_season_tiles_falls_back_to_compute_when_missing(monkeypatch):
    from app.data import precalc
    monkeypatch.setattr(precalc, "read_catching_season", lambda c, season=None: None)
    out = catching_caps.framing_season_tiles(RAW_CID)
    assert set(out) == {"games", "pitches", "net_strikes", "steal_pct"}
