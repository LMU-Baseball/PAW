"""Catcher pitch-level data access on CAPS GAMES (replaces catching.py's
warehouse reads for the QUERY layer only). Transforms are imported from
`app.data.catching` UNCHANGED -- they consume snake_case fact-style columns,
so `_CATCHER_SELECT` aliases GAMES's CamelCase columns to those exact names.

Catcher identity = RAW `GAMES.CatcherId` (== a player's trackman_id), unlike
the warehouse's surrogate catcher_id. LMU catchers: rows where
PitcherTeam='LOY_LIO' (the catcher is on the pitching team -- same rule as
the oracle). `app.data.catching` remains the parity oracle (see
tests/test_catching_caps.py) until Phase 3 removes its warehouse queries.
"""
from __future__ import annotations

import pandas as pd

from app.data import pitching_caps
from app.data.pitching_caps import _NUMERIC_GAME_ID_CLAUSE
from app.data.cache import cached
from app.db import query_df
from app.data import called_strike as _cs

LMU_TEAM_ID = 78  # GAMES.HomeTeamForeignID/AwayTeamForeignID for LMU.
LMU_PITCHER_TEAM = "LOY_LIO"  # GAMES.PitcherTeam code for LMU (catcher is on the pitching team).

# GAMES CamelCase -> the exact snake_case names app.data.catching's transforms
# read, so those transforms run unchanged over a GAMES-sourced frame.
# `catcher_id` carries the RAW id -- the transforms only ever read it, never
# map it. `game_date` (aliased from Date) is read by caught_stealing_trend.
_CATCHER_SELECT = """
    PlateLocSide AS plate_loc_side, PlateLocHeight AS plate_loc_height,
    TaggedPitchType AS tagged_pitch_type, PitchCall AS pitch_call,
    BatterSide AS batter_side, PitcherThrows AS pitcher_throws,
    PlayResult AS play_result, PopTime AS pop_time, ExchangeTime AS exchange_time,
    ThrowSpeed AS throw_speed, CatcherId AS catcher_id, GameID AS game_id,
    Date AS game_date, Inning AS inning, Pitcher AS pitcher_name
"""


def _in_clause(ids) -> tuple[str, dict]:
    """Build a parameterized `IN (...)` fragment + params dict for a list of ids."""
    ph = ", ".join(f":id{i}" for i in range(len(ids)))
    return ph, {f"id{i}": int(v) for i, v in enumerate(ids)}


@cached
def _sibling_catcher_ids(catcher_id) -> list[int]:
    """All LMU GAMES.CatcherId values sharing this id's Catcher name."""
    name = query_df(
        "SELECT Catcher FROM GAMES WHERE CatcherId = :c AND PitcherTeam = :t LIMIT 1",
        {"c": int(catcher_id), "t": LMU_PITCHER_TEAM},
    )
    if name.empty:
        return [int(catcher_id)]
    ids = query_df(
        "SELECT DISTINCT CatcherId FROM GAMES WHERE Catcher = :n AND PitcherTeam = :t "
        "AND CatcherId IS NOT NULL",
        {"n": str(name.iloc[0]["Catcher"]), "t": LMU_PITCHER_TEAM},
    )
    return [int(x) for x in ids["CatcherId"]] or [int(catcher_id)]


@cached
def game_pitches_for(game_id, catcher_id) -> pd.DataFrame:
    """A catcher's pitches in a game, unioning split Trackman ids (sibling union)."""
    ph, idp = _in_clause(_sibling_catcher_ids(catcher_id))
    # GameID is an opaque TEXT key (numeric surrogate for warehouse-backfilled
    # games, composite string like "20250517-704EddieDField-1" for legacy/cron
    # games), so it is passed through as a string -- never int()'d.
    idp["g"] = str(game_id)
    return query_df(
        f"SELECT {_CATCHER_SELECT} FROM GAMES WHERE GameID = :g AND CatcherId IN ({ph}) "
        f"ORDER BY PitchNo",
        idp,
    )


