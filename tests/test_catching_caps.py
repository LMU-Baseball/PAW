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
    monkeypatch.setattr(precalc, "read_catching_season", lambda c: sentinel)
    assert catching_caps.framing_season_tiles(RAW_CID) == {
        "games": "12", "pitches": "800", "net_strikes": "15", "steal_pct": "4.2%"}


def test_framing_season_tiles_falls_back_to_compute_when_missing(monkeypatch):
    from app.data import precalc
    monkeypatch.setattr(precalc, "read_catching_season", lambda c: None)
    out = catching_caps.framing_season_tiles(RAW_CID)
    assert set(out) == {"games", "pitches", "net_strikes", "steal_pct"}
