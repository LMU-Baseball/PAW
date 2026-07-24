"""Catcher data access + transforms for the catching stats dashboard.

Reads the modern Trackman warehouse (fact_tm_game_pitch / dim_tm_game /
tm_player / tm_team). Canonical id = warehouse catcher_id (== tm_player.player_id).
LMU catchers are those who received while pitcher_team = 'LOY_LIO'.

Metric definitions for framing / blocking / throws are PROVISIONAL v1 (docstring'd)
and coach-confirmable once the legacy R catcher app under src/ is available.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.db import query_df
from app.data.hitting_wh import attack_zone

LMU_TEAM_ID = 78
LMU_PITCHER_TEAM = "LOY_LIO"  # catcher is on the pitching team


def _in_clause(ids) -> tuple[str, dict]:
    ph = ", ".join(f":id{i}" for i in range(len(ids)))
    return ph, {f"id{i}": int(v) for i, v in enumerate(ids)}


def _sibling_catcher_ids(catcher_id: int) -> list[int]:
    """All LMU catcher_ids sharing this catcher's name (split-id union)."""
    df = query_df(
        """
        SELECT DISTINCT f2.catcher_id
          FROM fact_tm_game_pitch f
          JOIN tm_player p  ON p.player_id = f.catcher_id
          JOIN tm_player p2 ON p2.last_name = p.last_name
                           AND p2.first_name = p.first_name
          JOIN fact_tm_game_pitch f2 ON f2.catcher_id = p2.player_id
         WHERE f.catcher_id = :cid
           AND f2.pitcher_team = :lmu
           AND f2.catcher_id IS NOT NULL
        """,
        {"cid": int(catcher_id), "lmu": LMU_PITCHER_TEAM},
    )
    ids = [int(x) for x in df["catcher_id"].tolist()] if not df.empty else []
    return ids or [int(catcher_id)]


def wh_lmu_catchers() -> pd.DataFrame:
    """One row per LMU catcher for the dashboard dropdown (name-deduped)."""
    return query_df(
        """
        SELECT CatcherId, Catcher FROM (
          SELECT p.player_id AS CatcherId,
                 CONCAT(p.last_name, ', ', p.first_name) AS Catcher,
                 COUNT(*) AS n,
                 ROW_NUMBER() OVER (
                   PARTITION BY p.last_name, p.first_name
                   ORDER BY COUNT(*) DESC, p.player_id) AS rn
            FROM fact_tm_game_pitch f
            JOIN tm_player p ON p.player_id = f.catcher_id
           WHERE f.pitcher_team = :lmu AND f.catcher_id IS NOT NULL
           GROUP BY p.player_id, p.last_name, p.first_name
        ) t
        WHERE rn = 1
        ORDER BY Catcher
        """,
        {"lmu": LMU_PITCHER_TEAM},
    )


def catcher_name(catcher_id: int) -> str:
    df = query_df(
        "SELECT first_name, last_name FROM tm_player WHERE player_id = :pid",
        {"pid": int(catcher_id)},
    )
    if df.empty:
        return str(catcher_id)
    return f"{df.iloc[0]['last_name']}, {df.iloc[0]['first_name']}"


def catcher_tm_id_for(catcher_id: int):
    df = query_df(
        """
        SELECT catcher_tm_id FROM fact_tm_game_pitch
         WHERE catcher_id = :cid AND catcher_tm_id IS NOT NULL
         GROUP BY catcher_tm_id ORDER BY COUNT(*) DESC LIMIT 1
        """,
        {"cid": int(catcher_id)},
    )
    if df.empty or pd.isna(df.iloc[0]["catcher_tm_id"]):
        return None
    return int(df.iloc[0]["catcher_tm_id"])