@cached
def range_pitches_for(catcher_id, start, end) -> pd.DataFrame:
    """All of a catcher's pitches across in-range games (sibling-id union).

    Guarded by `_NUMERIC_GAME_ID_CLAUSE` so a custom pre-2025 range can't pull
    in pre-CAPS-migration composite-GameID scrimmage rows, mirroring
    pitching_caps.range_pitches_for.
    """
    ph, idp = _in_clause(_sibling_catcher_ids(catcher_id))
    idp["start"] = str(start)
    idp["end"] = str(end)
    return query_df(
        f"SELECT {_CATCHER_SELECT} FROM GAMES WHERE CatcherId IN ({ph}) "
        f"AND Date BETWEEN :start AND :end AND {_NUMERIC_GAME_ID_CLAUSE} "
        f"ORDER BY GameID, PitchNo",
        idp,
    )


def game_pitches_season(catcher_id) -> pd.DataFrame:
    """All season pitches for a catcher (sibling-id union), numeric-GameID guarded."""
    ph, idp = _in_clause(_sibling_catcher_ids(catcher_id))
    return query_df(
        f"SELECT {_CATCHER_SELECT} FROM GAMES WHERE CatcherId IN ({ph}) "
        f"AND {_NUMERIC_GAME_ID_CLAUSE} ORDER BY GameID, PitchNo",
        idp,
    )


def game_context(game_id) -> dict:
    """Reuse pitching_caps's game context (already on GAMES)."""
    return pitching_caps.game_context(game_id)


# ======================= IDENTITY + ROSTER ==================================
#
# Catcher identity here is RAW GAMES.CatcherId (== a player's trackman_id),
# unlike catching.py's warehouse surrogate catcher_id. GAMES.Catcher is
# verified live as "Last, First" (e.g. "Lyall, Jake") -- the SAME format
# catching.catcher_name already builds from tm_player, so (unlike the
# pitching slice's First/Last reorder) catcher_name here reads GAMES.Catcher
# as-is, with no reformatting.

@cached
def lmu_catchers(season=None, start=None, end=None) -> pd.DataFrame:
    """One row per LMU catcher (name deduped; canonical id = most-tracked id),
    scoped to the given academic-year season (default = current_season()).

    Season date-bounds (not a numeric-GameID filter, and no ~12-month recent
    window) do the scoping now, so legacy composite-GameID seasons are listable
    too -- picking a PAST season from the dropdown surfaces that season's
    catchers, whose games are ALL composite-GameID and were previously hidden.
    The COUNT(*) DESC dedup tiebreak is computed over the season's rows only.
    Mirrors hitting_caps.lmu_hitters(season) exactly.

    When both `start` and `end` are given, they replace the season's date
    bounds (the coach's date-range dropdown nests inside the season, so this
    narrows the roster to catchers with data in that window).

    At the season level (no start/end override), also unions in
    `app.data.lmu_roster` placeholder rows (negative CatcherId) for any
    rostered catcher with zero GAMES rows yet this season. A ranged call
    never gets placeholders -- it's explicitly asking "who has DATA in this
    window", which a data-less placeholder can never answer yes to.
    """
    from app.data import seasons
    season = season or seasons.current_season()
    s, e = seasons.season_bounds(season)
    ranged = start is not None and end is not None
    if ranged:
        s, e = str(start), str(end)
    df = query_df(
        f"""
        SELECT CatcherId, Catcher FROM (
          SELECT CatcherId, Catcher,
                 ROW_NUMBER() OVER (PARTITION BY Catcher
                                    ORDER BY COUNT(*) DESC, CatcherId) AS rn
            FROM GAMES
           WHERE PitcherTeam = :team AND CatcherId IS NOT NULL
             AND Date BETWEEN :s AND :e
           GROUP BY CatcherId, Catcher
        ) t WHERE rn = 1 ORDER BY Catcher
        """,
        {"team": LMU_PITCHER_TEAM, "s": s, "e": e},
    )
    if not df.empty:
        df["CatcherId"] = df["CatcherId"].astype(int)
    if not ranged:
        from app.data import lmu_roster
        df = lmu_roster.union_with_roster(df, season, ("catcher",), "CatcherId", "Catcher")
    return df


