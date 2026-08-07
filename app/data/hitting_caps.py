"""Hitting data layer on CAPS GAMES (replaces hitting_wh's warehouse reads).

GAMES stores columns under the legacy names the app/data/hitting.py transforms
expect, so no aliasing is needed -- SELECT the columns and hand to _finish.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from app.db import query_df
from app.data.hitting import _finish, _in_clause, _roster_lookup, _BIP_COLS   # pure/param helpers (moved from hitting_wh in Phase 3)
from app.data.hitting import qab_frame, _slash_from_pas, _slash_counts
from app.data.roster_media import player_media

LMU_BATTER_TEAM = "LOY_LIO"
LMU_TEAM_ID = 78

# Shared trailing-~12-month window (anchored to the newest LMU GAMES date, not
# today's date -- see lmu_hitters docstring for why). Reused by lmu_hitters
# (which hitter names to list) and season_pitches (which pitches count toward
# that hitter's season stats) so both are scoped consistently.
_RECENT_WINDOW_CLAUSE = """Date >= (
               SELECT DATE_FORMAT(
                        DATE_SUB(STR_TO_DATE(MAX(Date), '%Y-%m-%d'), INTERVAL 12 MONTH),
                        '%Y-%m-%d')
                 FROM GAMES
                WHERE BatterTeam = :team AND Date REGEXP '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
             )"""

# GAMES columns the transforms consume (already correctly named).
_PITCH_COLS = (
    "PlateLocSide, PlateLocHeight, PitchCall, PlayResult, KorBB, TaggedHitType, "
    "TaggedPitchType, ExitSpeed, Distance, Bearing, HangTime, Inning, PAofInning, "
    "PitchofPA, PitchNo, Balls, Strikes, RunsScored, OutsOnPlay, BatterSide, "
    "Pitcher, GameID, Angle"
)

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

def game_pitches(game_id, batter_id):
    ph, idp = _in_clause(_sibling_ids(batter_id))
    df = query_df(
        f"SELECT {_PITCH_COLS} FROM GAMES WHERE GameID = :g AND BatterId IN ({ph}) "
        f"ORDER BY PitchNo", {"g": int(game_id), **idp})
    return _finish(df)

def season_pitches(batter_id):
    """Season pitches, windowed to the trailing ~12 months (see
    _RECENT_WINDOW_CLAUSE) rather than a batter's full GAMES history."""
    ph, idp = _in_clause(_sibling_ids(batter_id))
    idp["team"] = LMU_BATTER_TEAM
    df = query_df(
        f"SELECT {_PITCH_COLS} FROM GAMES WHERE BatterId IN ({ph}) "
        f"AND {_RECENT_WINDOW_CLAUSE} "
        f"ORDER BY GameID, PitchNo", idp)
    return _finish(df)

def range_pitches(batter_id, start, end):
    ph, idp = _in_clause(_sibling_ids(batter_id))
    idp["start"] = str(start); idp["end"] = str(end)
    df = query_df(
        f"SELECT {_PITCH_COLS} FROM GAMES WHERE BatterId IN ({ph}) "
        f"AND Date BETWEEN :start AND :end ORDER BY GameID, PitchNo", idp)
    return _finish(df)


def games_for_batter(batter_id, start=None, end=None):
    """A batter's games, newest first.

    Restricted to numeric GameIDs (see the REGEXP filter below, mirroring
    pitching_caps.games_for_pitcher): GAMES also holds pre-CAPS-migration
    scrimmage rows under composite string GameIDs (e.g.
    "20241023-LoyolaMarymount-Private-1") for RETURNING VETERAN hitters who
    have both current/backfilled numeric-GameID games and legacy pre-2025
    games in GAMES. Excluding those composite ids keeps the int-cast below
    safe -- without the filter, a real veteran hitter (verified live:
    BatterId 801956, "Danos, Luca") crashes here with
    `ValueError: invalid literal for int() with base 10`.
    """
    ph, idp = _in_clause(_sibling_ids(batter_id))
    date_clause = ""
    if start is not None and end is not None:
        date_clause = " AND Date BETWEEN :start AND :end"; idp["start"]=str(start); idp["end"]=str(end)
    df = query_df(
        f"SELECT DISTINCT GameID AS game_id, Date AS game_date, HomeTeam, AwayTeam, "
        f"HomeTeamForeignID FROM GAMES WHERE BatterId IN ({ph}) "
        f"AND GameID REGEXP '^[0-9]+$'{date_clause}", idp)
    if df.empty:
        return pd.DataFrame(columns=["game_id", "game_date", "GameLabel"])
    df["game_id"] = df["game_id"].astype(int)
    # GameID is stored as text, so sort numerically in pandas rather than via SQL
    # ORDER BY (which would sort lexicographically). Same-date ties (doubleheaders)
    # break by game_id DESC: a deliberate, deterministic tiebreak -- the warehouse
    # oracle (wh_games_for_batter) has no secondary ORDER BY at all, so its
    # same-date order is DB-planner incidental/non-deterministic, not a contract
    # we should copy.
    df = df.sort_values(["game_date", "game_id"], ascending=[False, False]).reset_index(drop=True)
    lmu_home = df["HomeTeamForeignID"] == LMU_TEAM_ID
    df["loc"] = lmu_home.map({True: "vs", False: "@"})
    df["opp"] = df["AwayTeam"].where(lmu_home, df["HomeTeam"])
    df["GameLabel"] = [f"{pd.to_datetime(d).strftime('%m/%d/%y')} {l} {o}"
                       for d, l, o in zip(df["game_date"], df["loc"], df["opp"])]
    return df[["game_id", "game_date", "GameLabel"]]


