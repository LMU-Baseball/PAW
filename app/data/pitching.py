"""Pitcher data access + transforms for the postgame report.

Reads the modern Trackman warehouse: fact_tm_game_pitch (pitch grain),
dim_tm_game (game context), tm_player (names), and pitcher views. Keys are
warehouse game_id (int) + pitcher_id (bigint). Percentages returned NUMERIC.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from app.db import query_df

LMU_TEAM_ID = 78  # tm_team.team_name='LMU'; stable id (no collisions among teams)
# Trackman's PitcherTeam/BatterTeam code for LMU in fact_tm_game_pitch. The fact
# table stores the raw Trackman team abbreviation (e.g. 'SAN_TOR' for USD), not a
# team_id, so LMU pitchers are identified by this string. Verified live: LMU is
# the only 'LOY_LIO' in the warehouse (same code the hitting queries use).
LMU_PITCHER_TEAM = "LOY_LIO"
PITCH_TYPE_COL = "tagged_pitch_type"


def pitch_type(df: pd.DataFrame) -> pd.Series:
    """Tagged pitch type, falling back to auto_pitch_type when null/empty."""
    tagged = df[PITCH_TYPE_COL].replace("", np.nan)
    return tagged.fillna(df["auto_pitch_type"]).fillna("Undefined")


# ============================ QUERIES =====================================

def game_pitches(game_id: int, pitcher_id: int) -> pd.DataFrame:
    return query_df(
        """
        SELECT *
          FROM fact_tm_game_pitch
         WHERE game_id = :gid AND pitcher_id = :pid
         ORDER BY pitch_no
        """,
        {"gid": game_id, "pid": pitcher_id},
    )


def game_context(game_id: int) -> dict:
    # NOTE: tm_team has no `name` column — the actual columns are
    # team_id/school_name/team_name/nickname (verified against the live
    # warehouse schema). vw_pitcher_appearance_velo joins on `team_name` the
    # same way, so we mirror that here for a short, display-friendly label.
    dim = query_df(
        """
        SELECT g.game_date, g.season_label, g.game_type,
               ht.team_name AS home_team, at.team_name AS away_team,
               g.home_team_id, g.away_team_id
          FROM dim_tm_game g
          LEFT JOIN tm_team ht ON ht.team_id = g.home_team_id
          LEFT JOIN tm_team at ON at.team_id = g.away_team_id
         WHERE g.game_id = :gid
        """,
        {"gid": game_id},
    )
    if dim.empty:
        raise KeyError(f"No dim_tm_game row for game_id={game_id}")
    row = dim.iloc[0]

    # Final score: sum runs_scored by batting half. Top => away bats, Bottom => home.
    runs = query_df(
        """
        SELECT top_bottom, COALESCE(SUM(runs_scored), 0) AS runs
          FROM fact_tm_game_pitch
         WHERE game_id = :gid
         GROUP BY top_bottom
        """,
        {"gid": game_id},
    ).set_index("top_bottom")["runs"].to_dict()
    away_runs = int(runs.get("Top", 0))
    home_runs = int(runs.get("Bottom", 0))

    lmu_is_home = row["home_team_id"] == LMU_TEAM_ID
    return {
        "game_date": row["game_date"],
        "season_label": row["season_label"],
        "game_type": row["game_type"],
        "home_team": row["home_team"],
        "away_team": row["away_team"],
        "lmu_runs": home_runs if lmu_is_home else away_runs,
        "opp_runs": away_runs if lmu_is_home else home_runs,
        "lmu_is_home": bool(lmu_is_home),
    }


def recent_outings(pitcher_id: int, game_id: int, n: int = 5) -> pd.DataFrame:
    """This outing + prior ones, newest first, up to n rows."""
    df = query_df(
        """
        SELECT game_id, game_date, season_label, game_type,
               home_team_name, away_team_name,
               appearance_avg_velo, appearance_max_velo, appearance_min_velo,
               pitch_count
          FROM vw_pitcher_recent_outings
         WHERE pitcher_id = :pid
         ORDER BY game_date DESC
        """,
        {"pid": pitcher_id},
    )
    if df.empty:
        return df
    this_date = df.loc[df["game_id"] == game_id, "game_date"]
    if not this_date.empty:
        df = df[df["game_date"] <= this_date.iloc[0]]
    return df.head(n).reset_index(drop=True)


def velo_trend(pitcher_id: int) -> pd.DataFrame:
    return query_df(
        """
        SELECT game_date, avg_velo, max_velo, pitch_count, velo_change
          FROM vw_pitcher_velo_trend
         WHERE pitcher_id = :pid
         ORDER BY game_date
        """,
        {"pid": pitcher_id},
    )


def pitcher_name(pitcher_id: int) -> str:
    df = query_df(
        "SELECT first_name, last_name FROM tm_player WHERE player_id = :pid",
        {"pid": pitcher_id},
    )
    if df.empty:
        return f"Pitcher {pitcher_id}"
    r = df.iloc[0]
    return f"{r['first_name']} {r['last_name']}".strip()


def pitcher_tm_id_for(pitcher_id: int) -> int | None:
    """Raw Trackman id for a warehouse pitcher_id (for role gating)."""
    df = query_df(
        """
        SELECT pitcher_tm_id
          FROM fact_tm_game_pitch
         WHERE pitcher_id = :pid AND pitcher_tm_id IS NOT NULL
         LIMIT 1
        """,
        {"pid": pitcher_id},
    )
    return None if df.empty else int(df.iloc[0]["pitcher_tm_id"])


def recent_games(limit: int = 25) -> pd.DataFrame:
    """LMU games (home or away), newest first, for the report picker.

    Team names come from tm_team.team_name (the same display column
    game_context() uses); LMU is team_id 78. `dim_tm_game` holds non-LMU
    games too, so we filter to games LMU played in.
    """
    return query_df(
        """
        SELECT g.game_id, g.game_date, g.season_label, g.game_type,
               ht.team_name AS home_team, at.team_name AS away_team
          FROM dim_tm_game g
          LEFT JOIN tm_team ht ON ht.team_id = g.home_team_id
          LEFT JOIN tm_team at ON at.team_id = g.away_team_id
         WHERE g.home_team_id = :lmu OR g.away_team_id = :lmu
         ORDER BY g.game_date DESC, g.game_id DESC
         LIMIT :lim
        """,
        {"lmu": LMU_TEAM_ID, "lim": limit},
    )


def pitchers_for_game(game_id: int, sort: str = "pitch") -> pd.DataFrame:
    """LMU pitchers who appeared in a game.

    These reports are for LMU pitchers only, so opponents are filtered out via
    fact_tm_game_pitch.pitcher_team = LMU_PITCHER_TEAM ('LOY_LIO').

    Reads vw_game_pitchers (game_id, player_id, display_name; display_name is
    already "Last, First"). `sort` picks the row order:
      - "pitch" (default): order of appearance in the game — starter first,
        last reliever last — by each pitcher's first pitch. pitch_no is
        game-global sequential, so MIN(pitch_no) is the entry order.
      - "alpha": alphabetical by display_name.
    Any value other than "alpha" is treated as "pitch".
    """
    order_by = (
        "v.display_name" if sort == "alpha" else
        "(SELECT MIN(f.pitch_no) FROM fact_tm_game_pitch f "
        " WHERE f.game_id = v.game_id AND f.pitcher_id = v.player_id)"
    )
    return query_df(
        f"""
        SELECT v.game_id, v.player_id, v.display_name
          FROM vw_game_pitchers v
         WHERE v.game_id = :gid
           AND EXISTS (
                 SELECT 1 FROM fact_tm_game_pitch f
                  WHERE f.game_id = v.game_id
                    AND f.pitcher_id = v.player_id
                    AND f.pitcher_team = :lmu)
         ORDER BY {order_by}
        """,
        {"gid": game_id, "lmu": LMU_PITCHER_TEAM},
    )


def wh_lmu_pitchers() -> pd.DataFrame:
    """One row per LMU pitcher for the dashboard dropdown.

    Some pitchers have multiple pitcher_ids (split Trackman id schemes, same
    name); collapse to the most-tracked id per name, like the hitting module.
    Names come from tm_player as "Last, First".
    """
    return query_df(
        """
        SELECT PitcherId, Pitcher FROM (
          SELECT p.player_id AS PitcherId,
                 CONCAT(p.last_name, ', ', p.first_name) AS Pitcher,
                 COUNT(*) AS n,
                 ROW_NUMBER() OVER (
                   PARTITION BY p.last_name, p.first_name
                   ORDER BY COUNT(*) DESC) AS rn
            FROM fact_tm_game_pitch f
            JOIN tm_player p ON p.player_id = f.pitcher_id
           WHERE f.pitcher_team = :lmu AND f.pitcher_id IS NOT NULL
           GROUP BY p.player_id, p.last_name, p.first_name
        ) t
        WHERE rn = 1
        ORDER BY Pitcher
        """,
        {"lmu": LMU_PITCHER_TEAM},
    )


def _sibling_pitcher_ids(pitcher_id: int) -> list[int]:
    """All LMU pitcher_ids sharing this pitcher's name (split-id union)."""
    df = query_df(
        """
        SELECT DISTINCT f2.pitcher_id
          FROM fact_tm_game_pitch f
          JOIN tm_player p  ON p.player_id = f.pitcher_id
          JOIN tm_player p2 ON p2.last_name = p.last_name
                           AND p2.first_name = p.first_name
          JOIN fact_tm_game_pitch f2 ON f2.pitcher_id = p2.player_id
         WHERE f.pitcher_id = :pid AND f2.pitcher_team = :lmu
        """,
        {"pid": pitcher_id, "lmu": LMU_PITCHER_TEAM},
    )
    ids = [int(x) for x in df["pitcher_id"].tolist()]
    return ids or [int(pitcher_id)]