def catcher_name(catcher_id) -> str:
    """"Last, First" straight from GAMES.Catcher -- matches
    catching.catcher_name's format exactly (also "Last, First", built from
    tm_player there), so no reordering is needed (unlike pitcher_name)."""
    df = query_df(
        "SELECT Catcher FROM GAMES WHERE CatcherId = :c LIMIT 1",
        {"c": int(catcher_id)},
    )
    if df.empty:
        return str(catcher_id)
    return str(df.iloc[0]["Catcher"])


def catcher_tm_id_for(catcher_id):
    """Identity: GAMES.CatcherId already IS the raw trackman id. Kept for API
    compat with the report/dashboard/video's role-gating code."""
    return int(catcher_id)


@cached
def catcher_profile(catcher_id) -> dict:
    """Name + position 'C' + jersey/photo (roster_media, by raw id directly --
    no catcher_tm_id_for mapping needed, unlike the oracle)."""
    from app.data import roster_media
    name = catcher_name(catcher_id)
    media = roster_media.player_media(int(catcher_id))
    return {"name": name, "class_year": "", "position": "C",
            "throws": "", "jersey": media.get("jersey", ""),
            "photo": media.get("photo_url", "")}


@cached
def games_for_catcher(catcher_id, start=None, end=None) -> pd.DataFrame:
    """A catcher's games, newest first. GameLabel = 'YYYY-MM-DD vs/@ OPP'.
    Optional start/end (inclusive) bound game_date. Sibling-id union, matching
    catching.games_for_catcher's shape/format exactly.

    GameID is treated as an OPAQUE STRING (no numeric-only guard, no int cast),
    so legacy composite-GameID games (and future cron-loaded ones) appear too.
    Scoping is by Date only; sort is by Date desc with a GameID-string desc
    tiebreak for same-date doubleheaders (deterministic). Mirrors
    hitting_caps.games_for_batter.
    """
    ph, idp = _in_clause(_sibling_catcher_ids(catcher_id))
    date_clause = ""
    if start is not None and end is not None:
        date_clause = " AND Date BETWEEN :start AND :end"
        idp["start"] = str(start)
        idp["end"] = str(end)
    df = query_df(
        f"""
        SELECT DISTINCT GameID AS game_id, Date AS game_date,
               HomeTeam AS home_team, AwayTeam AS away_team,
               HomeTeamForeignID AS home_team_id
          FROM GAMES
         WHERE CatcherId IN ({ph}){date_clause}
        """,
        idp,
    )
    if df.empty:
        return pd.DataFrame(columns=["game_id", "game_date", "GameLabel"])
    df["game_id"] = df["game_id"].astype(str)
    df = df.sort_values(["game_date", "game_id"], ascending=[False, False]).reset_index(drop=True)
    lmu_home = df["home_team_id"] == LMU_TEAM_ID
    opp = df["away_team"].where(lmu_home, df["home_team"])
    loc = pd.Series("vs", index=df.index).where(lmu_home, "@")
    df["GameLabel"] = (df["game_date"].astype(str) + " " + loc + " " + opp.fillna("?"))
    return df[["game_id", "game_date", "GameLabel"]].reset_index(drop=True)


# ============================ SEASON TILES ===================================

