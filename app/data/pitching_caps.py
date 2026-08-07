"""Pitcher data access on CAPS GAMES (replaces pitching.py's warehouse reads
for the QUERY layer only). Transforms + figures are imported from
`app.data.pitching` UNCHANGED -- they consume snake_case fact-style columns,
so `_PITCH_SELECT` aliases GAMES's CamelCase columns to those exact names.

Pitcher identity = RAW `GAMES.PitcherId` (== a player's trackman_id), unlike
the warehouse's surrogate pitcher_id. LMU pitchers: PitcherTeam='LOY_LIO'.
`app.data.pitching` remains the parity oracle (see tests/test_pitching_caps.py)
until Phase 3 removes its warehouse queries.
"""
from __future__ import annotations

import pandas as pd

from app.data.pitching import bb_pct, barrel_pct_ev, format_ip, k_pct
from app.db import query_df

LMU_TEAM_ID = 78  # GAMES.HomeTeamForeignID/AwayTeamForeignID for LMU.
LMU_PITCHER_TEAM = "LOY_LIO"  # GAMES.PitcherTeam code for LMU (same as the fact table's).

# GAMES also holds pre-CAPS-migration scrimmage rows under composite string
# GameIDs (e.g. "20241019-LoyolaMarymount-1") that predate the warehouse's
# synced season -- see games_for_pitcher. Restricting to numeric GameIDs
# conveniently reproduces the oracle's season boundary exactly wherever a
# query has no other date bound (verified live for season_summary/
# range_summary's whole-career branches: with this filter, totals for a real
# fixture pitcher are byte-identical to pitching.py's warehouse-scoped ones).
_NUMERIC_GAME_ID_CLAUSE = "GameID REGEXP '^[0-9]+$'"

# GAMES CamelCase -> the exact snake_case names app.data.pitching's transforms
# read, so those transforms run unchanged over a GAMES-sourced frame. Includes
# PlateLocHeight (paired with PlateLocSide) even though it isn't in the plan's
# aliasing list verbatim -- pitching.py's fig_location/fig_heatmap read
# plate_loc_height alongside plate_loc_side, and this module's loaders are the
# only place that can supply it. Also includes pitcher_team (Task 7: the
# postgame report's LMU-only defense-in-depth guard reads this column off the
# loaded pitch df) and pitcher_throws (Task 7: the report's handedness
# detection reads this when present) -- both added columns, additive-only, so
# they don't affect any existing parity assertion.
_PITCH_SELECT = """
    PitchCall AS pitch_call, RelSpeed AS rel_speed, PlateLocSide AS plate_loc_side,
    PlateLocHeight AS plate_loc_height, InducedVertBreak AS induced_vert_break,
    HorzBreak AS horz_break, VertApprAngle AS vert_appr_angle,
    TaggedHitType AS tagged_hit_type, TaggedPitchType AS tagged_pitch_type,
    AutoPitchType AS auto_pitch_type, PlayResult AS play_result, KorBB AS korbb,
    Balls AS balls, Strikes AS strikes, Inning AS inning, PAofInning AS pa_of_inning,
    PitchofPA AS pitch_of_pa, PitchNo AS pitch_no, OutsOnPlay AS outs_on_play,
    RunsScored AS runs_scored, BatterSide AS batter_side, SpinRate AS spin_rate,
    RelHeight AS rel_height, RelSide AS rel_side, Extension AS extension,
    ExitSpeed AS exit_speed, Zone AS izt_zone, GameID AS game_id,
    PitcherId AS pitcher_id, `Top.Bottom` AS top_bottom,
    PitcherTeam AS pitcher_team, PitcherThrows AS pitcher_throws
"""


def _in_clause(ids) -> tuple[str, dict]:
    """Build a parameterized `IN (...)` fragment + params dict for a list of ids."""
    ph = ", ".join(f":id{i}" for i in range(len(ids)))
    return ph, {f"id{i}": int(v) for i, v in enumerate(ids)}