def games_for_pitcher(pitcher_id: int) -> pd.DataFrame:
    """A pitcher's outings, newest first. GameLabel = 'YYYY-MM-DD vs/@ OPP'."""
    ids = _sibling_pitcher_ids(pitcher_id)
    marks = ", ".join(f":id{i}" for i in range(len(ids)))
    params = {f"id{i}": v for i, v in enumerate(ids)}
    params["lmu"] = LMU_TEAM_ID
    df = query_df(
        f"""
        SELECT DISTINCT g.game_id, g.game_date,
               ht.team_name AS home_team, at.team_name AS away_team,
               g.home_team_id
          FROM fact_tm_game_pitch f
          JOIN dim_tm_game g ON g.game_id = f.game_id
          LEFT JOIN tm_team ht ON ht.team_id = g.home_team_id
          LEFT JOIN tm_team at ON at.team_id = g.away_team_id
         WHERE f.pitcher_id IN ({marks})
         ORDER BY g.game_date DESC, g.game_id DESC
        """,
        params,
    )
    if df.empty:
        return pd.DataFrame(columns=["game_id", "GameLabel"])
    lmu_home = df["home_team_id"] == LMU_TEAM_ID
    opp = df["away_team"].where(lmu_home, df["home_team"])
    loc = pd.Series("vs", index=df.index).where(lmu_home, "@")
    df["GameLabel"] = (df["game_date"].astype(str) + " " + loc + " " + opp.fillna("?"))
    return df[["game_id", "GameLabel"]].reset_index(drop=True)