def games_for_catcher(catcher_id: int, start=None, end=None) -> pd.DataFrame:
    """A catcher's games, newest first. GameLabel = 'YYYY-MM-DD vs/@ OPP'.
    Optional start/end (inclusive) bound game_date."""
    ids = _sibling_catcher_ids(catcher_id)
    marks, params = _in_clause(ids)
    params["lmu"] = LMU_TEAM_ID
    date_clause = ""
    if start is not None and end is not None:
        date_clause = " AND g.game_date BETWEEN :start AND :end"
        params["start"] = str(start)
        params["end"] = str(end)
    df = query_df(
        f"""
        SELECT DISTINCT g.game_id, g.game_date,
               ht.team_name AS home_team, at.team_name AS away_team,
               g.home_team_id
          FROM fact_tm_game_pitch f
          JOIN dim_tm_game g ON g.game_id = f.game_id
          LEFT JOIN tm_team ht ON ht.team_id = g.home_team_id
          LEFT JOIN tm_team at ON at.team_id = g.away_team_id
         WHERE f.catcher_id IN ({marks}){date_clause}
         ORDER BY g.game_date DESC, g.game_id DESC
        """,
        params,
    )
    if df.empty:
        return pd.DataFrame(columns=["game_id", "game_date", "GameLabel"])
    lmu_home = df["home_team_id"] == LMU_TEAM_ID
    opp = df["away_team"].where(lmu_home, df["home_team"])
    loc = pd.Series("vs", index=df.index).where(lmu_home, "@")
    df["GameLabel"] = (df["game_date"].astype(str) + " " + loc + " " + opp.fillna("?"))
    return df[["game_id", "game_date", "GameLabel"]].reset_index(drop=True)


def game_pitches_for(game_id: int, catcher_id: int) -> pd.DataFrame:
    """Pitch-level rows for one catcher in one game (sibling-id union)."""
    ids = _sibling_catcher_ids(catcher_id)
    marks, params = _in_clause(ids)
    params["gid"] = int(game_id)
    return query_df(
        f"""
        SELECT * FROM fact_tm_game_pitch
         WHERE game_id = :gid AND catcher_id IN ({marks})
         ORDER BY pitch_no
        """,
        params,
    )


def range_pitches_for(catcher_id: int, start, end) -> pd.DataFrame:
    """All of a catcher's pitches across in-range games (sibling-id union)."""
    ids = _sibling_catcher_ids(catcher_id)
    marks, params = _in_clause(ids)
    params["start"] = str(start)
    params["end"] = str(end)
    return query_df(
        f"""
        SELECT f.* FROM fact_tm_game_pitch f
          JOIN dim_tm_game g ON g.game_id = f.game_id
         WHERE f.catcher_id IN ({marks})
           AND g.game_date BETWEEN :start AND :end
         ORDER BY f.game_id, f.pitch_no
        """,
        params,
    )


def catcher_profile(catcher_id: int) -> dict:
    """Name + jersey/photo (best-effort roster media)."""
    from app.data import roster_media
    name = catcher_name(catcher_id)
    tm_id = catcher_tm_id_for(catcher_id)
    media = roster_media.player_media(tm_id) if tm_id is not None else {
        "jersey": "", "photo_url": "",
    }
    return {
        "name": name, "class_year": "", "position": "C",
        "throws": "", "jersey": media.get("jersey", ""),
        "photo": media.get("photo_url", ""),
    }


def game_pitches_season(catcher_id: int) -> pd.DataFrame:
    """All season pitches for a catcher (sibling-id union). Prefer aggregates
    for sidebar tiles; use this only when full pitch-level season analysis is needed."""
    ids = _sibling_catcher_ids(catcher_id)
    marks, params = _in_clause(ids)
    return query_df(
        f"""
        SELECT * FROM fact_tm_game_pitch
         WHERE catcher_id IN ({marks})
         ORDER BY game_id, pitch_no
        """,
        params,
    )


def game_context(game_id: int) -> dict:
    """Reuse pitching's game context shape for the scoreboard."""
    from app.data import pitching as P
    return P.game_context(game_id)


# ============================ TRANSFORMS ==================================

def _col(df: pd.DataFrame, *names: str) -> str | None:
    """Return the first present column name (case-sensitive), else None."""
    for n in names:
        if n in df.columns:
            return n
    return None