def _add_batters_faced(df: pd.DataFrame) -> pd.DataFrame:
    """Synthesize `batters_faced`, the warehouse's running-PA counter.

    GAMES has no such column, but `pitching.game_overall_line` reads
    `df["batters_faced"].max()`, which is just the count of distinct PAs
    (inning, pa_of_inning) in the frame. Since a pitcher's pitches for one PA
    are contiguous in pitch order, numbering PA-groups in order of first
    appearance (pandas `ngroup(sort=False)`) gives each row its PA's ordinal
    position -- a monotonically non-decreasing running counter whose max
    equals the total distinct-PA count, exactly like the warehouse counter
    `game_overall_line` reads. Mirrors `pitching._pa_count`'s group key
    (inning, pa_of_inning only -- no game_id), so behavior matches exactly on
    the single-game frames these loaders are actually read through.
    """
    if df.empty:
        df = df.copy()
        df["batters_faced"] = pd.Series(dtype="int64")
        return df
    df = df.sort_values("pitch_no").reset_index(drop=True)
    df["batters_faced"] = df.groupby(["inning", "pa_of_inning"], sort=False).ngroup() + 1
    return df


def _sibling_pitcher_ids(pitcher_id) -> list[int]:
    """All LMU GAMES.PitcherId values sharing this id's Pitcher name."""
    name = query_df(
        "SELECT Pitcher FROM GAMES WHERE PitcherId = :p AND PitcherTeam = :t LIMIT 1",
        {"p": int(pitcher_id), "t": LMU_PITCHER_TEAM},
    )
    if name.empty:
        return [int(pitcher_id)]
    ids = query_df(
        "SELECT DISTINCT PitcherId FROM GAMES WHERE Pitcher = :n AND PitcherTeam = :t "
        "AND PitcherId IS NOT NULL",
        {"n": str(name.iloc[0]["Pitcher"]), "t": LMU_PITCHER_TEAM},
    )
    return [int(x) for x in ids["PitcherId"]] or [int(pitcher_id)]


def game_pitches(game_id, pitcher_id) -> pd.DataFrame:
    """A single raw pitcher_id's pitches in one game (no sibling union)."""
    df = query_df(
        f"SELECT {_PITCH_SELECT} FROM GAMES WHERE GameID = :g AND PitcherId = :p "
        f"ORDER BY PitchNo",
        {"g": int(game_id), "p": int(pitcher_id)},
    )
    return _add_batters_faced(df)


def game_pitches_for(game_id, pitcher_id) -> pd.DataFrame:
    """A pitcher's pitches in a game, unioning split Trackman ids (dashboard/report use)."""
    ph, idp = _in_clause(_sibling_pitcher_ids(pitcher_id))
    idp["g"] = int(game_id)
    df = query_df(
        f"SELECT {_PITCH_SELECT} FROM GAMES WHERE GameID = :g AND PitcherId IN ({ph}) "
        f"ORDER BY PitchNo",
        idp,
    )
    return _add_batters_faced(df)


def range_pitches_for(pitcher_id, start, end) -> pd.DataFrame:
    """All of a pitcher's pitches across in-range games (sibling-id union).

    Guarded by `_NUMERIC_GAME_ID_CLAUSE` so a custom pre-2025 range can't pull
    in pre-CAPS-migration composite-GameID scrimmage rows (see
    `games_for_pitcher`); in-season ranges are all-numeric and unaffected.
    """
    ph, idp = _in_clause(_sibling_pitcher_ids(pitcher_id))
    idp["start"] = str(start)
    idp["end"] = str(end)
    df = query_df(
        f"SELECT {_PITCH_SELECT} FROM GAMES WHERE PitcherId IN ({ph}) "
        f"AND Date BETWEEN :start AND :end AND {_NUMERIC_GAME_ID_CLAUSE} "
        f"ORDER BY GameID, PitchNo",
        idp,
    )
    return _add_batters_faced(df)


