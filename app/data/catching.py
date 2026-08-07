"""Pure catching transforms for the catching stats dashboard (CAPS era).

Runtime data access for catching now lives in `app.data.catching_caps` (reads
the CAPS `GAMES` table). This module is the kept home for the DB-free, pure
transforms the catching dashboard tabs import -- framing derivation/summary and
caught-stealing derivation/summary/trend -- plus `_pct`, which `catching_caps`
reuses. The former warehouse-query oracles (fact_tm_game_pitch / dim_tm_game /
tm_player / tm_team) were removed in Phase 3 when the warehouse was dropped.

Metric definitions for framing / blocking / throws are PROVISIONAL v1 (docstring'd)
and coach-confirmable once the legacy R catcher app under src/ is available.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.data.hitting import attack_zone


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


def caught_stealing_trend(df: pd.DataFrame) -> pd.DataFrame:
    """Per-game-date caught-stealing trend. PROVISIONAL v1.

    Columns: game_date, attempts, caught, cs_pct, avg_pop. Only dates with >=1
    stolen-base attempt; sorted by date. Sparse by nature (few attempts/season).
    """
    cols = ["game_date", "attempts", "caught", "cs_pct", "avg_pop"]
    ev = caught_stealing_events(df)
    if ev.empty or "game_date" not in ev.columns:
        return pd.DataFrame(columns=cols)
    rows = []
    for d, sub in ev.groupby("game_date"):
        n = len(sub)
        c = int(sub["Caught"].sum())
        pops = sub["pop_time"].dropna()
        rows.append({
            "game_date": d, "attempts": n, "caught": c,
            "cs_pct": round(100.0 * c / n, 1),
            "avg_pop": None if pops.empty else round(float(pops.mean()), 2),
        })
    out = pd.DataFrame(rows, columns=cols).sort_values("game_date").reset_index(drop=True)
    # Keep avg_pop as Python None on pop-less rows: pandas silently coerces a
    # float64 column's None -> NaN, but callers (and tests) expect None.
    out["avg_pop"] = out["avg_pop"].astype(object).where(out["avg_pop"].notna(), None)
    return out