def _resolve_season_window(season, start, end) -> tuple[str, str]:
    """Resolve a (season, start, end) triple to a concrete [start, end] date
    window: `season`'s bounds by default, or the caller's `start`/`end`
    sub-range when both are given and differ from the season's own bounds.

    Extracted from `framing_season_tiles` and `slaa_season_tiles`, which
    used to duplicate this branch verbatim -- a duplication that already
    caused one real bug (`slaa_season_tiles` originally shipped without it
    and returned all-dashes on default page load, since `range_pitches_for`
    got the literal string 'None' for start/end). Both now share this
    helper instead."""
    from app.data import seasons
    season = season or seasons.current_season()
    if start and end:
        s_b, e_b = seasons.season_bounds(season)
        return (str(start), str(end)) if (str(start) != s_b or str(end) != e_b) else (s_b, e_b)
    return seasons.season_bounds(season)

def _rollup_over(catcher_id, start, end) -> dict:
    """The catching framing rollup (games, pitches, net strikes, steal%) for one
    catcher over an arbitrary [start, end] date window, as a single SQL
    aggregate over GAMES (sibling-id union). Since the 2026-08-12 sidebar
    redesign `framing_season_tiles` no longer reads it (see its docstring), and
    the catching precalc rollup was retired 2026-08-13, so it now backs only
    `_compute_season_rollup` and its tests."""
    from app.data.catching import _pct
    cid = int(catcher_id)
    ph, idp = _in_clause(_sibling_catcher_ids(cid))
    idp["s"] = start; idp["e"] = end
    df = query_df(
        f"""
        SELECT COUNT(DISTINCT GameID) AS games,
               COUNT(*) AS pitches,
               SUM(PitchCall='StrikeCalled'
                   AND NOT (ABS(PlateLocSide*12) <= 10
                            AND ABS(PlateLocHeight*12 - 30) <= 13)) AS stolen,
               SUM(PitchCall='BallCalled'
                   AND (ABS(PlateLocSide*12) <= 10
                        AND ABS(PlateLocHeight*12 - 30) <= 13)) AS lost,
               SUM(PlateLocSide IS NOT NULL
                   AND PlateLocHeight IS NOT NULL) AS valid_loc
          FROM GAMES
         WHERE CatcherId IN ({ph}) AND Date BETWEEN :s AND :e
        """,
        idp,
    )
    tiles = {"games": "—", "pitches": "—", "net_strikes": "—", "steal_pct": "—"}
    if not df.empty:
        r = df.iloc[0]
        stolen = int(r["stolen"] or 0)
        lost = int(r["lost"] or 0)
        valid_loc = int(r["valid_loc"] or 0)
        steal = _pct(lost, valid_loc)
        tiles = {
            "games": str(int(r["games"] or 0)),
            "pitches": str(int(r["pitches"] or 0)),
            "net_strikes": str(stolen - lost),
            "steal_pct": "—" if steal is None else f"{steal}%",
        }
    return {"catcher_id": cid, "catcher_name": catcher_name(cid), **tiles}


def _compute_season_rollup(catcher_id, season=None) -> dict:
    """Catching season rollup: the PRECALC row (games, pitches, net strikes,
    steal%) plus catcher_id/name. Thin wrapper over `_rollup_over` with the
    season's date bounds. (Was the catching precalc source; that rollup was
    retired 2026-08-13 -- unrelated to the sidebar tiles, see
    `framing_season_tiles`.)

    Scoped to the academic-year `season` (default current_season()) via
    Date-bounds -- which for the current season equals the old numeric-GameID
    guard (that season is the numeric-backfilled one) but also lets a PAST
    season's composite-GameID rows aggregate when the Season dropdown selects
    it."""
    from app.data import seasons
    season = season or seasons.current_season()
    s, e = seasons.season_bounds(season)
    return {**_rollup_over(catcher_id, s, e), "season_label": season}


