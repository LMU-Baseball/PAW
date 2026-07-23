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

# Takes = no-swing pitch calls used for framing.
# Verified warehouse pitch_call values (see pitching.py notes): StrikeCalled,
# BallCalled, BallinDirt, BallIntentional, AutomaticBall. HitByPitch is a
# dead-ball / no-call and is intentionally excluded from framing.
_TAKE_CALLS = {
    "StrikeCalled", "BallCalled", "BallinDirt",
    "BallIntentional", "AutomaticBall",
}
_STRIKE_CALLS = {"StrikeCalled"}

# Blocking: dirt / passed / wild classifiers (provisional).
_DIRT_CALLS = {"BallinDirt"}
_PASSED_WILD = {"PassedBall", "WildPitch"}
_LOW_BALL_CALLS = {"BallCalled", "BallinDirt"}


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


def games_for_catcher(catcher_id: int) -> pd.DataFrame:
    """A catcher's games, newest first. GameLabel = 'YYYY-MM-DD vs/@ OPP'."""
    ids = _sibling_catcher_ids(catcher_id)
    marks, params = _in_clause(ids)
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
         WHERE f.catcher_id IN ({marks})
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


def season_summary(catcher_id: int) -> dict:
    """Coarse season tiles: games caught, pitches, framing CS%, block %.

    Computed with SQL aggregates (does NOT pull every pitch into pandas).
    """
    ids = _sibling_catcher_ids(catcher_id)
    marks, params = _in_clause(ids)
    df = query_df(
        f"""
        SELECT COUNT(DISTINCT game_id) AS games,
               COUNT(*) AS pitches,
               SUM(pitch_call = 'StrikeCalled') AS called_strikes,
               SUM(pitch_call IN ('StrikeCalled','BallCalled','BallinDirt',
                                  'BallIntentional','AutomaticBall')) AS takes,
               SUM(pitch_call = 'BallinDirt') AS dirt_calls,
               SUM(play_result IN ('PassedBall','WildPitch')) AS passed_wild
          FROM fact_tm_game_pitch
         WHERE catcher_id IN ({marks})
        """,
        params,
    )

    def _s(v):
        return "—" if v is None or (isinstance(v, float) and pd.isna(v)) else str(int(v))

    if df.empty:
        return {"games": "—", "pitches": "—", "cs_pct": "—", "block_pct": "—"}
    r = df.iloc[0]
    takes = int(r["takes"] or 0)
    cs = int(r["called_strikes"] or 0)
    dirt = int(r["dirt_calls"] or 0)
    pw = int(r["passed_wild"] or 0)
    # Dirt events ≈ BallinDirt calls + passed/wild results; blocked ≈ dirt calls
    # that weren't also tagged passed/wild (provisional SQL mirror of transforms).
    block_denom = dirt + pw
    cs_pct = "—" if takes == 0 else f"{round(100.0 * cs / takes, 1)}%"
    block_pct = ("—" if block_denom == 0
                 else f"{round(100.0 * dirt / block_denom, 1)}%")
    return {
        "games": _s(r["games"]),
        "pitches": _s(r["pitches"]),
        "cs_pct": cs_pct,
        "block_pct": block_pct,
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


def takes(df: pd.DataFrame) -> pd.DataFrame:
    """Non-swing pitches used for framing analysis."""
    if df.empty or "pitch_call" not in df.columns:
        return df.iloc[0:0].copy() if not df.empty else df.copy()
    mask = df["pitch_call"].isin(_TAKE_CALLS)
    out = df.loc[mask].copy()
    if "plate_loc_side" in out.columns and "plate_loc_height" in out.columns:
        out["Zone"] = [
            attack_zone(s, h)
            for s, h in zip(out["plate_loc_side"], out["plate_loc_height"])
        ]
    else:
        out["Zone"] = ""
    out["is_strike"] = out["pitch_call"].isin(_STRIKE_CALLS)
    return out


def framing_by_zone(df: pd.DataFrame) -> pd.DataFrame:
    """Called-strike % by attack zone on takes. PROVISIONAL v1."""
    t = takes(df)
    zones = ["Heart", "Shadow", "Chase", "Waste"]
    rows = []
    for z in zones:
        sub = t[t["Zone"] == z] if not t.empty else t
        n = len(sub)
        cs = int(sub["is_strike"].sum()) if n else 0
        pct = round(100.0 * cs / n, 1) if n else None
        rows.append({"Zone": z, "Takes": n, "CalledStrikes": cs, "CS%": pct})
    return pd.DataFrame(rows)


def framing_overall(df: pd.DataFrame) -> dict:
    t = takes(df)
    n = len(t)
    if n == 0:
        return {"takes": 0, "called_strikes": 0, "cs_pct": None}
    cs = int(t["is_strike"].sum())
    return {"takes": n, "called_strikes": cs, "cs_pct": round(100.0 * cs / n, 1)}


def framing_shadow(df: pd.DataFrame) -> dict:
    """Called-strike % on Shadow-zone takes only (most coach-relevant)."""
    t = takes(df)
    if t.empty:
        return {"takes": 0, "called_strikes": 0, "cs_pct": None}
    sub = t[t["Zone"] == "Shadow"]
    n = len(sub)
    if n == 0:
        return {"takes": 0, "called_strikes": 0, "cs_pct": None}
    cs = int(sub["is_strike"].sum())
    return {"takes": n, "called_strikes": cs, "cs_pct": round(100.0 * cs / n, 1)}


def framing_by_batter_side(df: pd.DataFrame) -> pd.DataFrame:
    """Called-strike % on takes split by batter_side (L/R)."""
    t = takes(df)
    rows = []
    for side, label in (("Left", "vs LHH"), ("Right", "vs RHH")):
        if t.empty or "batter_side" not in t.columns:
            sub = t.iloc[0:0]
        else:
            sub = t[t["batter_side"] == side]
        n = len(sub)
        cs = int(sub["is_strike"].sum()) if n else 0
        pct = round(100.0 * cs / n, 1) if n else None
        rows.append({"Split": label, "Takes": n, "CalledStrikes": cs, "CS%": pct})
    return pd.DataFrame(rows)


def _is_dirt_row(r) -> bool:
    call = str(r.get("pitch_call") or "")
    result = str(r.get("play_result") or "")
    if call in _DIRT_CALLS or result in _PASSED_WILD or call in _PASSED_WILD:
        return True
    # Low pitch heuristic (below ~1.5 ft plate height) + ball call.
    h = r.get("plate_loc_height")
    if (h is not None and not pd.isna(h) and float(h) < 1.5
            and call in _LOW_BALL_CALLS):
        return True
    return False


def dirt_events(df: pd.DataFrame) -> pd.DataFrame:
    """Dirt / blocking candidate pitches. PROVISIONAL v1."""
    if df.empty:
        return df.copy()
    mask = df.apply(_is_dirt_row, axis=1)
    out = df.loc[mask].copy()
    if out.empty:
        return out

    def _outcome(r):
        result = str(r.get("play_result") or "")
        call = str(r.get("pitch_call") or "")
        if result in _PASSED_WILD or call in _PASSED_WILD:
            return "Passed/Wild"
        return "Blocked"

    out["BlockOutcome"] = out.apply(_outcome, axis=1)
    return out


def blocking_summary(df: pd.DataFrame) -> dict:
    """Block % among dirt candidates. PROVISIONAL v1."""
    ev = dirt_events(df)
    n = len(ev)
    if n == 0:
        return {"dirt": 0, "blocked": 0, "passed_wild": 0, "block_pct": None}
    blocked = int((ev["BlockOutcome"] == "Blocked").sum())
    pw = n - blocked
    return {
        "dirt": n,
        "blocked": blocked,
        "passed_wild": pw,
        "block_pct": round(100.0 * blocked / n, 1),
    }


def throw_attempts(df: pd.DataFrame) -> pd.DataFrame:
    """Rows with throw timing / speed data."""
    if df.empty:
        return df.copy()
    pop = _col(df, "pop_time", "PopTime")
    thr = _col(df, "throw_speed", "ThrowSpeed", "catcher_throw_speed")
    exch = _col(df, "exchange_time", "ExchangeTime")
    if not any([pop, thr, exch]):
        return df.iloc[0:0].copy()
    mask = pd.Series(False, index=df.index)
    for c in (pop, thr, exch):
        if c:
            mask = mask | df[c].notna()
    out = df.loc[mask].copy()
    out["pop_time"] = out[pop] if pop else np.nan
    out["throw_speed"] = out[thr] if thr else np.nan
    out["exchange_time"] = out[exch] if exch else np.nan
    return out


def throws_summary(df: pd.DataFrame) -> dict:
    """Avg/min pop time + avg exchange + avg throw speed. PROVISIONAL v1."""
    t = throw_attempts(df)
    n = len(t)
    if n == 0:
        return {
            "attempts": 0, "avg_pop": None, "min_pop": None,
            "avg_exchange": None, "avg_throw_speed": None,
        }

    def _avg(col):
        s = t[col].dropna()
        return None if s.empty else round(float(s.mean()), 2)

    def _min(col):
        s = t[col].dropna()
        return None if s.empty else round(float(s.min()), 2)

    return {
        "attempts": n,
        "avg_pop": _avg("pop_time"),
        "min_pop": _min("pop_time"),
        "avg_exchange": _avg("exchange_time"),
        "avg_throw_speed": _avg("throw_speed"),
    }