def scoreboard(game_id):
    df = query_df(
        "SELECT Date, HomeTeam, AwayTeam, HomeTeamForeignID, GameType "
        "FROM GAMES WHERE GameID = :g LIMIT 1", {"g": int(game_id)})
    if df.empty:
        return {"date": "", "loc": "", "opp": "", "game_type": ""}
    r = df.iloc[0]
    lmu_home = r["HomeTeamForeignID"] == LMU_TEAM_ID
    opp = r["AwayTeam"] if lmu_home else r["HomeTeam"]
    return {"date": pd.to_datetime(r["Date"]).strftime("%m/%d/%y"),
            "loc": "vs" if lmu_home else "@",
            "opp": "" if pd.isna(opp) else str(opp),
            "game_type": "" if pd.isna(r["GameType"]) else str(r["GameType"])}


def _season_rollup(batter_id) -> dict:
    """Phase 4: read the precalc season rollup (1-row); fall back to on-the-fly
    compute when the row is absent (pre-rebuild, unbuilt player, or table not
    yet created) so correctness never depends on a rebuild having run."""
    from app.data import precalc  # lazy: precalc imports hitting_caps for rebuild
    row = precalc.read_hitting_season(int(batter_id))
    return row if row is not None else _compute_season_rollup(batter_id)


def season_qab_rate(batter_id) -> float | None:
    return _season_rollup(batter_id)["qab_pct"]


def slash_line(batter_id) -> dict:
    r = _season_rollup(batter_id)
    return {"BA": r["ba"], "SLG": r["slg"], "OBP": r["obp"]}


def _compute_season_rollup(batter_id) -> dict:
    """The Phase 4 hitting season rollup for one batter, computed from raw CAPS.

    Single source of truth for the rollup: runs the SAME season load + PA-frame
    the sidebar/summary use (`season_pitches` -> `qab_frame`), then the shared
    `_slash_counts`/`_slash_from_pas`. `precalc.rebuild_hitting` writes this dict
    to `precalc_hitting_player_season`; `sidebar_stats` et al. read it back (with
    this function as the compute fallback). No metric is redefined here.
    """
    bid = int(batter_id)
    meta = query_df(
        "SELECT Batter, Date FROM GAMES WHERE BatterId = :b "
        "AND GameID REGEXP '^[0-9]+$' ORDER BY Date DESC LIMIT 1", {"b": bid})
    name = "" if meta.empty or pd.isna(meta.iloc[0]["Batter"]) else str(meta.iloc[0]["Batter"])
    season_label = ""
    if not meta.empty and not pd.isna(meta.iloc[0]["Date"]):
        season_label = str(pd.to_datetime(meta.iloc[0]["Date"]).year)

    df = season_pitches(bid)
    q = qab_frame(df)
    counts = _slash_counts(q)
    slash = _slash_from_pas(q)
    total = len(q)
    qab_pct = round(float(q["QAB"].sum()) / total, 3) if total else None
    return {
        "batter_id": bid, "batter_name": name, "season_label": season_label,
        "qab_pct": qab_pct, "ba": slash["BA"], "obp": slash["OBP"], "slg": slash["SLG"],
        "pa": counts["pa"], "ab": counts["ab"], "h": counts["h"],
        "doubles": counts["doubles"], "triples": counts["triples"], "hr": counts["hr"],
        "bb": counts["bb"], "so": counts["so"],
    }


def sidebar_stats(batter_id):
    """QAB% + slash line as a single precalc 1-row read (fixes the profiled 3.2s
    full-season double-load); compute fallback when the rollup row is absent."""
    r = _season_rollup(batter_id)
    return {"qab": r["qab_pct"], "BA": r["ba"], "SLG": r["slg"], "OBP": r["obp"]}


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