def pitcher_profile(pitcher_id: int) -> dict:
    """Name + throws (from the warehouse) + jersey/photo (best-effort roster media)."""
    from app.data import roster_media
    name = pitcher_name(pitcher_id)  # "First Last"
    thr = query_df(
        """
        SELECT pitcher_throws FROM fact_tm_game_pitch
         WHERE pitcher_id = :pid AND pitcher_throws IS NOT NULL LIMIT 1
        """,
        {"pid": pitcher_id},
    )
    throws = "" if thr.empty else str(thr.iloc[0]["pitcher_throws"])
    tm_id = pitcher_tm_id_for(pitcher_id)
    media = roster_media.player_media(tm_id) if tm_id is not None else {"jersey": "", "photo_url": ""}
    return {"name": name, "class_year": "", "position": "",
            "throws": throws, "jersey": media.get("jersey", ""),
            "photo": media.get("photo_url", "")}


def season_summary(pitcher_id: int) -> dict:
    """Coarse season tiles: appearances (distinct games) + total pitches + K + BB."""
    ids = _sibling_pitcher_ids(pitcher_id)
    marks = ", ".join(f":id{i}" for i in range(len(ids)))
    params = {f"id{i}": v for i, v in enumerate(ids)}
    df = query_df(
        f"""
        SELECT COUNT(DISTINCT game_id) AS apps, COUNT(*) AS pitches,
               SUM(korbb = 'Strikeout') AS k, SUM(korbb = 'Walk') AS bb
          FROM fact_tm_game_pitch
         WHERE pitcher_id IN ({marks})
        """,
        params,
    )
    if df.empty:
        return {"appearances": "—", "pitches": "—", "k": "—", "bb": "—"}
    r = df.iloc[0]
    def _s(v):
        return "—" if v is None or pd.isna(v) else str(int(v))
    return {"appearances": _s(r["apps"]), "pitches": _s(r["pitches"]),
            "k": _s(r["k"]), "bb": _s(r["bb"])}