# Fastball/Offspeed recode of tagged_pitch_type (matches legacy src/app.R).
PITCH_SPEED_MAP = {
    "Fastball": "Fastball", "Sinker": "Fastball", "Cutter": "Fastball",
    "Splitter": "Fastball", "TwoSeamFastBall": "Fastball",
    "FourSeamFastBall": "Fastball", "OneSeamFastBall": "Fastball",
    "Slider": "Offspeed", "ChangeUp": "Offspeed", "Changeup": "Offspeed",
    "Curveball": "Offspeed", "Knuckleball": "Offspeed", "Undefined": "Offspeed",
}


def _in_zone(side_ft, height_ft) -> bool:
    """Rulebook strike-zone box in catcher-view inches (PROVISIONAL, coach-
    confirmable). The legacy app used a Trackman InZone DB flag the warehouse
    lacks (zi is NULL). Box matches the solid rectangle drawn in src/app.R."""
    if side_ft is None or height_ft is None or pd.isna(side_ft) or pd.isna(height_ft):
        return False
    return abs(float(side_ft) * 12) <= 10 and abs(float(height_ft) * 12 - 30) <= 13


def add_framing_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Derive Zone / InZone / PitchSpeed / CallType / _x / _y for framing views.

    CallType (PROVISIONAL v1, matches legacy stolen/lost model):
      Stolen Strike = out-of-zone pitch called StrikeCalled
      Lost Strike   = in-zone pitch called BallCalled
      Correct Call  = everything else (incl. swings / in-play — no framing signal)
    """
    if df.empty:
        return df.copy()
    out = df.copy()
    out["Zone"] = [attack_zone(s, h)
                   for s, h in zip(out["plate_loc_side"], out["plate_loc_height"])]
    out["InZone"] = [_in_zone(s, h)
                     for s, h in zip(out["plate_loc_side"], out["plate_loc_height"])]
    out["PitchSpeed"] = (out["tagged_pitch_type"].map(PITCH_SPEED_MAP)
                         .fillna("Offspeed"))
    call = out["pitch_call"].astype(str)
    out["CallType"] = "Correct Call"
    out.loc[(~out["InZone"]) & (call == "StrikeCalled"), "CallType"] = "Stolen Strike"
    out.loc[(out["InZone"]) & (call == "BallCalled"), "CallType"] = "Lost Strike"
    out["_x"] = out["plate_loc_side"] * -12
    out["_y"] = out["plate_loc_height"] * 12 - 30
    return out


def apply_framing_filters(df: pd.DataFrame, *, bat_side="All",
                          pitcher_throws="All", pitch_speed="All",
                          zone="All") -> pd.DataFrame:
    """Apply the 4 legacy framing filters. 'All' = no filter on that dimension.
    Expects columns from add_framing_cols."""
    if df.empty:
        return df.copy()
    out = df
    if bat_side != "All":
        out = out[out["batter_side"] == bat_side]
    if pitcher_throws != "All":
        out = out[out["pitcher_throws"] == pitcher_throws]
    if pitch_speed != "All":
        out = out[out["PitchSpeed"] == pitch_speed]
    if zone != "All":
        out = out[out["Zone"] == zone]
    return out.copy()


def _pct(num, den):
    return None if not den else round(100.0 * num / den, 1)


def framing_table(df: pd.DataFrame) -> dict:
    """Legacy stolen/lost framing summary (PROVISIONAL; formulas verbatim from
    src/app.R, incl. the 'Steal%' = lost/total quirk — coach-confirmable)."""
    empty = {"net_strikes": 0, "steal_pct": None, "shadow_net": 0,
             "shadow_steal_pct": None, "heart_net": 0, "heart_loss_pct": None,
             "waste_net": 0, "waste_steal_pct": None}
    if df.empty:
        return empty
    f = add_framing_cols(df) if "CallType" not in df.columns else df
    f = f[f["plate_loc_side"].notna() & f["plate_loc_height"].notna()]
    if f.empty:
        return empty
    ct, zone = f["CallType"], f["Zone"]
    stolen = ct == "Stolen Strike"
    lost = ct == "Lost Strike"
    total = len(f)
    shadow = zone == "Shadow"
    heart = zone == "Heart"
    waste = zone.isin(["Waste", "Chase"])
    return {
        "net_strikes": int(stolen.sum() - lost.sum()),
        "steal_pct": _pct(lost.sum(), total),
        "shadow_net": int((stolen & shadow).sum() - (lost & shadow).sum()),
        "shadow_steal_pct": _pct((stolen & shadow).sum(), shadow.sum()),
        "heart_net": int((stolen & heart).sum() - (lost & heart).sum()),
        "heart_loss_pct": _pct((lost & heart).sum(), heart.sum()),
        "waste_net": int((stolen & waste).sum() - (lost & waste).sum()),
        "waste_steal_pct": _pct((lost & waste).sum(), waste.sum()),
    }


def framing_season_tiles(catcher_id: int) -> dict:
    """Season sidebar tiles: games, pitches, net strikes, steal% (SQL aggregate,
    sibling-id union). InZone box mirrors _in_zone in SQL."""
    ids = _sibling_catcher_ids(catcher_id)
    marks, params = _in_clause(ids)
    df = query_df(
        f"""
        SELECT COUNT(DISTINCT game_id) AS games,
               COUNT(*) AS pitches,
               SUM(pitch_call='StrikeCalled'
                   AND NOT (ABS(plate_loc_side*12) <= 10
                            AND ABS(plate_loc_height*12 - 30) <= 13)) AS stolen,
               SUM(pitch_call='BallCalled'
                   AND (ABS(plate_loc_side*12) <= 10
                        AND ABS(plate_loc_height*12 - 30) <= 13)) AS lost,
               SUM(plate_loc_side IS NOT NULL
                   AND plate_loc_height IS NOT NULL) AS valid_loc
          FROM fact_tm_game_pitch
         WHERE catcher_id IN ({marks})
        """,
        params,
    )
    if df.empty:
        return {"games": "—", "pitches": "—", "net_strikes": "—", "steal_pct": "—"}
    r = df.iloc[0]
    stolen = int(r["stolen"] or 0)
    lost = int(r["lost"] or 0)
    valid_loc = int(r["valid_loc"] or 0)
    steal = _pct(lost, valid_loc)
    return {
        "games": str(int(r["games"] or 0)),
        "pitches": str(int(r["pitches"] or 0)),
        "net_strikes": str(stolen - lost),
        "steal_pct": "—" if steal is None else f"{steal}%",
    }


CS_RESULTS = {"StolenBase", "CaughtStealing"}


def caught_stealing_events(df: pd.DataFrame) -> pd.DataFrame:
    """Stolen-base attempts charged on this catcher's pitches. PROVISIONAL v1."""
    if df.empty or "play_result" not in df.columns:
        return df.iloc[0:0].copy() if not df.empty else df.copy()
    out = df[df["play_result"].isin(CS_RESULTS)].copy()
    if out.empty:
        return out
    out["Caught"] = out["play_result"] == "CaughtStealing"
    pop = _col(out, "pop_time", "PopTime")
    exch = _col(out, "exchange_time", "ExchangeTime")
    thr = _col(out, "throw_speed", "ThrowSpeed")
    out["pop_time"] = out[pop] if pop else np.nan
    out["exchange_time"] = out[exch] if exch else np.nan
    out["throw_speed"] = out[thr] if thr else np.nan
    return out


def caught_stealing_summary(df: pd.DataFrame) -> dict:
    """Attempts / caught / CS% / avg pop time on caught-stealing events."""
    ev = caught_stealing_events(df)
    n = len(ev)
    if n == 0:
        return {"attempts": 0, "caught": 0, "cs_pct": None, "avg_pop": None}
    caught = int(ev["Caught"].sum())
    pops = ev["pop_time"].dropna()
    return {
        "attempts": n,
        "caught": caught,
        "cs_pct": round(100.0 * caught / n, 1),
        "avg_pop": None if pops.empty else round(float(pops.mean()), 2),
    }
