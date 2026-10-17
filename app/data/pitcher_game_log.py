"""Pitching Game Log: every pitch LMU pitchers threw in one game, labeled the
same way as the hitting Game Log (`app.data.game_log.label_pitches`), with the
coaches' pitching KPIs from `app.data.pitching`.

Queries read GAMES (+ the shared video clip sources); everything after the
query is a pure transform so it can be tested without a database.
"""
from __future__ import annotations

import pandas as pd

from app.data import game_log, pitching
from app.data import video as videodata
from app.data.cache import cached
from app.data.hitting_caps import LMU_TEAM_ID, _game_label
from app.data.pitching_caps import LMU_PITCHER_TEAM
from app.db import query_df

_COLS = game_log._COLS + ", RelSide, RelHeight, Extension"

SHOW_ONLY = [
    ("pa_end", "PA-ending pitch"), ("strike", "Strikes"), ("ball", "Balls"),
    ("swing", "Swings"), ("whiff", "Whiffs"), ("chase", "Chases"), ("bip", "Balls in play"),
    ("hard", f"Hard hit ({game_log.HARD_HIT_EV:.0f}+)"), ("first", "First pitch of PA"),
    ("two_strike", "Two strikes"), ("video", "Has video"),
]
_BALL_CALLS = {"BallCalled", "BallinDirt", "BallIntentional", "AutomaticBall", "HitByPitch"}


@cached
def lmu_games(start, end) -> pd.DataFrame:
    """Games in [start, end] where an LMU pitcher threw, newest first."""
    df = query_df(
        "SELECT DISTINCT GameID AS game_id, Date AS game_date, HomeTeam, AwayTeam, "
        "HomeTeamForeignID, GameType FROM GAMES "
        "WHERE PitcherTeam = :t AND Date BETWEEN :s AND :e",
        {"t": LMU_PITCHER_TEAM, "s": str(start), "e": str(end)})
    if df.empty:
        return pd.DataFrame(columns=["game_id", "game_date", "GameLabel"])
    df["game_id"] = df["game_id"].astype(str)
    df = (df.drop_duplicates("game_id")
            .sort_values(["game_date", "game_id"], ascending=[False, False])
            .reset_index(drop=True))
    lmu_home = df["HomeTeamForeignID"] == LMU_TEAM_ID
    loc = lmu_home.map({True: "vs", False: "@"})
    opp = df["AwayTeam"].where(lmu_home, df["HomeTeam"])
    df["GameLabel"] = [_game_label(d, lc, o) + (f" ({gt})" if isinstance(gt, str) and gt
                                                and gt != "Regular" else "")
                       for d, lc, o, gt in zip(df["game_date"], loc, opp, df["GameType"])]
    return df[["game_id", "game_date", "GameLabel"]]


@cached
def _labeled_pitches(game_id) -> pd.DataFrame:
    raw = query_df(
        f"SELECT {_COLS} FROM GAMES WHERE GameID = :g AND PitcherTeam = :t ORDER BY PitchNo",
        {"g": str(game_id), "t": LMU_PITCHER_TEAM})
    df = game_log.label_pitches(raw)
    if df.empty:
        return df
    df["is_strike"] = ~df["PitchCall"].isin(_BALL_CALLS)
    df["is_ball"] = df["PitchCall"].isin(_BALL_CALLS)
    df["is_first"] = df["PitchofPA"] == 1
    for src, dst in (("SpinRate", "Spin"), ("InducedVertBreak", "IVB"), ("HorzBreak", "HB")):
        vals = pd.to_numeric(df[src], errors="coerce").round(0 if src == "SpinRate" else 1)
        df[dst] = [None if pd.isna(v) else (int(v) if src == "SpinRate" else float(v))
                   for v in vals]
    return df


def game_pitches(game_id, *, with_video: bool = True) -> pd.DataFrame:
    """Every LMU pitch in the game, labeled, with video urls looked up fresh
    (see `app.data.game_log.game_pitches` for why they aren't cached)."""
    df = _labeled_pitches(game_id)
    if df.empty or not with_video:
        return df
    try:
        urls = videodata.clip_urls(df["PitchUID"].tolist())
    except Exception:
        urls = {}
    return game_log.attach_video(df, urls)