def lmu_hitters() -> pd.DataFrame:
    """One row per LMU hitter (name deduped; canonical id = most-tracked id),
    scoped to a ~12-month recent-data window.

    Mirrors hitting_wh.wh_lmu_hitters's dedup logic, but over GAMES/BatterId
    instead of fact_tm_game_pitch/batter_tm_id -- with one deliberate
    addition: GAMES holds the FULL CAPS history back to 2022, so an unscoped
    version of this query would surface 50+ retired alumni the warehouse
    (current-season-only) never has. The window is anchored to the newest
    GAMES date, not to today's date -- during the offseason "today" would put
    the anchor after the season ends and empty the whole list.

    The COUNT(*) DESC dedup tiebreak is computed over the WINDOWED rows only,
    which incidentally fixes a canonical-id quirk found in the unscoped
    version: two current hitters (Dunn, JD and Casale, Johnny) have MORE
    total career pitches under an old pre-2025 BatterId than under their
    current one, so the unscoped tiebreak picked the stale id. Windowing
    removes the old id's rows from the count entirely.

    Also guarded by the numeric-GameID filter (mirroring games_for_batter's
    inline REGEXP form): a hitter can have in-window rows that are ALL legacy
    composite-GameID (pre-CAPS-migration) games -- such a "ghost" would be
    listed here but every numeric-GameID-guarded data function
    (games_for_batter, season_pitches's downstream consumers, etc.) returns
    empty for them, producing a blank dashboard. Restricting to numeric-
    GameID rows keeps the dropdown consistent with what the data functions
    can actually show.
    """
    df = query_df(
        f"""
        SELECT Batter, BatterId FROM (
          SELECT Batter, BatterId,
                 ROW_NUMBER() OVER (PARTITION BY Batter
                                    ORDER BY COUNT(*) DESC, BatterId) AS rn
            FROM GAMES
           WHERE BatterTeam = :team AND BatterId IS NOT NULL
             AND {_RECENT_WINDOW_CLAUSE} AND GameID REGEXP '^[0-9]+$'
           GROUP BY Batter, BatterId
        ) t WHERE rn = 1 ORDER BY Batter
        """,
        {"team": LMU_BATTER_TEAM},
    )
    if not df.empty:
        df["BatterId"] = df["BatterId"].astype(int)
    return df


def bip_points(batter_id, game_id) -> pd.DataFrame:
    """Balls-in-play landing (x,y) + launch-radial (rx,ry) for a batter and
    game(s). `game_id` is an int or a list. Empty full-column frame when none.

    Mirrors hitting_wh.wh_bip_points's spray/radial math exactly. Unlike the
    pitch-level transforms (_finish), which NaN out Angle, GAMES stores a real
    launch angle there -- so this reads Angle directly instead of routing
    through _finish.
    """
    gids = [int(g) for g in (game_id if isinstance(game_id, (list, tuple)) else [game_id])]
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


def last_n_pas(batter_id, n: int = 27) -> pd.DataFrame:
    """The batter's most recent `n` plate appearances (across all games),
    returned through _finish so the shared hitting transforms apply.

    GameID, Inning, and PAofInning are all stored as text in GAMES, so the
    most-recent-PA window is sorted by their numeric values (CAST ... AS
    UNSIGNED), not the lexicographic default -- lexicographic order would
    mis-rank extra innings (e.g. "10" before "2"). Mirrors wh_last_n_pas's
    date/game/inning/PA ordering over the warehouse's integer columns.

    Both queries below are restricted to numeric GameIDs (see the REGEXP
    filter, mirroring games_for_batter/pitching_caps.games_for_pitcher):
    GAMES also holds pre-CAPS-migration scrimmage rows under composite
    string GameIDs (e.g. "20241023-LoyolaMarymount-Private-1") for RETURNING
    VETERAN hitters. Without this filter the `int(g)` calls below crash for
    such a hitter -- CAST(... AS UNSIGNED) in the ORDER BY merely truncates
    the composite ids rather than crashing, but the raw (uncast) GameID
    still flows through to `pas`/`all_df` and into the mask comprehension,
    where the plain `int()` call raises ValueError (verified live: BatterId
    801956, "Danos, Luca").
    """
    ph, idp = _in_clause(_sibling_ids(batter_id))
    pas = query_df(
        f"""
        SELECT d.GameID, d.Inning, d.PAofInning FROM (
          SELECT DISTINCT GameID, Inning, PAofInning, Date
            FROM GAMES
           WHERE BatterId IN ({ph}) AND GameID REGEXP '^[0-9]+$'
        ) d
        ORDER BY d.Date DESC, CAST(d.GameID AS UNSIGNED) DESC,
                 CAST(d.Inning AS UNSIGNED) DESC, CAST(d.PAofInning AS UNSIGNED) DESC
        LIMIT {int(n)}
        """,
        idp,
    )
    all_df = _finish(query_df(
        f"SELECT {_PITCH_COLS} FROM GAMES WHERE BatterId IN ({ph}) "
        f"AND GameID REGEXP '^[0-9]+$' "
        f"ORDER BY GameID, PitchNo", idp,
    ))
    if all_df.empty or pas.empty:
        return all_df
    keys = set(zip(pas["GameID"].astype(int), pas["Inning"].astype(int),
                   pas["PAofInning"].astype(int)))
    mask = [(int(g), int(i), int(p)) in keys
            for g, i, p in zip(all_df["GameID"], all_df["Inning"], all_df["PAofInning"])]
    return all_df[mask].reset_index(drop=True)