def report_data_version(pitcher_id: int) -> str:
    """A token that changes when a pitcher gets new data, for report caching.

    The postgame report's season velo-trend spans every game, so a cached PDF
    would go stale once the pitcher throws again. Keying the cache on the
    pitcher's latest trend game_date means new data yields a new key (rebuild),
    while an unchanged pitcher serves the cache. Returns "none" if the pitcher
    has no trend rows yet.
    """
    df = query_df(
        "SELECT MAX(game_date) AS v FROM vw_pitcher_velo_trend WHERE pitcher_id = :pid",
        {"pid": pitcher_id},
    )
    v = df.iloc[0]["v"] if not df.empty else None
    return "none" if v is None or pd.isna(v) else str(v)


# ============================ TRANSFORMS ==================================
#
# NOTE on column-semantics adjustments made after checking against the live
# fixture (game_id=166, pitcher_id=1) and a full-table scan of distinct
# values:
#
# - pitch_call: the live values are StrikeCalled, StrikeSwinging, InPlay,
#   BallCalled, HitByPitch, Undefined, FoulBallNotFieldable,
#   FoulBallFieldable, BallinDirt, BallIntentional, AutomaticBall — there is
#   no plain "FoulBall" and balls aren't only "BallCalled". _STRIKE_CALLS/
#   _SWING_CALLS use the two Foul* variants instead of "FoulBall", and a new
#   _BALL_CALLS set covers all called/no-swing ball variants (BallCalled,
#   BallinDirt, BallIntentional, AutomaticBall). HitByPitch and Undefined are
#   intentionally excluded from both strikes and balls (dead-ball / no call).
#
# - zi: this column is NULL for every row in fact_tm_game_pitch (verified
#   warehouse-wide), so it cannot be used as an in-zone indicator. zone
#   location instead derives in-zone from izt_zone, whose values are the
#   strings "1".."9" (the 3x3 strike-zone grid), "Shadow" (borderline), and
#   "Ball" (clearly out). in_zone_pct = % of pitches with izt_zone in 1..9.

_STRIKE_CALLS = {"StrikeCalled", "StrikeSwinging", "FoulBallNotFieldable",
                  "FoulBallFieldable", "InPlay"}
_WHIFF_CALLS = {"StrikeSwinging"}
_SWING_CALLS = {"StrikeSwinging", "FoulBallNotFieldable", "FoulBallFieldable", "InPlay"}
_BALL_CALLS = {"BallCalled", "BallinDirt", "BallIntentional", "AutomaticBall"}
_IN_ZONE_CODES = {"1", "2", "3", "4", "5", "6", "7", "8", "9"}

_HIT_RESULTS = {"Single", "Double", "Triple", "HomeRun"}


def _pct(a: int, b: int) -> float:
    return round(100.0 * a / b, 1) if b else 0.0


def _pa_count(df: pd.DataFrame) -> int:
    """Plate appearances = distinct (inning, pa_of_inning) among the pitches.

    Split-safe (works on a batter-side subset), unlike batters_faced.max()
    which is a running counter over the whole outing.
    """
    if df.empty:
        return 0
    return int(df[["inning", "pa_of_inning"]].drop_duplicates().shape[0])


def strike_pct(df: pd.DataFrame) -> tuple[float, int]:
    s = int(df["pitch_call"].isin(_STRIKE_CALLS).sum())
    return _pct(s, len(df)), s