def _season_label(date_str) -> str:
    """'Spring 2026' / 'Fall 2025' from a GAMES.Date -- GAMES has no
    season_label column, so derive it with the same Jan-Jun/Jul-Dec half-year
    split app.dashboards.date_range.season_block uses, matching the live
    dim_tm_game.season_label format verified against the warehouse ('Fall
    2025', 'Spring 2026')."""
    if date_str is None or (isinstance(date_str, float) and pd.isna(date_str)):
        return ""
    d = pd.to_datetime(date_str)
    return f"{'Spring' if d.month <= 6 else 'Fall'} {d.year}"


def game_context(game_id) -> dict:
    dim = query_df(
        "SELECT Date, GameType, HomeTeam, AwayTeam, HomeTeamForeignID "
        "FROM GAMES WHERE GameID = :g LIMIT 1",
        {"g": int(game_id)},
    )
    if dim.empty:
        raise KeyError(f"No GAMES row for game_id={game_id}")
    row = dim.iloc[0]

    # Final score: sum RunsScored by batting half. Top => away bats, Bottom => home.
    runs = query_df(
        "SELECT `Top.Bottom` AS top_bottom, COALESCE(SUM(RunsScored), 0) AS runs "
        "FROM GAMES WHERE GameID = :g GROUP BY `Top.Bottom`",
        {"g": int(game_id)},
    ).set_index("top_bottom")["runs"].to_dict()
    away_runs = int(runs.get("Top", 0))
    home_runs = int(runs.get("Bottom", 0))

    lmu_is_home = bool(row["HomeTeamForeignID"] == LMU_TEAM_ID)
    return {
        "game_date": row["Date"],
        "season_label": _season_label(row["Date"]),
        "game_type": None if pd.isna(row["GameType"]) else row["GameType"],
        "home_team": row["HomeTeam"],
        "away_team": row["AwayTeam"],
        "lmu_runs": home_runs if lmu_is_home else away_runs,
        "opp_runs": away_runs if lmu_is_home else home_runs,
        "lmu_is_home": lmu_is_home,
    }


# ============================ VELO VIEWS ===================================
#
# The warehouse's vw_pitcher_appearance_velo aggregates AVG/MAX/MIN(rel_speed)
# + COUNT(*) per (game, pitcher) FILTERED TO TaggedPitchType IN ('Fastball',
# 'Sinker') ONLY (verified from the live view definition) -- off-speed pitches
# don't count toward "velo". vw_pitcher_recent_outings joins that to the
# active-players roster; vw_pitcher_velo_trend adds a per-pitcher,
# per-season LAG for velo_change. GAMES has no roster/status table, so caps
# substitutes the LMU-pitcher filter (PitcherTeam='LOY_LIO', via
# _sibling_pitcher_ids) for "active roster". This is a PROVISIONAL,
# coach-confirmable difference: a pitcher who is on the historical LMU roster
# but not currently "active" would still show up here, where the warehouse
# view would have excluded them. No current fixture pitcher is affected.

def _pitcher_velo_appearances(pitcher_id) -> pd.DataFrame:
    """Per-appearance (game) Fastball/Sinker velo aggregates, sibling-id union.

    Mirrors the warehouse's vw_pitcher_appearance_velo. Adds `season_label`
    (derived, since GAMES has none) for velo_trend's season-partitioned LAG.

    Restricted to numeric GameIDs (see `_NUMERIC_GAME_ID_CLAUSE`) so
    `recent_outings`/`velo_trend` don't surface pre-CAPS-migration composite-
    GameID scrimmages/older seasons the warehouse oracle never showed --
    same season-boundary reasoning as `games_for_pitcher`.
    """
    ph, idp = _in_clause(_sibling_pitcher_ids(pitcher_id))
    df = query_df(
        f"""
        SELECT GameID AS game_id, Date AS game_date, GameType AS game_type,
               HomeTeam AS home_team_name, AwayTeam AS away_team_name,
               AVG(RelSpeed) AS appearance_avg_velo,
               MAX(RelSpeed) AS appearance_max_velo,
               MIN(RelSpeed) AS appearance_min_velo,
               COUNT(*) AS pitch_count
          FROM GAMES
         WHERE PitcherId IN ({ph}) AND TaggedPitchType IN ('Fastball', 'Sinker')
           AND {_NUMERIC_GAME_ID_CLAUSE}
         GROUP BY GameID, Date, GameType, HomeTeam, AwayTeam
        """,
        idp,
    )
    if df.empty:
        return df
    df["season_label"] = df["game_date"].apply(_season_label)
    return df