def framing_season_tiles(catcher_id, season=None, start=None, end=None) -> dict:
    """Season sidebar tiles: GAMES, STRIKES (framing strikes gained), STRIKES
    LOST, STEAL% (caught-stealing %).

    All four are computed FRESH from a single `range_pitches_for` pull over
    the window (the season's bounds by default, or the caller's `start`/`end`
    sub-range) -- one DB round trip feeds every tile, no precalc read:
      - GAMES        = distinct game_id count in the pull
      - STRIKES      = out-of-zone called strikes ("Stolen Strike" in
                        `catching.add_framing_cols`'s CallType -- the SAME
                        pandas framing-box logic the Framing tab uses, reused
                        here rather than re-deriving the box test in SQL)
      - STRIKES LOST = in-zone called balls ("Lost Strike")
      - STEAL%       = `caught_stealing_summary`'s cs_pct (caught / attempts)
                        on the SAME dataframe -- no second pull

    2026-08-12 fix-round-1: an earlier version of this tile row tried to keep
    reading GAMES/STRIKES/STRIKES-LOST off the precalc fast path by
    repurposing the `pitches`/`net_strikes` precalc columns' values in place.
    That's infeasible without a schema change: the old precalc only ever
    stored `pitches` (total pitch count) and `net_strikes` (stolen - lost),
    and `stolen`/`lost` individually can't be recovered from `net = stolen -
    lost` alone. So the precalc fast path is no longer used here at all;
    `_rollup_over`/`_compute_season_rollup`/the precalc table are UNCHANGED
    from before this task and remain in use only by `flask rebuild-precalc`.
    Empty-pull semantics match the existing "—" no-data convention used
    everywhere else in this dict."""
    from app.data.catching import add_framing_cols, caught_stealing_summary
    window = _resolve_season_window(season, start, end)
    df = range_pitches_for(catcher_id, *window)
    if df.empty:
        games = strikes = strikes_lost = "—"
    else:
        games = str(df["game_id"].nunique())
        f = add_framing_cols(df)
        f = f[f["plate_loc_side"].notna() & f["plate_loc_height"].notna()]
        strikes = str(int((f["CallType"] == "Stolen Strike").sum()))
        strikes_lost = str(int((f["CallType"] == "Lost Strike").sum()))
    cs_pct = caught_stealing_summary(df)["cs_pct"]
    return {
        "games": games,
        "strikes": strikes,
        "strikes_lost": strikes_lost,
        "cs_pct": "—" if cs_pct is None else f"{cs_pct}%",
    }


# SL+ is a ratio and is meaningless on a small denominator. Measured against
# the live data: LMU has 22,577 taken pitches across 24 catchers, so regular
# starters clear 100 within a handful of games while one-game cameo lines --
# exactly the noise this floor suppresses -- do not.
SL_PLUS_MIN_TAKEN = 100


def slaa_summary(df, *, lookup=None) -> dict:
    """SLAA / SL+ over a catcher's pitches.

    SLAA = actual called strikes - expected, in units of strikes: 0 is
    average, +12 means twelve strikes gained beyond what an average receiver
    gets on those same pitches. SL+ = 100 * actual / expected (100 = average,
    higher is better), suppressed to None below SL_PLUS_MIN_TAKEN because a
    ratio on a small denominator will be believed and should not be.

    Note: LMU's pitches are ~40% of `called_strike`'s training population
    (spec Sec.2: 22,577 of 56,537 taken pitches), so an LMU catcher is
    partly benchmarked against his own team's pitches rather than a fully
    independent baseline -- SLAA/SL+ magnitudes are somewhat attenuated
    toward the neutral average as a result.

    `df` needs `plate_loc_side`, `plate_loc_height`, `pitch_call` -- i.e. the
    shape `range_pitches_for` already returns.

    Taken pitches with a missing `plate_loc_side`/`plate_loc_height` are
    excluded from `taken`, mirroring `called_strike._raw_taken_pitches()`'s
    own training-data convention -- a pitch that can't be placed on the plate
    can't be meaningfully scored by a location-conditioned model either.
    """
    empty = {"taken": 0, "actual": 0, "expected": 0.0, "slaa": 0.0, "sl_plus": None}
    if df is None or df.empty:
        return empty
    taken = df[_cs.is_taken(df)]
    taken = taken[taken["plate_loc_side"].notna() & taken["plate_loc_height"].notna()]
    if taken.empty:
        return empty

    actual = int(_cs.is_called_strike(taken).sum())
    expected = float(_cs.expected_called_strikes(taken, lookup=lookup).sum())
    n = int(len(taken))
    sl_plus = None
    if n >= SL_PLUS_MIN_TAKEN and expected > 0:
        sl_plus = round(100.0 * actual / expected, 1)
    return {
        "taken": n,
        "actual": actual,
        "expected": round(expected, 1),
        "slaa": round(actual - expected, 1),
        "sl_plus": sl_plus,
    }