def fps_pct(df: pd.DataFrame) -> tuple[float, int]:
    fp = df[df["pitch_of_pa"] == 1]
    s = int(fp["pitch_call"].isin(_STRIKE_CALLS).sum())
    return _pct(s, len(fp)), s


def k_pct(df: pd.DataFrame) -> tuple[float, int]:
    k = int((df["korbb"] == "Strikeout").sum())
    return _pct(k, _pa_count(df)), k


def bb_pct(df: pd.DataFrame) -> tuple[float, int]:
    bb = int((df["korbb"] == "Walk").sum())
    return _pct(bb, _pa_count(df)), bb


def ea_pct(df: pd.DataFrame) -> tuple[float, int]:
    """Early & Ahead %. PROVISIONAL v1 definition (confirm with coaches):
    share of PAs where the pitcher reached an ahead count (strikes-balls >= 1)
    at any point in the PA. balls/strikes are the recorded count on each pitch.
    """
    if df.empty:
        return 0.0, 0
    ahead = df.groupby(["inning", "pa_of_inning"]).apply(
        lambda p: bool(((p["strikes"] - p["balls"]).max()) >= 1), include_groups=False)
    return _pct(int(ahead.sum()), int(ahead.shape[0])), int(ahead.sum())


def pre2k_pct(df: pd.DataFrame) -> tuple[float, int]:
    """Pre-2K strike %. PROVISIONAL v1: strike% on pitches thrown in counts
    with fewer than 2 strikes."""
    sub = df[df["strikes"] < 2]
    s = int(sub["pitch_call"].isin(_STRIKE_CALLS).sum())
    return _pct(s, len(sub)), s


def twok_kill_pct(df: pd.DataFrame) -> tuple[float, int]:
    """2K Kill %. PROVISIONAL v1: strikeouts / PAs that reached a 2-strike count."""
    if df.empty:
        return 0.0, 0
    g = df.groupby(["inning", "pa_of_inning"])
    reached = g.apply(lambda p: bool((p["strikes"] >= 2).any()), include_groups=False)
    ks = g.apply(lambda p: bool((p["korbb"] == "Strikeout").any()), include_groups=False)
    kills = int((reached & ks).sum())
    return _pct(kills, int(reached.sum())), kills


def barrel_pct(df: pd.DataFrame) -> tuple[float, int]:
    """Barrel %. PROVISIONAL v1 (no launch-angle column in the warehouse):
    barrels / balls in play, barrel ~ exit_speed >= 95 and tagged_hit_type in
    {LineDrive, FlyBall}."""
    bip = df[df["pitch_call"] == "InPlay"]
    barrels = int(((bip["exit_speed"] >= 95)
                   & (bip["tagged_hit_type"].isin({"LineDrive", "FlyBall"}))).sum())
    return _pct(barrels, len(bip)), barrels


def header_stat_line(df: pd.DataFrame) -> dict:
    """The header line: batters faced (R/L), outs, hits, runs, BB, SO, pitches."""
    return {
        "bf": _pa_count(df),
        "bf_r": _pa_count(df[df["batter_side"] == "Right"]),
        "bf_l": _pa_count(df[df["batter_side"] == "Left"]),
        "outs": int(df["outs_on_play"].sum()) if len(df) else 0,
        "h": int(df["play_result"].isin(_HIT_RESULTS).sum()) if len(df) else 0,
        "r": int(df["runs_scored"].sum()) if len(df) else 0,
        "bb": int((df["korbb"] == "Walk").sum()) if len(df) else 0,
        "so": int((df["korbb"] == "Strikeout").sum()) if len(df) else 0,
        "pitches": len(df),
    }


def game_overall_line(df: pd.DataFrame) -> dict:
    n = len(df)
    calls = df["pitch_call"]
    strikes = int(calls.isin(_STRIKE_CALLS).sum())
    balls = int(calls.isin(_BALL_CALLS).sum())
    swings = int(calls.isin(_SWING_CALLS).sum())
    whiffs = int(calls.isin(_WHIFF_CALLS).sum())
    korbb = df["korbb"]
    first_pitch = df[df["pitch_of_pa"] == 1]
    fps = int(first_pitch["pitch_call"].isin(_STRIKE_CALLS).sum())

    def pct(a, b):
        return round(100.0 * a / b, 1) if b else 0.0

    return {
        "pitches": n,
        "batters_faced": int(df["batters_faced"].max() or 0) if n else 0,
        "strikes": strikes,
        "balls": balls,
        "strike_pct": pct(strikes, n),
        "whiff_pct": pct(whiffs, swings),
        "k": int((korbb == "Strikeout").sum()),
        "bb": int((korbb == "Walk").sum()),
        "first_pitch_strike_pct": pct(fps, len(first_pitch)),
        "runs": int(df["runs_scored"].sum()) if n else 0,
    }