def recent_outings(pitcher_id, game_id, n: int = 5) -> pd.DataFrame:
    """This outing + prior ones, newest first, up to n rows.

    Mirrors `pitching.recent_outings`'s shape/behavior: pulls every
    Fastball/Sinker appearance for the pitcher, orders newest-first, then
    (if `game_id` is one of them) drops appearances after that game's date,
    and caps at `n` rows.
    """
    cols = ["game_id", "game_date", "season_label", "game_type",
            "home_team_name", "away_team_name", "appearance_avg_velo",
            "appearance_max_velo", "appearance_min_velo", "pitch_count"]
    df = _pitcher_velo_appearances(pitcher_id)
    if df.empty:
        return pd.DataFrame(columns=cols)
    df = df.sort_values("game_date", ascending=False, kind="mergesort").reset_index(drop=True)
    this_date = df.loc[df["game_id"] == int(game_id), "game_date"]
    if not this_date.empty:
        df = df[df["game_date"] <= this_date.iloc[0]]
    return df[cols].head(n).reset_index(drop=True)


def velo_trend(pitcher_id) -> pd.DataFrame:
    """Chronological avg/max velo per appearance, with velo_change vs the
    pitcher's previous appearance IN THE SAME SEASON (matches the oracle's
    `PARTITION BY pitcher_id, season_label ORDER BY game_date` LAG -- the
    first appearance of a season has a null velo_change)."""
    cols = ["game_date", "avg_velo", "max_velo", "pitch_count", "velo_change"]
    df = _pitcher_velo_appearances(pitcher_id)
    if df.empty:
        return pd.DataFrame(columns=cols)
    df = df.sort_values("game_date", kind="mergesort").reset_index(drop=True)
    df = df.rename(columns={
        "appearance_avg_velo": "avg_velo",
        "appearance_max_velo": "max_velo",
    })
    df["velo_change"] = df.groupby("season_label")["avg_velo"].diff()
    return df[cols]


def report_data_version(pitcher_id) -> str:
    """MAX(game_date) of the pitcher's Fastball/Sinker appearances, or 'none'.

    Cache-busting token for the postgame report (see
    `pitching.report_data_version`): new Fastball/Sinker data -> new max date
    -> new key -> rebuild; unchanged pitcher -> same key -> serve the cache.
    """
    df = _pitcher_velo_appearances(pitcher_id)
    if df.empty:
        return "none"
    v = df["game_date"].max()
    return "none" if v is None or pd.isna(v) else str(v)


# ======================= IDENTITY + ROSTER ==================================
#
# Pitcher identity here is RAW GAMES.PitcherId (== a player's trackman_id),
# unlike pitching.py's warehouse surrogate pitcher_id. GAMES.Pitcher is
# verified live as "Last, First" (e.g. "Behrens, Adam") -- the same format
# pitching.wh_lmu_pitchers/pitchers_for_game build from tm_player, so
# lmu_pitchers/pitchers_for_game read GAMES.Pitcher as-is. pitching.py's
# pitcher_name, however, builds "First Last" from tm_player, so
# pitcher_name() here must split "Last, First" -> "First Last" to match.