def _compute_slaa_season_rollup(catcher_id, season=None, *, lookup=None) -> dict:
    """The SLAA/SL+ season rollup for one catcher, computed from raw CAPS --
    the precalc-bound counterpart to `slaa_season_tiles`. Thin wrapper over
    `slaa_summary` with the season's resolved date window; no metric is
    redefined here.

    `precalc.rebuild_catching` writes this dict to
    `precalc_catching_player_season`; `slaa_season_tiles` reads it back
    (with this function as the compute fallback) for the season-default
    view. `lookup=` is exposed for DB-free tests; real callers omit it.
    """
    from app.data import seasons
    season = season or seasons.current_season()
    s, e = seasons.season_bounds(season)
    df = range_pitches_for(int(catcher_id), s, e)
    summary = slaa_summary(df, lookup=lookup)
    return {
        "catcher_id": int(catcher_id),
        "catcher_name": catcher_name(catcher_id),
        "slaa": summary["slaa"],
        "sl_plus": summary["sl_plus"],
        "taken": summary["taken"],
        "season_label": season,
    }


def slaa_season_tiles(catcher_id, season=None, start=None, end=None) -> dict:
    """Display-ready SLAA / SL+ / taken-pitch count for the sidebar.

    Mirrors `framing_season_tiles`' scoping so date-range selection behaves
    identically. For the season-default view (no sub-range, or a sub-range
    equal to the season's own bounds), reads the precalc rollup -- falling
    back to a live compute when the row is absent (pre-rebuild, unbuilt
    catcher, or table not yet created) OR present but missing `taken`/`slaa`
    (a DB restore, a fresh environment, or the in-flight window of a rebuild
    can leave a row that exists but isn't actually populated on these
    columns yet) -- so correctness never depends on a rebuild having run.
    `sl_plus` is NOT part of that guard: None is a legitimate value for it
    (too few taken pitches to trust the ratio, per `slaa_summary`), not a
    landmine. A genuine sub-range always computes live. Returns strings; "—"
    where a value is unavailable.
    """
    from app.data import seasons, precalc
    tiles = {"slaa": "—", "sl_plus": "—", "taken": "—"}
    if catcher_id is None:
        return tiles
    resolved_season = season or seasons.current_season()
    s_b, e_b = seasons.season_bounds(resolved_season)
    is_season_default = not (start and end) or (str(start) == s_b and str(end) == e_b)
    if is_season_default:
        row = precalc.read_catching_season(int(catcher_id), resolved_season)
        if row is not None and not pd.isna(row.get("taken")) and not pd.isna(row.get("slaa")):
            tiles["taken"] = str(row["taken"])
            tiles["slaa"] = f"{row['slaa']:+.1f}"
            tiles["sl_plus"] = "—" if row["sl_plus"] is None else f"{row['sl_plus']:.0f}"
            return tiles
    window = _resolve_season_window(season, start, end)
    df = range_pitches_for(int(catcher_id), *window)
    if df is None or df.empty:
        return tiles
    s = slaa_summary(df)
    tiles["taken"] = str(s["taken"])
    # Signed, because "+8" and "-8" mean opposite things and a bare "8" is
    # ambiguous at a glance on a tile.
    tiles["slaa"] = f"{s['slaa']:+.1f}"
    tiles["sl_plus"] = "—" if s["sl_plus"] is None else f"{s['sl_plus']:.0f}"
    return tiles