def pitch_characteristics(df: pd.DataFrame) -> pd.DataFrame:
    d = df.assign(_pt=pitch_type(df))
    n = len(d)
    g = d.groupby("_pt")
    out = pd.DataFrame({
        "count": g.size(),
        "avg_velo": g["rel_speed"].mean().round(1),
        "max_velo": g["rel_speed"].max().round(1),
        "spin_rate": g["spin_rate"].mean().round(0),
        "ivb": g["induced_vert_break"].mean().round(1),
        "hb": g["horz_break"].mean().round(1),
        "rel_height": g["rel_height"].mean().round(2),
        "rel_side": g["rel_side"].mean().round(2),
        "extension": g["extension"].mean().round(2),
    }).reset_index(names="pitch")
    out["usage_pct"] = (100.0 * out["count"] / n).round(1)
    return out.sort_values("count", ascending=False).reset_index(drop=True)


def pitch_usage(df: pd.DataFrame) -> pd.DataFrame:
    d = df.assign(_pt=pitch_type(df))
    n = len(d)
    out = (d.groupby("_pt").size().reset_index(name="count")
             .rename(columns={"_pt": "pitch"}))
    out["usage_pct"] = (100.0 * out["count"] / n).round(1)
    return out.sort_values("count", ascending=False).reset_index(drop=True)


def zone_location(df: pd.DataFrame) -> pd.DataFrame:
    d = df.assign(_pt=pitch_type(df),
                  _in_zone=df["izt_zone"].isin(_IN_ZONE_CODES))
    g = d.groupby("_pt")
    out = pd.DataFrame({
        "count": g.size(),
        "in_zone_pct": (100.0 * g["_in_zone"].mean()).round(1),
    }).reset_index(names="pitch")
    return out.sort_values("count", ascending=False).reset_index(drop=True)


def usage_by_count(df: pd.DataFrame) -> pd.DataFrame:
    d = df.assign(_pt=pitch_type(df),
                  count_state=df["balls"].astype(str) + "-" + df["strikes"].astype(str))
    return (d.pivot_table(index="count_state", columns="_pt", values="pitch_no",
                          aggfunc="count", fill_value=0)
              .reset_index())


def splits_by_batter_side(df: pd.DataFrame) -> dict:
    out = {}
    for side in ("Left", "Right"):
        sub = df[df["batter_side"] == side]
        out[side] = {
            "overall": game_overall_line(sub) if len(sub) else game_overall_line(df.iloc[0:0]),
            "usage": pitch_usage(sub) if len(sub) else pitch_usage(df.iloc[0:0]),
        }
    return out


def averages_last5(recent_df: pd.DataFrame) -> pd.DataFrame:
    if recent_df.empty:
        return recent_df
    cols = ["game_date", "away_team_name", "home_team_name",
            "appearance_avg_velo", "appearance_max_velo", "pitch_count"]
    return recent_df[cols].copy()


# ============================ FIGURES =====================================

_SZ = dict(x0=-0.83, x1=0.83, y0=1.5, y1=3.5)  # approx strike zone (ft)


def _base_layout(fig: go.Figure, title: str) -> go.Figure:
    fig.update_layout(
        title=title, template="simple_white",
        font=dict(family="Teko, sans-serif", size=16),
        margin=dict(l=40, r=20, t=50, b=40), showlegend=True,
    )
    return fig


def fig_velo_by_inning(df: pd.DataFrame) -> go.Figure:
    d = df.dropna(subset=["rel_speed"])
    g = d.groupby("inning")["rel_speed"].mean().reset_index()
    fig = go.Figure(go.Bar(x=g["inning"], y=g["rel_speed"].round(1)))
    fig.update_xaxes(title="Inning"); fig.update_yaxes(title="Avg Velo (mph)")
    return _base_layout(fig, "Velocity by Inning")


