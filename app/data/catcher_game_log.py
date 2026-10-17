"""Catching Game Log: every pitch LMU catchers received in one game, labeled
the same way as the hitting Game Log (`app.data.game_log.label_pitches`), with
the Catching dashboard's framing (stolen/lost strikes on the rulebook box,
`app.data.catching`), SLAA (called-strike probability, `app.data.called_strike`)
and throwing (pop/exchange/throw velo on steal attempts) measures.

Queries read GAMES (+ the shared video clip sources); everything after the
query is a pure transform so it can be tested without a database.
"""
from __future__ import annotations

import pandas as pd

from app.data import called_strike, catching, game_log
from app.data import pitcher_game_log as pgl
from app.data import video as videodata
from app.data.cache import cached
from app.data.catching_caps import SL_PLUS_MIN_TAKEN
from app.data.pitching_caps import LMU_PITCHER_TEAM
from app.db import query_df

_COLS = game_log._COLS + ", Catcher, CatcherId, PopTime, ExchangeTime, ThrowSpeed"

SHOW_ONLY = [
    ("take", "Takes"), ("called_strike", "Called strikes"), ("called_ball", "Called balls"),
    ("stolen", "Stolen strikes"), ("lost", "Lost strikes"), ("edge", "Borderline (40-60% strike)"),
    ("steal", "Steal attempts"), ("dirt", "Balls in dirt"), ("pa_end", "PA-ending pitch"),
    ("video", "Has video"),
]
_FLAGS = {"take": "is_take", "called_strike": "is_called_strike", "called_ball": "is_called_ball",
          "stolen": "is_stolen", "lost": "is_lost", "edge": "is_edge", "steal": "is_steal",
          "dirt": "is_dirt", "pa_end": "is_pa_end", "video": "has_video"}

lmu_games = pgl.lmu_games  # an LMU catcher is behind the plate exactly when LMU pitches


def add_receiving(df: pd.DataFrame, *, lookup=None) -> pd.DataFrame:
    """Framing / SLAA / throwing columns on a `label_pitches` frame."""
    df = df.copy()
    snake = pd.DataFrame({
        "plate_loc_side": pd.to_numeric(df["PlateLocSide"], errors="coerce"),
        "plate_loc_height": pd.to_numeric(df["PlateLocHeight"], errors="coerce"),
        "pitch_call": df["PitchCall"], "tagged_pitch_type": df["TaggedPitchType"],
    }, index=df.index)
    framed = catching.add_framing_cols(snake)
    df["CallType"] = framed["CallType"]
    df["is_stolen"] = df["CallType"] == "Stolen Strike"
    df["is_lost"] = df["CallType"] == "Lost Strike"
    df["Frame"] = df["CallType"].map({"Stolen Strike": "Stolen", "Lost Strike": "Lost"}).fillna("")
    df["fx"], df["fy"] = framed["_x"], framed["_y"]

    taken = called_strike.is_taken(snake) & snake["plate_loc_side"].notna() \
        & snake["plate_loc_height"].notna()
    p = pd.Series(pd.NA, index=df.index, dtype="Float64")
    if taken.any():
        p[taken] = called_strike.expected_called_strikes(snake[taken], lookup=lookup).values
    df["p_strike"] = p
    df["is_take_scored"] = taken
    df["is_called_strike"] = df["PitchCall"] == "StrikeCalled"
    df["is_called_ball"] = df["PitchCall"].isin({"BallCalled", "BallinDirt"})
    df["strikes_added"] = (df["is_called_strike"].astype(float) - df["p_strike"]).where(taken)
    df["is_edge"] = taken & df["p_strike"].between(0.4, 0.6).fillna(False).astype(bool)
    df["xK"] = [None if pd.isna(v) else f"{round(100 * float(v))}%" for v in df["p_strike"]]
    df["is_steal"] = df["PlayResult"].isin(catching.CS_RESULTS)
    df["is_dirt"] = df["PitchCall"] == "BallinDirt"
    df["Steal"] = df["PlayResult"].map({"StolenBase": "SB", "CaughtStealing": "CS"}).fillna("")
    return df