def filter_pitches(df, *, batter=None, pitcher=None, innings=None, types=None,
                   show_only=None, zones=None) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    shown = game_log.filter_pitches(df, batter=batter, pitcher=pitcher, innings=innings,
                                    types=types, zones=zones,
                                    show_only=[k for k in show_only or []
                                               if k not in ("strike", "ball", "first")])
    for key, col in (("strike", "is_strike"), ("ball", "is_ball"), ("first", "is_first")):
        if key in (show_only or []):
            shown = shown[shown[col]]
    return shown


def _kpi_frame(df: pd.DataFrame) -> pd.DataFrame:
    """`df` in the snake_case shape `app.data.pitching`'s KPI functions read.
    game_id carries the half too: in an intrasquad both halves are LMU pitchers,
    so (inning, PA of inning) alone would merge two different at-bats."""
    return pd.DataFrame({
        "game_id": df["GameID"].astype(str) + "|" + df["half"].fillna("").astype(str),
        "inning": df["Inning"], "pa_of_inning": df["PAofInning"],
        "pitch_of_pa": df["PitchofPA"], "balls": df["Balls"], "strikes": df["Strikes"],
        "pitch_call": df["PitchCall"], "korbb": df["KorBB"], "play_result": df["PlayResult"],
        "outs_on_play": pd.to_numeric(df["OutsOnPlay"], errors="coerce"),
        "runs_scored": pd.to_numeric(df["RunsScored"], errors="coerce").fillna(0),
        "exit_speed": pd.to_numeric(df["ExitSpeed"], errors="coerce"),
        "rel_speed": pd.to_numeric(df["RelSpeed"], errors="coerce"),
        "batter_side": df["BatterSide"],
    })


def _outs(k: pd.DataFrame) -> int:
    # Trackman leaves OutsOnPlay at 0 on most strikeouts (it's a batted-ball
    # field), so a K adds an out unless its row already carries one.
    oop = k["outs_on_play"].fillna(0)
    return int(oop.sum() + ((k["korbb"] == "Strikeout") & (oop == 0)).sum())


def _pct(v) -> str:
    return f"{v:.0f}%"


def summary(df: pd.DataFrame | None) -> dict:
    """Outing line for the pitches in `df` (unfiltered rows)."""
    keys = ["IP", "P", "BF", "H", "R", "K", "BB", "Strike%", "FPS%", "E+A%", "2K Kill%",
            "Whiff%", "Chase%", "Max Velo"]
    if df is None or df.empty:
        return {k: "—" for k in keys}
    k = _kpi_frame(df)
    line = pitching.header_stat_line(k)
    out_zone = df["Zone"].isin(["Chase", "Waste"])
    swings = int(df["is_swing"].sum())
    return {
        "IP": pitching.format_ip(_outs(k)),
        "P": str(line["pitches"]),
        "BF": str(line["bf"]),
        "H": str(line["h"]),
        "R": str(line["r"]),
        "K": str(line["so"]),
        "BB": str(line["bb"]),
        "Strike%": _pct(pitching.strike_pct(k)[0]),
        "FPS%": _pct(pitching.fps_pct(k)[0]),
        "E+A%": _pct(pitching.ea_pct(k)[0]),
        "2K Kill%": _pct(pitching.twok_kill_pct(k)[0]),
        "Whiff%": game_log._pct(int(df["is_whiff"].sum()), swings),
        "Chase%": game_log._pct(int((df["is_swing"] & out_zone).sum()), int(out_zone.sum())),
        "Max Velo": "—" if line["max_velo"] is None else f"{line['max_velo']:.1f}",
    }


def pitcher_line(df: pd.DataFrame, pitcher: str) -> str:
    """'2.1 IP · 38 P · 3 K · 1 BB · 2 H · 66% strikes' for one pitcher's game."""
    s = summary(df[df["Pitcher"] == pitcher])
    if s["P"] == "—":
        return ""
    return (f"{s['IP']} IP · {s['P']} P · {s['K']} K · {s['BB']} BB · {s['H']} H · "
            f"{s['Strike%']} strikes")


def same_type(df: pd.DataFrame, pitcher: str, pitch_type: str) -> pd.DataFrame:
    """This pitcher's pitches of one tagged type this game (movement/release context)."""
    return df[(df["Pitcher"] == pitcher) & (df["TaggedPitchType"] == pitch_type)]