def fig_velo_by_pitch(df: pd.DataFrame) -> go.Figure:
    d = df.dropna(subset=["rel_speed"]).copy()
    d["_pt"] = pitch_type(d)
    fig = go.Figure()
    for pt, sub in d.groupby("_pt"):
        fig.add_trace(go.Scatter(x=sub["pitch_no"], y=sub["rel_speed"],
                                 mode="markers+lines", name=pt))
    fig.update_xaxes(title="Pitch #"); fig.update_yaxes(title="Velo (mph)")
    return _base_layout(fig, "Velocity Across Outing")


def fig_movement(df: pd.DataFrame) -> go.Figure:
    d = df.dropna(subset=["horz_break", "induced_vert_break"]).copy()
    d["_pt"] = pitch_type(d)
    fig = go.Figure()
    for pt, sub in d.groupby("_pt"):
        fig.add_trace(go.Scatter(x=sub["horz_break"], y=sub["induced_vert_break"],
                                 mode="markers", name=pt))
    fig.update_xaxes(title="Horizontal Break (in)", zeroline=True)
    fig.update_yaxes(title="Induced Vert Break (in)", zeroline=True)
    return _base_layout(fig, "Pitch Movement")


def _add_zone(fig: go.Figure) -> None:
    fig.add_shape(type="rect", line=dict(color="black", width=2), **_SZ)


def fig_location(df: pd.DataFrame) -> go.Figure:
    d = df.dropna(subset=["plate_loc_side", "plate_loc_height"]).copy()
    d["_pt"] = pitch_type(d)
    fig = go.Figure()
    for pt, sub in d.groupby("_pt"):
        fig.add_trace(go.Scatter(x=sub["plate_loc_side"], y=sub["plate_loc_height"],
                                 mode="markers", name=pt))
    _add_zone(fig)
    fig.update_xaxes(title="Plate Side (ft)", range=[-2.5, 2.5])
    fig.update_yaxes(title="Plate Height (ft)", range=[0, 5], scaleanchor="x")
    return _base_layout(fig, "Pitch Location (Catcher View)")


def fig_location_split(df: pd.DataFrame) -> go.Figure:
    d = df.dropna(subset=["plate_loc_side", "plate_loc_height"]).copy()
    fig = go.Figure()
    for side, sub in d.groupby("batter_side"):
        fig.add_trace(go.Scatter(x=sub["plate_loc_side"], y=sub["plate_loc_height"],
                                 mode="markers", name=f"vs {side}"))
    _add_zone(fig)
    fig.update_xaxes(title="Plate Side (ft)", range=[-2.5, 2.5])
    fig.update_yaxes(title="Plate Height (ft)", range=[0, 5], scaleanchor="x")
    return _base_layout(fig, "Location vs LHH/RHH")