# Shared trailing-~12-month window (anchored to the newest LMU GAMES date, not
# today's date -- see hitting_caps._RECENT_WINDOW_CLAUSE for the same
# rationale: during the offseason an anchor on "today" would empty the list).
# Scopes lmu_pitchers() to current pitchers instead of GAMES's full history
# back to 2022.
_RECENT_WINDOW_CLAUSE = """Date >= (
               SELECT DATE_FORMAT(
                        DATE_SUB(STR_TO_DATE(MAX(Date), '%Y-%m-%d'), INTERVAL 12 MONTH),
                        '%Y-%m-%d')
                 FROM GAMES
                WHERE PitcherTeam = :team AND Date REGEXP '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
             )"""


def lmu_pitchers() -> pd.DataFrame:
    """One row per LMU pitcher (name deduped; canonical id = most-tracked id
    within the window), scoped to a ~12-month recent-data window.

    Mirrors pitching.wh_lmu_pitchers's dedup logic, but over GAMES/PitcherId
    instead of fact_tm_game_pitch/pitcher_id -- windowed for the same reason
    hitting_caps.lmu_hitters is: GAMES holds full CAPS history back to 2022,
    so an unscoped version would surface retired alumni the warehouse
    (current-season-only) never has.

    Also guarded by `_NUMERIC_GAME_ID_CLAUSE`: a pitcher can have in-window
    rows that are ALL legacy composite-GameID (pre-CAPS-migration) games --
    such a "ghost" would be listed here but every numeric-GameID-guarded data
    function (games_for_pitcher, season_summary, range_summary, velo views)
    returns empty for them, producing a blank dashboard. Restricting to
    numeric-GameID rows keeps the dropdown consistent with what the data
    functions can actually show, and also means the COUNT(*) dedup tiebreak
    is computed over current-era rows only.
    """
    df = query_df(
        f"""
        SELECT PitcherId, Pitcher FROM (
          SELECT PitcherId, Pitcher,
                 ROW_NUMBER() OVER (PARTITION BY Pitcher
                                    ORDER BY COUNT(*) DESC, PitcherId) AS rn
            FROM GAMES
           WHERE PitcherTeam = :team AND PitcherId IS NOT NULL
             AND {_RECENT_WINDOW_CLAUSE} AND {_NUMERIC_GAME_ID_CLAUSE}
           GROUP BY PitcherId, Pitcher
        ) t WHERE rn = 1 ORDER BY Pitcher
        """,
        {"team": LMU_PITCHER_TEAM},
    )
    if not df.empty:
        df["PitcherId"] = df["PitcherId"].astype(int)
    return df


def pitcher_name(pitcher_id) -> str:
    """"First Last", matching pitching.pitcher_name's format exactly (built
    from tm_player there; derived here by splitting GAMES.Pitcher's
    "Last, First")."""
    df = query_df(
        "SELECT Pitcher FROM GAMES WHERE PitcherId = :p LIMIT 1",
        {"p": int(pitcher_id)},
    )
    if df.empty:
        return f"Pitcher {pitcher_id}"
    raw = str(df.iloc[0]["Pitcher"])
    if "," in raw:
        last, first = (p.strip() for p in raw.split(",", 1))
        return f"{first} {last}".strip()
    return raw.strip()


def pitcher_tm_id_for(pitcher_id):
    """Identity: GAMES.PitcherId already IS the raw trackman id. Kept for API
    compat with the report/dashboard's role-gating code."""
    return int(pitcher_id)


