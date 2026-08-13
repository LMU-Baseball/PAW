"""Hitting data layer on CAPS GAMES (replaces hitting_wh's warehouse reads).

GAMES stores columns under the legacy names the app/data/hitting.py transforms
expect, so no aliasing is needed -- SELECT the columns and hand to _finish.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from app.db import query_df
from app.data.hitting import (
    _finish, _in_clause, _roster_lookup, _BIP_COLS,   # pure/param helpers (moved from hitting_wh in Phase 3)
    _HITS, _AB_OUTS,   # AB-qualifying PlayResult sets -- mirrored for the xBA numerator filter
)
from app.data.hitting import qab_frame, _slash_from_pas, _slash_counts, _fmt_avg
from app.data.roster_media import player_media
from app.data.cache import cached

LMU_BATTER_TEAM = "LOY_LIO"
LMU_TEAM_ID = 78

# GAMES columns the transforms consume (already correctly named).
_PITCH_COLS = (
    "PlateLocSide, PlateLocHeight, PitchCall, PlayResult, KorBB, TaggedHitType, "
    "TaggedPitchType, ExitSpeed, Distance, Bearing, HangTime, Inning, PAofInning, "
    "PitchofPA, PitchNo, Balls, Strikes, RunsScored, OutsOnPlay, BatterSide, "
    "Pitcher, GameID, Angle"
)

@cached
def _sibling_ids(batter_id):
    name = query_df(
        "SELECT Batter FROM GAMES WHERE BatterId = :b AND BatterTeam = :t LIMIT 1",
        {"b": int(batter_id), "t": LMU_BATTER_TEAM})
    if name.empty:
        return [int(batter_id)]
    ids = query_df(
        "SELECT DISTINCT BatterId FROM GAMES WHERE Batter = :n AND BatterTeam = :t "
        "AND BatterId IS NOT NULL",
        {"n": str(name.iloc[0]["Batter"]), "t": LMU_BATTER_TEAM})
    return [int(x) for x in ids["BatterId"]] or [int(batter_id)]

@cached
def game_pitches(game_id, batter_id):
    ph, idp = _in_clause(_sibling_ids(batter_id))
    df = query_df(
        f"SELECT {_PITCH_COLS} FROM GAMES WHERE GameID = :g AND BatterId IN ({ph}) "
        f"ORDER BY PitchNo", {"g": str(game_id), **idp})
    return _finish(df)

@cached
def season_pitches(batter_id, season=None):
    """Pitches for the batter within an academic-year season (default =
    current_season()). Season date-bounds (Aug 1 -> Jul 31) replace the old
    trailing-12-month window, so any season -- including legacy composite-GameID
    ones -- loads, and the sidebar rescopes when the Season dropdown changes."""
    from app.data import seasons
    s, e = seasons.season_bounds(season or seasons.current_season())
    ph, idp = _in_clause(_sibling_ids(batter_id))
    idp["s"] = s; idp["e"] = e
    df = query_df(
        f"SELECT {_PITCH_COLS} FROM GAMES WHERE BatterId IN ({ph}) "
        f"AND Date BETWEEN :s AND :e "
        f"ORDER BY GameID, PitchNo", idp)
    return _finish(df)

@cached
def range_pitches(batter_id, start, end):
    ph, idp = _in_clause(_sibling_ids(batter_id))
    idp["start"] = str(start); idp["end"] = str(end)
    df = query_df(
        f"SELECT {_PITCH_COLS} FROM GAMES WHERE BatterId IN ({ph}) "
        f"AND Date BETWEEN :start AND :end ORDER BY GameID, PitchNo", idp)
    return _finish(df)


def _game_label(game_date, loc, opp) -> str:
    """Dropdown label for one game: "MM/DD/YY vs Opp".

    Some legacy composite-GameID games carry an empty/unparseable Date (the old
    numeric-GameID guard used to exclude them; the opaque-GameID contract lets
    them through). pd.to_datetime(errors="coerce") -> NaT for those, and
    NaT.strftime raises -- so a NaT date drops the date prefix instead of
    crashing the whole game list.
    """
    ts = pd.to_datetime(game_date, errors="coerce")
    ds = "" if pd.isna(ts) else ts.strftime("%m/%d/%y")
    return f"{ds} {loc} {opp}".strip()


@cached
def games_for_batter(batter_id, start=None, end=None):
    """A batter's games, newest first.

    GameID is treated as an OPAQUE STRING (no numeric-only guard, no int cast),
    so legacy composite-GameID games (and future cron-loaded ones) appear too.
    Scoping is by Date only; sort is by Date desc with a GameID-string desc
    tiebreak for same-date doubleheaders (deterministic).
    """
    ph, idp = _in_clause(_sibling_ids(batter_id))
    date_clause = ""
    if start is not None and end is not None:
        date_clause = " AND Date BETWEEN :start AND :end"; idp["start"]=str(start); idp["end"]=str(end)
    df = query_df(
        f"SELECT DISTINCT GameID AS game_id, Date AS game_date, HomeTeam, AwayTeam, "
        f"HomeTeamForeignID FROM GAMES WHERE BatterId IN ({ph}){date_clause}", idp)
    if df.empty:
        return pd.DataFrame(columns=["game_id", "game_date", "GameLabel"])
    df["game_id"] = df["game_id"].astype(str)
    df = df.sort_values(["game_date", "game_id"], ascending=[False, False]).reset_index(drop=True)
    lmu_home = df["HomeTeamForeignID"] == LMU_TEAM_ID
    df["loc"] = lmu_home.map({True: "vs", False: "@"})
    df["opp"] = df["AwayTeam"].where(lmu_home, df["HomeTeam"])
    df["GameLabel"] = [_game_label(d, l, o)
                       for d, l, o in zip(df["game_date"], df["loc"], df["opp"])]
    return df[["game_id", "game_date", "GameLabel"]]


@cached
def scoreboard(game_id):
    df = query_df(
        "SELECT Date, HomeTeam, AwayTeam, HomeTeamForeignID, GameType "
        "FROM GAMES WHERE GameID = :g LIMIT 1", {"g": str(game_id)})
    if df.empty:
        return {"date": "", "loc": "", "opp": "", "game_type": ""}
    r = df.iloc[0]
    lmu_home = r["HomeTeamForeignID"] == LMU_TEAM_ID
    opp = r["AwayTeam"] if lmu_home else r["HomeTeam"]
    return {"date": pd.to_datetime(r["Date"]).strftime("%m/%d/%y"),
            "loc": "vs" if lmu_home else "@",
            "opp": "" if pd.isna(opp) else str(opp),
            "game_type": "" if pd.isna(r["GameType"]) else str(r["GameType"])}


def _season_rollup(batter_id, season=None) -> dict:
    """Read the precalc season rollup (1-row); fall back to on-the-fly compute
    when the row is absent (pre-rebuild, unbuilt player, or table not yet
    created) so correctness never depends on a rebuild having run.

    The precalc table holds one row per (batter, season), so ANY season is a
    ~0.2s single-row read; the compute fallback covers a pre-rebuild / unbuilt
    (batter, season)."""
    from app.data import seasons, precalc  # lazy: precalc imports hitting_caps
    season = season or seasons.current_season()
    row = precalc.read_hitting_season(int(batter_id), season)
    return row if row is not None else _compute_season_rollup(batter_id, season)


def season_qab_rate(batter_id, season=None) -> float | None:
    return _season_rollup(batter_id, season)["qab_pct"]


def slash_line(batter_id, season=None) -> dict:
    r = _season_rollup(batter_id, season)
    return {"BA": r["ba"], "SLG": r["slg"], "OBP": r["obp"]}


def _rollup_over(batter_id, start, end) -> dict:
    """The hitting rollup for one batter over an arbitrary [start, end] date
    window, computed from raw CAPS. Single source of truth for the slash/QAB
    math: runs the same PA-frame chain (`range_pitches` -> `qab_frame`) then the
    shared `_slash_counts`/`_slash_from_pas`. `_compute_season_rollup` calls this
    with a season's bounds; `sidebar_stats`'s range path calls it with the
    caller's date-range bounds directly -- same function, different window.
    """
    bid = int(batter_id)
    meta = query_df(
        "SELECT Batter FROM GAMES WHERE BatterId = :b AND Date BETWEEN :s AND :e "
        "ORDER BY Date DESC LIMIT 1", {"b": bid, "s": start, "e": end})
    name = "" if meta.empty or pd.isna(meta.iloc[0]["Batter"]) else str(meta.iloc[0]["Batter"])

    df = range_pitches(bid, start, end)
    q = qab_frame(df)
    counts = _slash_counts(q)
    slash = _slash_from_pas(q)
    total = len(q)
    qab_pct = round(float(q["QAB"].sum()) / total, 3) if total else None
    return {
        "batter_id": bid, "batter_name": name,
        "qab_pct": qab_pct, "ba": slash["BA"], "obp": slash["OBP"], "slg": slash["SLG"],
        "pa": counts["pa"], "ab": counts["ab"], "h": counts["h"],
        "doubles": counts["doubles"], "triples": counts["triples"], "hr": counts["hr"],
        "bb": counts["bb"], "so": counts["so"],
    }


def _compute_season_rollup(batter_id, season=None) -> dict:
    """The hitting season rollup for one batter, computed from raw CAPS.

    Thin wrapper over `_rollup_over` with the season's date bounds -- the single
    source of truth for the slash/QAB math lives there now. `precalc.
    rebuild_hitting` writes this dict to `precalc_hitting_player_season`;
    `sidebar_stats` et al. read it back (with this function as the compute
    fallback). No metric is redefined here.

    Scoped to the academic-year `season` (default current_season()); the name is
    read from that season's rows and `season_label` stores the season label.
    """
    from app.data import seasons
    season = season or seasons.current_season()
    s, e = seasons.season_bounds(season)
    return {**_rollup_over(batter_id, s, e), "season_label": season}


def _fmt_pct(x) -> str:
    """Percent display string matching the existing QAB% tile's own inline
    formatting (`app.dashboards.hitting.layout.sidebar`'s
    `f"{round(qab * 100, 1)}%"`), e.g. 0.452 -> "45.2%"; "-" when undefined."""
    return f"{round(x * 100, 1)}%" if x is not None else "—"


def _ab_qualifying_mask(play_result: pd.Series) -> pd.Series:
    """Boolean mask selecting the AB-qualifying rows of a batted-ball
    PlayResult column -- i.e. the same population `_slash_counts` counts
    into AB, restricted to `PitchCall == 'InPlay'` rows (a batted ball is
    never a Walk/HBP/Strikeout PA, so of `_slash_counts`'s branches only
    "Sac* is excluded" and "unknown PlayResult is excluded" apply here):
    a PlayResult starting with "Sac" (sac fly/bunt) is excluded -- it's an
    InPlay ball but not an AB; a hit (`_HITS`) or a non-hit AB-out
    (`_AB_OUTS`) counts; anything else (undefined/NaN PlayResult) is
    excluded, mirroring `_slash_counts`'s "undefined/incomplete PA — not
    counted" fallthrough. Used ONLY to align the xBA numerator's population
    with the AB denominator -- hard_hit_pct/popup_pct correctly keep the
    full InPlay batted-ball set as their own denominator.
    """
    is_sac = play_result.astype(str).str.startswith("Sac")
    return ~is_sac & (play_result.isin(_HITS) | play_result.isin(_AB_OUTS))


def _live_batted_ball_kpis(batter_id, start, end, ab) -> dict:
    """HARD-HIT%, POP-UP%, xBA computed FRESH (no precalc) over the batter's
    InPlay batted balls in [start, end] -- the three new sidebar tiles (Task
    2 of the hitting-KPIs work). `ab` is the AB the caller already computed
    via its slash-count rollup (`_rollup_over`/`_season_rollup`, both of which
    carry an "ab" key), passed in so this doesn't redo the PA/AB compute --
    just one batted-ball pull (`bip_points`, via the range's game ids) plus
    the Task-1 xBA lookup.

    hard_hit_pct = count(ExitSpeed >= 95) / count(ExitSpeed notna) among the
    range's InPlay batted balls (null-EV rows excluded from the denominator).
    popup_pct = count(hit_type == 'Popup') / count(all InPlay batted balls).
    Both of these are batted-ball RATES, so their denominator is correctly
    the full InPlay batted-ball set (sacrifices and undefined PlayResults
    included) -- unlike xBA below, they are NOT AB rates.

    xba = sum(p_hit over the AB-QUALIFYING batted balls) / AB, formatted
    exactly like the BA tile (`_fmt_avg`) so it reads as directly
    comparable; AB == 0 renders the same "-" placeholder BA uses. The
    numerator is filtered to `_ab_qualifying_mask` (the same population
    `_slash_counts` counts into AB) rather than summed over every InPlay
    ball -- otherwise a sac fly/bunt (an InPlay ball, but never an AB)
    would inflate the numerator without a matching AB, biasing xBA high
    enough to exceed 1.000 in small samples.
    """
    from app.data import xba as xba_model
    games = games_for_batter(batter_id, start, end)
    gids = games["game_id"].tolist() if not games.empty else []
    bb = bip_points(batter_id, gids) if gids else pd.DataFrame(columns=_BIP_COLS)

    ev = bb["exit_speed"] if not bb.empty else pd.Series(dtype=float)
    ev_known = ev.dropna()
    hard_hit = (float((ev_known >= 95).sum()) / len(ev_known)) if len(ev_known) else None

    n_bip = len(bb)
    popup = (float((bb["hit_type"] == "Popup").sum()) / n_bip) if n_bip else None

    xba_bb = bb[_ab_qualifying_mask(bb["PlayResult"])] if n_bip else bb
    prob_sum = xba_model.xba_hit_prob_sum(xba_bb) if len(xba_bb) else 0.0
    xba_val = (prob_sum / ab) if ab else None

    return {"hard_hit_pct": _fmt_pct(hard_hit), "popup_pct": _fmt_pct(popup),
            "xba": _fmt_avg(xba_val)}


def sidebar_stats(batter_id, season=None, start=None, end=None) -> dict:
    """QAB% + slash line + HARD-HIT%/POP-UP%/xBA, scoped to a date range.

    When `start`/`end` are omitted, or given but equal to `season`'s bounds
    (the default "This Season" view), read the precalc 1-row rollup as before
    (fixes the profiled 3.2s full-season double-load; compute fallback when the
    rollup row is absent) -- this fast path is unchanged for qab/BA/SLG/OBP. A
    genuine sub-range (the coach narrowed the calendar/preset) computes on the
    fly via `_rollup_over` so the sidebar KPIs track the selected date range.

    HARD-HIT%/POP-UP%/xBA are always computed fresh (mirrors the catcher
    STEAL% approach) on BOTH paths -- they are not part of the precalc
    schema, so the season-default view now does one extra live batted-ball
    pull; the four existing tiles keep their precalc fast path untouched."""
    from app.data import seasons
    if start and end:
        s_b, e_b = seasons.season_bounds(season or seasons.current_season())
        if str(start) != s_b or str(end) != e_b:
            r = _rollup_over(batter_id, start, end)
            live = _live_batted_ball_kpis(batter_id, start, end, r["ab"])
            return {"qab": r["qab_pct"], "BA": r["ba"], "SLG": r["slg"], "OBP": r["obp"],
                    **live}
    r = _season_rollup(batter_id, season)
    s_b, e_b = seasons.season_bounds(season or seasons.current_season())
    live = _live_batted_ball_kpis(batter_id, s_b, e_b, r["ab"])
    return {"qab": r["qab_pct"], "BA": r["ba"], "SLG": r["slg"], "OBP": r["obp"], **live}


@cached
def player_profile(batter_id):
    blank = {"name": "", "bats": "", "class_year": "", "position": "",
             "photo": "", "jersey": ""}
    df = query_df(
        "SELECT Batter, BatterSide FROM GAMES WHERE BatterId = :b "
        "ORDER BY Date DESC LIMIT 1", {"b": int(batter_id)})
    if df.empty:
        return blank
    name = "" if pd.isna(df.iloc[0]["Batter"]) else str(df.iloc[0]["Batter"])
    bats = "" if pd.isna(df.iloc[0]["BatterSide"]) else str(df.iloc[0]["BatterSide"])
    cy, pos = _roster_lookup(name)
    media = player_media(int(batter_id))  # scraped headshot + jersey (blanks if none)
    return {"name": name, "bats": bats, "class_year": cy, "position": pos,
            "photo": media["photo_url"], "jersey": media["jersey"]}


@cached
def lmu_hitters(season=None, start=None, end=None) -> pd.DataFrame:
    """One row per LMU hitter (name deduped; canonical id = most-tracked id),
    scoped to the given academic-year season (default = current_season()).

    Season date-bounds (not a numeric-GameID filter) do the scoping now, so
    legacy composite-GameID seasons are listable too. The COUNT(*) DESC dedup
    tiebreak is computed over the season's rows only.

    When both `start` and `end` are given, they replace the season's date
    bounds (the coach's date-range dropdown nests inside the season, so this
    narrows the roster to hitters with data in that window -- e.g. the
    Hitter dropdown refresh on `*-daterange` change).
    """
    from app.data import seasons
    s, e = seasons.season_bounds(season or seasons.current_season())
    if start is not None and end is not None:
        s, e = str(start), str(end)
    df = query_df(
        f"""
        SELECT Batter, BatterId FROM (
          SELECT Batter, BatterId,
                 ROW_NUMBER() OVER (PARTITION BY Batter
                                    ORDER BY COUNT(*) DESC, BatterId) AS rn
            FROM GAMES
           WHERE BatterTeam = :team AND BatterId IS NOT NULL
             AND Date BETWEEN :s AND :e
           GROUP BY Batter, BatterId
        ) t WHERE rn = 1 ORDER BY Batter
        """,
        {"team": LMU_BATTER_TEAM, "s": s, "e": e},
    )
    if not df.empty:
        df["BatterId"] = df["BatterId"].astype(int)
    return df


@cached
def bip_points(batter_id, game_id) -> pd.DataFrame:
    """Balls-in-play landing (x,y) + launch-radial (rx,ry) for a batter and
    game(s). `game_id` is an opaque string id (or a list of them). Empty
    full-column frame when none.

    Mirrors hitting_wh.wh_bip_points's spray/radial math exactly. Unlike the
    pitch-level transforms (_finish), which NaN out Angle, GAMES stores a real
    launch angle there -- so this reads Angle directly instead of routing
    through _finish.
    """
    gids = [str(g) for g in (game_id if isinstance(game_id, (list, tuple)) else [game_id])]
    if not gids:
        return pd.DataFrame(columns=_BIP_COLS)
    ph, idp = _in_clause(_sibling_ids(batter_id))
    gph = ", ".join(f":g{i}" for i in range(len(gids)))
    idp.update({f"g{i}": g for i, g in enumerate(gids)})
    df = query_df(
        f"""
        SELECT TaggedHitType AS hit_type, ExitSpeed AS exit_speed, Angle AS la,
               Bearing AS bearing, Distance AS distance,
               PlayResult, PitchCall, TaggedPitchType AS PitchType, Pitcher,
               Balls, Strikes, GameID, Inning, PAofInning
          FROM GAMES
         WHERE GameID IN ({gph}) AND BatterId IN ({ph})
           AND PitchCall = 'InPlay'
         ORDER BY GameID, PitchNo
        """,
        idp,
    )
    if df.empty:
        return pd.DataFrame(columns=_BIP_COLS)
    df["hit_type"] = df["hit_type"].fillna("Undefined").replace("", "Undefined")
    br = np.radians(df["bearing"].astype(float))
    df["x"] = np.sin(br) * df["distance"].astype(float)
    df["y"] = np.cos(br) * df["distance"].astype(float)
    la = np.radians(df["la"].astype(float))
    ev = df["exit_speed"].astype(float)
    df["rx"] = ev / 120.0 * np.cos(la)
    df["ry"] = ev / 120.0 * np.sin(la)
    df["Count"] = (df["Balls"].astype("Int64").astype(str) + "-"
                   + df["Strikes"].astype("Int64").astype(str))
    undefined = df["PlayResult"].isna() | df["PlayResult"].isin(["Undefined"])
    df["Result"] = np.where(undefined, df["PitchCall"],
                            df["hit_type"] + " - " + df["PlayResult"].astype(str))
    return df[_BIP_COLS]


@cached
def last_n_pas(batter_id, n: int = 27) -> pd.DataFrame:
    """The batter's most recent `n` plate appearances (across all games),
    returned through _finish so the shared hitting transforms apply.

    GameID is an opaque text key (numeric surrogate for warehouse-backfilled
    games, composite string like "20241023-LoyolaMarymount-Private-1" for
    legacy/cron games), so it is NOT sorted numerically. The most-recent-PA
    window sorts by Date DESC (the real chronology), then GameID DESC as a
    lexicographic tiebreak within a date (composite ids are date-prefixed, so
    this stays chronological), then Inning/PAofInning by their numeric values
    (CAST ... AS UNSIGNED) so extra innings rank correctly ("10" after "2").
    The (GameID, Inning, PAofInning) key is matched as strings on both sides,
    so composite-GameID veterans no longer crash.
    """
    ph, idp = _in_clause(_sibling_ids(batter_id))
    pas = query_df(
        f"""
        SELECT d.GameID, d.Inning, d.PAofInning FROM (
          SELECT DISTINCT GameID, Inning, PAofInning, Date
            FROM GAMES
           WHERE BatterId IN ({ph})
        ) d
        ORDER BY d.Date DESC, d.GameID DESC,
                 CAST(d.Inning AS UNSIGNED) DESC, CAST(d.PAofInning AS UNSIGNED) DESC
        LIMIT {int(n)}
        """,
        idp,
    )
    all_df = _finish(query_df(
        f"SELECT {_PITCH_COLS} FROM GAMES WHERE BatterId IN ({ph}) "
        f"ORDER BY GameID, PitchNo", idp,
    ))
    if all_df.empty or pas.empty:
        return all_df
    keys = set(zip(pas["GameID"].astype(str), pas["Inning"].astype(str),
                   pas["PAofInning"].astype(str)))
    mask = [(str(g), str(i), str(p)) in keys
            for g, i, p in zip(all_df["GameID"], all_df["Inning"], all_df["PAofInning"])]
    return all_df[mask].reset_index(drop=True)