def fig_velo_trend(trend_df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if not trend_df.empty:
        fig.add_trace(go.Scatter(x=trend_df["game_date"], y=trend_df["avg_velo"],
                                 mode="markers+lines", name="Avg Velo"))
    fig.update_xaxes(title="Game Date"); fig.update_yaxes(title="Avg Velo (mph)")
    return _base_layout(fig, "Velocity Trend (Season)")


def _heatmap(d: pd.DataFrame, title: str) -> go.Figure:
    fig = go.Figure(go.Histogram2dContour(
        x=d["plate_loc_side"], y=d["plate_loc_height"],
        colorscale="YlOrRd", showscale=False, ncontours=12,
    ))
    _add_zone(fig)
    fig.update_xaxes(title="", range=[-2.5, 2.5], showticklabels=False)
    fig.update_yaxes(title="", range=[0, 5], scaleanchor="x", showticklabels=False)
    out = _base_layout(fig, title); out.update_layout(showlegend=False)
    return out


def fig_heatmap_overall(df: pd.DataFrame) -> go.Figure:
    d = df.dropna(subset=["plate_loc_side", "plate_loc_height"])
    return _heatmap(d, "Location Heatmap (All Pitches)")


def fig_heatmaps_by_pitch_type(df: pd.DataFrame) -> list:
    d = df.dropna(subset=["plate_loc_side", "plate_loc_height"]).copy()
    d["_pt"] = pitch_type(d)
    items = []
    for pt, sub in d.groupby("_pt"):
        if len(sub) >= 3:
            items.append((pt, _heatmap(sub, pt)))
    return items


# ============================ TABLE ASSEMBLERS ============================

def _r1(x) -> float | None:
    """Round to 1 dp, or None if NaN/empty."""
    return None if x is None or pd.isna(x) else round(float(x), 1)


def _metric_rows(df: pd.DataFrame, specs: list[tuple]) -> list[dict]:
    rhh = df[df["batter_side"] == "Right"]
    lhh = df[df["batter_side"] == "Left"]
    rows = []
    for label, key, fn in specs:
        pct, cnt = fn(df)
        rows.append({
            "metric": label, "key": key,
            "value_pct": pct, "value_count": cnt,
            "vrhh": fn(rhh)[0], "vlhh": fn(lhh)[0],
        })
    return rows


def process_metrics(df: pd.DataFrame) -> list[dict]:
    return _metric_rows(df, [
        ("Strike%", "strike_pct", strike_pct),
        ("FPS%", "fps_pct", fps_pct),
        ("E&A%", "ea_pct", ea_pct),
        ("Pre2K%", "pre2k_pct", pre2k_pct),
        ("2K Kill%", "twok_kill_pct", twok_kill_pct),
    ])


def outcome_metrics(df: pd.DataFrame) -> list[dict]:
    return _metric_rows(df, [
        ("K%", "k_pct", k_pct),
        ("BB%", "bb_pct", bb_pct),
        ("Barrel%", "barrel_pct", barrel_pct),
    ])


def pitch_usage_table(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []
    d = df.assign(_pt=pitch_type(df))
    n = len(d)
    n_r = len(d[d["batter_side"] == "Right"]) or 1
    n_l = len(d[d["batter_side"] == "Left"]) or 1
    n_2k = len(d[d["strikes"] == 2]) or 1
    rows = []
    for pt, sub in d.groupby("_pt"):
        rows.append({
            "pitch": pt,
            "strike_pct": _pct(int(sub["pitch_call"].isin(_STRIKE_CALLS).sum()), len(sub)),
            "usage_pct": _pct(len(sub), n),
            # PROVISIONAL: share of the pitcher's 2-strike-count pitches that
            # were this pitch type.
            "twok_usage_pct": _pct(len(sub[sub["strikes"] == 2]), n_2k),
            "vrhh": _pct(len(sub[sub["batter_side"] == "Right"]), n_r),
            "vlhh": _pct(len(sub[sub["batter_side"] == "Left"]), n_l),
            "_count": len(sub),
        })
    rows.sort(key=lambda r: r["_count"], reverse=True)
    for r in rows:
        del r["_count"]
    return rows


def movement_summary(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []
    d = df.assign(_pt=pitch_type(df))
    rows = []
    for pt, sub in d.groupby("_pt"):
        rhh = sub[sub["batter_side"] == "Right"]
        lhh = sub[sub["batter_side"] == "Left"]
        # PROVISIONAL "Spread": std dev of total break magnitude (movement
        # consistency), in inches.
        mag = np.sqrt(sub["induced_vert_break"] ** 2 + sub["horz_break"] ** 2)
        spread = float(mag.std(ddof=0)) if len(sub) > 1 else 0.0
        rows.append({
            "pitch": pt,
            "velo_avg": _r1(sub["rel_speed"].mean()),
            "velo_max": _r1(sub["rel_speed"].max()),
            "ivb_avg": _r1(sub["induced_vert_break"].mean()),
            "ivb_rhh": _r1(rhh["induced_vert_break"].mean()) if len(rhh) else None,
            "ivb_lhh": _r1(lhh["induced_vert_break"].mean()) if len(lhh) else None,
            "hb_avg": _r1(sub["horz_break"].mean()),
            "hb_rhh": _r1(rhh["horz_break"].mean()) if len(rhh) else None,
            "hb_lhh": _r1(lhh["horz_break"].mean()) if len(lhh) else None,
            "spread": _r1(spread),
            "_count": len(sub),
        })
    rows.sort(key=lambda r: r["_count"], reverse=True)
    for r in rows:
        del r["_count"]
    return rows