def pitcher_profile(pitcher_id) -> dict:
    """Name + throws (from GAMES) + jersey/photo (roster_media, by raw id
    directly -- no pitcher_tm_id_for mapping needed, unlike the oracle)."""
    from app.data import roster_media
    name = pitcher_name(pitcher_id)
    thr = query_df(
        "SELECT PitcherThrows FROM GAMES WHERE PitcherId = :p "
        "AND PitcherThrows IS NOT NULL LIMIT 1",
        {"p": int(pitcher_id)},
    )
    throws = "" if thr.empty else str(thr.iloc[0]["PitcherThrows"])
    media = roster_media.player_media(int(pitcher_id))
    return {"name": name, "class_year": "", "position": "",
            "throws": throws, "jersey": media.get("jersey", ""),
            "photo": media.get("photo_url", "")}


def games_for_pitcher(pitcher_id, start=None, end=None) -> pd.DataFrame:
    """A pitcher's outings, newest first. GameLabel = 'YYYY-MM-DD vs/@ OPP'.
    Optional start/end (inclusive) bound game_date. Sibling-id union, matching
    pitching.games_for_pitcher's shape/format exactly.

    Restricted to numeric GameIDs (see the REGEXP filter below): GAMES also
    holds pre-CAPS-migration scrimmage rows under composite string GameIDs
    (e.g. "20241019-LoyolaMarymount-1", verified live back to 2024 for a real
    LMU pitcher) that predate the warehouse's synced season. Excluding them
    conveniently reproduces the oracle's season boundary exactly (verified:
    unbounded output is byte-identical to pitching.games_for_pitcher's for a
    real fixture), not just a defensive int-cast guard.
    """
    ph, idp = _in_clause(_sibling_pitcher_ids(pitcher_id))
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
         WHERE PitcherId IN ({ph}) AND {_NUMERIC_GAME_ID_CLAUSE}{date_clause}
        """,
        idp,
    )
    if df.empty:
        return pd.DataFrame(columns=["game_id", "game_date", "GameLabel"])
    # GameID is stored as text in GAMES; pre-CAPS-migration scrimmage rows use
    # composite string ids (e.g. "20241019-LoyolaMarymount-1") that predate the
    # numeric GameID convention -- excluded above via REGEXP so the int-cast
    # below never blows up on a real pitcher's older history (verified live:
    # this raw pitcher id has 38 such legacy rows going back to 2024). Numeric
    # ids still sort in pandas (not SQL ORDER BY, which would be lexicographic).
    df["game_id"] = df["game_id"].astype(int)
    df = df.sort_values(["game_date", "game_id"], ascending=[False, False]).reset_index(drop=True)
    lmu_home = df["home_team_id"] == LMU_TEAM_ID
    opp = df["away_team"].where(lmu_home, df["home_team"])
    loc = pd.Series("vs", index=df.index).where(lmu_home, "@")
    df["GameLabel"] = (df["game_date"].astype(str) + " " + loc + " " + opp.fillna("?"))
    return df[["game_id", "game_date", "GameLabel"]].reset_index(drop=True)


def pitchers_for_game(game_id, sort: str = "pitch") -> pd.DataFrame:
    """LMU pitchers who appeared in a game (reimplements vw_game_pitchers
    directly over GAMES, already filtered to PitcherTeam='LOY_LIO' -- no
    opponent-exclusion join needed since GAMES rows carry pitcher_team
    per-pitch, unlike the oracle's separate view + fact join).

    `sort`: "pitch" (default) orders by first pitch thrown (MIN(PitchNo));
    "alpha" orders by display_name. Anything else is treated as "pitch".
    """
    order_by = (
        "Pitcher" if sort == "alpha" else
        "(SELECT MIN(g2.PitchNo) FROM GAMES g2 "
        " WHERE g2.GameID = :gid AND g2.PitcherId = g.PitcherId)"
    )
    return query_df(
        f"""
        SELECT DISTINCT GameID AS game_id, PitcherId AS player_id,
               Pitcher AS display_name
          FROM GAMES g
         WHERE GameID = :gid AND PitcherTeam = :lmu
         ORDER BY {order_by}
        """,
        {"gid": int(game_id), "lmu": LMU_PITCHER_TEAM},
    )


def recent_games(limit: int = 25) -> pd.DataFrame:
    """LMU games (home or away), newest first, for the report picker.
    `GAMES` has no season_label column, so it's derived via `_season_label`."""
    df = query_df(
        """
        SELECT DISTINCT GameID AS game_id, Date AS game_date,
               GameType AS game_type, HomeTeam AS home_team, AwayTeam AS away_team
          FROM GAMES
         WHERE HomeTeamForeignID = :lmu OR AwayTeamForeignID = :lmu
         ORDER BY Date DESC, GameID DESC
         LIMIT :lim
        """,
        {"lmu": LMU_TEAM_ID, "lim": limit},
    )
    if df.empty:
        return pd.DataFrame(columns=["game_id", "game_date", "season_label",
                                      "game_type", "home_team", "away_team"])
    df["season_label"] = df["game_date"].apply(_season_label)
    return df[["game_id", "game_date", "season_label", "game_type", "home_team", "away_team"]]


# ======================== SEASON / RANGE SUMMARIES ==========================
#
# Both mirror pitching.py's warehouse versions exactly (same keys/format),
# scoped to a raw pitcher_id's sibling-id union. Neither takes a game_id, so
# there's no natural date bound to keep GAMES's pre-CAPS-migration composite-
# string-GameID scrimmage rows (see games_for_pitcher) out of "whole career"
# totals -- both apply the same _NUMERIC_GAME_ID_CLAUSE games_for_pitcher
# uses, which happens to reproduce the warehouse's synced-season boundary
# exactly (verified live: with the filter, a real fixture pitcher's totals
# are byte-identical to the oracle's).

def season_summary(pitcher_id) -> dict:
    """Coarse season tiles: appearances (distinct games) + total pitches + K + BB."""
    ph, idp = _in_clause(_sibling_pitcher_ids(pitcher_id))
    df = query_df(
        f"""
        SELECT COUNT(DISTINCT GameID) AS apps, COUNT(*) AS pitches,
               SUM(KorBB = 'Strikeout') AS k, SUM(KorBB = 'Walk') AS bb
          FROM GAMES
         WHERE PitcherId IN ({ph}) AND {_NUMERIC_GAME_ID_CLAUSE}
        """,
        idp,
    )
    if df.empty:
        return {"appearances": "—", "pitches": "—", "k": "—", "bb": "—"}
    r = df.iloc[0]
    def _s(v):
        return "—" if v is None or pd.isna(v) else str(int(v))
    return {"appearances": _s(r["apps"]), "pitches": _s(r["pitches"]),
            "k": _s(r["k"]), "bb": _s(r["bb"])}


def range_summary(pitcher_id, start=None, end=None) -> dict:
    """Date-range-scoped sidebar tiles: Appearances / IP / K% / Walk% / Barrel%.

    Loads the date-bounded pitch df (whole-career, numeric-GameID-only, when
    start/end are missing) and computes via the transforms shared with
    pitching.py (imported unchanged)."""
    pid = int(pitcher_id)
    if start and end:
        df = range_pitches_for(pid, start, end)
    else:
        ph, idp = _in_clause(_sibling_pitcher_ids(pid))
        df = query_df(
            f"SELECT {_PITCH_SELECT} FROM GAMES "
            f"WHERE PitcherId IN ({ph}) AND {_NUMERIC_GAME_ID_CLAUSE}",
            idp,
        )
    if df is None or df.empty:
        return {"appearances": "—", "ip": "—", "k_pct": "—",
                "bb_pct": "—", "barrel_pct": "—"}
    return {
        "appearances": str(int(df["game_id"].nunique())),
        "ip": format_ip(int(df["outs_on_play"].sum())),
        "k_pct": f"{k_pct(df)[0]:.1f}%",
        "bb_pct": f"{bb_pct(df)[0]:.1f}%",
        "barrel_pct": f"{barrel_pct_ev(df)[0]:.1f}%",
    }