@cached
def _labeled_pitches(game_id) -> pd.DataFrame:
    raw = query_df(
        f"SELECT {_COLS} FROM GAMES WHERE GameID = :g AND PitcherTeam = :t ORDER BY PitchNo",
        {"g": str(game_id), "t": LMU_PITCHER_TEAM})
    df = game_log.label_pitches(raw)
    if df.empty:
        return df
    df["Catcher"] = df["Catcher"].fillna("").astype(str).str.strip()
    return add_receiving(df)


def game_pitches(game_id, *, with_video: bool = True) -> pd.DataFrame:
    """Every pitch LMU caught in the game, labeled, with video urls looked up
    fresh (see `app.data.game_log.game_pitches` for why they aren't cached)."""
    df = _labeled_pitches(game_id)
    if df.empty or not with_video:
        return df
    try:
        urls = videodata.clip_urls(df["PitchUID"].tolist())
    except Exception:
        urls = {}
    return game_log.attach_video(df, urls)


def filter_pitches(df, *, catcher=None, pitcher=None, batter=None, innings=None, types=None,
                   show_only=None, zones=None) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    shown = game_log.filter_pitches(df, batter=batter, pitcher=pitcher, innings=innings,
                                    types=types, zones=zones)
    if catcher:
        shown = shown[shown["Catcher"] == catcher]
    for key in show_only or []:
        col = _FLAGS.get(key)
        if col in shown:
            shown = shown[shown[col].astype(bool)]
    return shown


def _signed(v: float) -> str:
    return f"{v:+.1f}"


def summary(df: pd.DataFrame | None) -> dict:
    """Receiving + throwing line for the pitches in `df` (unfiltered rows)."""
    keys = ["P", "Taken", "Called K", "xK", "SLAA", "SL+", "Stolen", "Lost", "Net", "Dirt",
            "SB", "CS", "CS%", "Avg Pop"]
    if df is None or df.empty:
        return {k: "—" for k in keys}
    taken = df[df["is_take_scored"]]
    actual = int(taken["is_called_strike"].sum())
    expected = float(pd.to_numeric(taken["p_strike"], errors="coerce").sum())
    n_taken = len(taken)
    stolen, lost = int(df["is_stolen"].sum()), int(df["is_lost"].sum())
    steals = df[df["is_steal"]]
    cs = int((steals["PlayResult"] == "CaughtStealing").sum())
    pops = pd.to_numeric(steals["PopTime"], errors="coerce").dropna()
    sl_plus = (f"{100 * actual / expected:.0f}"
               if n_taken >= SL_PLUS_MIN_TAKEN and expected > 0 else "—")
    return {
        "P": str(len(df)),
        "Taken": str(n_taken),
        "Called K": str(actual),
        "xK": f"{expected:.1f}",
        "SLAA": _signed(actual - expected) if n_taken else "—",
        "SL+": sl_plus,
        "Stolen": str(stolen),
        "Lost": str(lost),
        "Net": f"{stolen - lost:+d}",
        "Dirt": str(int(df["is_dirt"].sum())),
        "SB": str(len(steals) - cs),
        "CS": str(cs),
        "CS%": game_log._pct(cs, len(steals)),
        "Avg Pop": "—" if pops.empty else f"{pops.mean():.2f}",
    }


def catcher_line(df: pd.DataFrame, catcher: str) -> str:
    """'96 P · SLAA +2.4 · 3 stolen / 1 lost · 0-for-1 CS' for one catcher's game."""
    s = summary(df[df["Catcher"] == catcher])
    if s["P"] == "—":
        return ""
    steal = f" · {s['CS']} CS / {s['SB']} SB" if s["SB"] != "0" or s["CS"] != "0" else ""
    return f"{s['P']} P · SLAA {s['SLAA']} · {s['Stolen']} stolen / {s['Lost']} lost{steal}"
