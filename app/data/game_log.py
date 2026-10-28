"""Hitting Game Log: every pitch LMU hitters saw in one game, in order, with
the per-pitch and per-PA labels the Game Log page shows.

Queries read GAMES (+ the shared video clip sources via
`app.data.video.clip_urls`); everything after the query is a pure transform of
the pitch frame so it can be tested without a database.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.data import video as videodata
from app.data.cache import cached
from app.data.hitting import CHASE_ZONES, PITCH_ABBR, attack_zone, qab_frame
from app.data.hitting_caps import LMU_BATTER_TEAM, LMU_TEAM_ID, _game_label
from app.db import query_df

_COLS = (
    "PitchUID, PitchNo, Inning, `Top.Bottom` AS half, Outs, Balls, Strikes, "
    "PAofInning, PitchofPA, Batter, BatterId, BatterSide, Pitcher, PitcherThrows, "
    "TaggedPitchType, PitchCall, KorBB, TaggedHitType, PlayResult, RunsScored, "
    "OutsOnPlay, RelSpeed, SpinRate, InducedVertBreak, HorzBreak, VertApprAngle, "
    "PlateLocSide, PlateLocHeight, ExitSpeed, Angle, Distance, Bearing, HangTime, "
    "GameID"
)

# Newer Trackman exports split FoulBall into Fieldable/NotFieldable;
# app.data.hitting.SWING_CALLS predates that split.
SWING_CALLS = {"StrikeSwinging", "InPlay", "FoulBall", "FoulBallFieldable",
               "FoulBallNotFieldable"}
HARD_HIT_EV = 95.0

_HIT_ABBR = {"GroundBall": "GB", "LineDrive": "LD", "FlyBall": "FB",
             "Popup": "PU", "PopUp": "PU", "Bunt": "BU"}
_PLAY_ABBR = {"Single": "1B", "Double": "2B", "Triple": "3B", "HomeRun": "HR",
              "Out": "OUT", "Error": "E", "FieldersChoice": "FC",
              "Sacrifice": "SAC", "SacrificeFly": "SF", "SacrificeBunt": "SAC"}
_HITS = {"Single", "Double", "Triple", "HomeRun"}

# "Show only" filter keys -> label; combined with AND so coaches can narrow
# (e.g. Chases + Two strikes = two-strike chases).
SHOW_ONLY = [
    ("pa_end", "PA-ending pitch"), ("swing", "Swings"), ("take", "Takes"),
    ("whiff", "Whiffs"), ("chase", "Chases"), ("bip", "Balls in play"),
    ("hard", f"Hard hit ({HARD_HIT_EV:.0f}+)"), ("two_strike", "Two strikes"),
    ("video", "Has video"),
]


# Zones 1-13 on the catcher's view: 1-9 are the strike-zone grid numbered like
# GAMES.Zone (1 = top row on the +PlateLocSide side), 10-13 the four out-of-zone
# corners (10 up/+side, 11 up/-side, 12 down/+side, 13 down/-side).
_SZ_X, _SZ_Y0, _SZ_Y1 = 0.83, 1.5, 3.5
# Words follow the hitter: +PlateLocSide is away from a righty, in on a lefty.
ZONE_WORDS = ["Up & In", "Up", "Up & Away", "In", "Middle", "Away", "Down & In", "Down",
              "Down & Away", "Chase Up & In", "Chase Up & Away", "Chase Down & In",
              "Chase Down & Away"]


def _blank(v) -> bool:
    return v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NA \
        or (isinstance(v, str) and v in ("", "Undefined"))


# ------------------------------- queries ---------------------------------

@cached
def lmu_games(start, end) -> pd.DataFrame:
    """Games in [start, end] where an LMU hitter batted, newest first."""
    df = query_df(
        "SELECT DISTINCT GameID AS game_id, Date AS game_date, HomeTeam, AwayTeam, "
        "HomeTeamForeignID, GameType FROM GAMES "
        "WHERE BatterTeam = :t AND Date BETWEEN :s AND :e",
        {"t": LMU_BATTER_TEAM, "s": str(start), "e": str(end)})
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
        f"SELECT {_COLS} FROM GAMES WHERE GameID = :g AND BatterTeam = :t ORDER BY PitchNo",
        {"g": str(game_id), "t": LMU_BATTER_TEAM})
    return label_pitches(raw)


def game_pitches(game_id, *, with_video: bool = True) -> pd.DataFrame:
    """Every pitch to an LMU hitter in the game, labeled (see `label_pitches`),
    with the hitter-angle video urls attached."""
    # Video urls are looked up fresh: clip uploads don't bump the data version, so
    # caching them kept a game showing only the angles uploaded before its first view.
    df = _labeled_pitches(game_id)
    if df.empty or not with_video:
        return df
    try:
        urls = videodata.clip_urls(df["PitchUID"].tolist())
    except Exception:
        urls = {}
    return attach_video(df, urls)


# ------------------------------ transforms -------------------------------

def zone13(side_ft, height_ft) -> int | None:
    if _blank(side_ft) or _blank(height_ft) or pd.isna(side_ft) or pd.isna(height_ft):
        return None
    x, y = float(side_ft), float(height_ft)
    if abs(x) <= _SZ_X and _SZ_Y0 <= y <= _SZ_Y1:
        third_x, third_y = 2 * _SZ_X / 3, (_SZ_Y1 - _SZ_Y0) / 3
        col = 0 if x > _SZ_X - third_x else (1 if x >= -_SZ_X + third_x else 2)
        row = 0 if y > _SZ_Y1 - third_y else (1 if y >= _SZ_Y0 + third_y else 2)
        return 1 + 3 * row + col
    up = y >= (_SZ_Y0 + _SZ_Y1) / 2
    return (10 if up else 12) + (0 if x >= 0 else 1)


def zone_word(zone, batter_side) -> str:
    """Hitter-relative name for a `zone13` number ('' when unknown)."""
    if zone is None or pd.isna(zone):
        return ""
    z = int(zone)
    righty = batter_side != "Left"
    if z >= 10:
        plus_side = z in (10, 12)
        horiz = "Away" if plus_side == righty else "In"
        return f"Chase {'Up' if z in (10, 11) else 'Down'} & {horiz}"
    row, col = divmod(z - 1, 3)
    horiz = "" if col == 1 else ("Away" if (col == 0) == righty else "In")
    vert = ("Up", "", "Down")[row]
    return " & ".join(p for p in (vert, horiz) if p) or "Middle"


def pa_result(last: dict) -> str:
    """Scorebook-style code for a PA's final pitch ('LD-2B', 'K-Swing', 'BB')."""
    korbb, call, play = last.get("KorBB"), last.get("PitchCall"), last.get("PlayResult")
    if korbb == "Strikeout":
        return "K-Look" if call == "StrikeCalled" else "K-Swing"
    if korbb == "Walk":
        return "BB"
    if call == "HitByPitch":
        return "HBP"
    if call == "InPlay":
        hit = "" if _blank(last.get("TaggedHitType")) else _HIT_ABBR.get(last["TaggedHitType"], "")
        res = "" if _blank(play) else _PLAY_ABBR.get(play, str(play))
        return "-".join(p for p in (hit, res) if p) or "In Play"
    return ""


def swing_decision(call, zone) -> str:
    """Swing/take judged against the Heart/Shadow/Chase/Waste attack zones."""
    if not zone:
        return ""
    swung = call in SWING_CALLS
    if call == "HitByPitch":
        return ""
    if zone == "Heart":
        return "Heart swing" if swung else "Heart take"
    if zone == "Shadow":
        return "Shadow swing" if swung else "Shadow take"
    return "Chase" if swung else "Good take"


def _pitch_result(call, play, pa_code, is_last) -> str:
    if call == "InPlay" and pa_code:
        return pa_code
    if is_last and pa_code in ("K-Swing", "K-Look", "BB", "HBP"):
        return pa_code
    return videodata._result(call, play)


def label_pitches(raw: pd.DataFrame) -> pd.DataFrame:
    """Adds PA keys/labels, swing flags, zone, xBA-ready fields to a raw GAMES
    pitch frame (one row per pitch, PitchNo order)."""
    if raw is None or raw.empty:
        return pd.DataFrame()
    df = raw.sort_values("PitchNo").reset_index(drop=True).copy()
    half = df["half"].fillna("").astype(str)
    df["pa_key"] = (half + "|" + df["Inning"].astype(str) + "|" + df["PAofInning"].astype(str))
    df["pa_seq"] = pd.factorize(df["pa_key"])[0] + 1
    last_idx = df.groupby("pa_key")["PitchofPA"].idxmax()
    df["is_pa_end"] = df.index.isin(last_idx.values)
    codes = {df.at[i, "pa_key"]: pa_result(df.loc[i].to_dict()) for i in last_idx}
    df["pa_code"] = df["pa_key"].map(codes).fillna("")

    df["Zone"] = [attack_zone(s, h) for s, h in zip(df["PlateLocSide"], df["PlateLocHeight"])]
    df["Z"] = pd.array([zone13(s, h) for s, h in zip(df["PlateLocSide"], df["PlateLocHeight"])],
                       dtype="Int64")
    df["ZoneWord"] = [zone_word(z, b) for z, b in zip(df["Z"], df["BatterSide"])]
    df["is_swing"] = df["PitchCall"].isin(SWING_CALLS)
    df["is_take"] = df["PitchCall"].isin({"StrikeCalled", "BallCalled", "BallinDirt"})
    df["is_whiff"] = df["PitchCall"] == "StrikeSwinging"
    df["is_chase"] = df["is_swing"] & df["Zone"].isin(CHASE_ZONES)
    df["is_bip"] = df["PitchCall"] == "InPlay"
    df["is_hard"] = df["is_bip"] & (pd.to_numeric(df["ExitSpeed"], errors="coerce") >= HARD_HIT_EV)
    df["decision"] = [swing_decision(c, z) for c, z in zip(df["PitchCall"], df["Zone"])]

    df["InnLabel"] = [f"{int(i)}{'▲' if h == 'Top' else '▼' if h == 'Bottom' else ''}"
                      for i, h in zip(df["Inning"], half)]
    df["Count"] = df["Balls"].astype("Int64").astype(str) + "-" + df["Strikes"].astype("Int64").astype(str)
    df["Type"] = [PITCH_ABBR.get(t, "" if _blank(t) else str(t)) for t in df["TaggedPitchType"]]
    df["Result"] = [_pitch_result(c, p, code, last) for c, p, code, last
                    in zip(df["PitchCall"], df["PlayResult"], df["pa_code"], df["is_pa_end"])]
    df["PA"] = np.where(df["is_pa_end"], df["pa_code"], "")
    for src, dst, nd in (("RelSpeed", "Velo", 1), ("ExitSpeed", "EV", 1),
                         ("Angle", "LA", 0), ("Distance", "Dist", 0)):
        vals = pd.to_numeric(df[src], errors="coerce").round(nd)
        df[dst] = [None if pd.isna(v) else (float(v) if nd else int(v)) for v in vals]
    df["Outs"] = df["Outs"].astype("Int64")
    return df


def attach_video(df: pd.DataFrame, urls: dict) -> pd.DataFrame:
    """Adds the url_* columns + 🎥 marker the shared video component reads."""
    df = df.copy()
    for angle, col in videodata.URL_COL.items():
        df[col] = [urls.get(u, {}).get(angle) for u in df["PitchUID"]]
    df["has_video"] = df["PitchUID"].map(lambda u: bool(urls.get(u)))
    df["Vid"] = np.where(df["has_video"], "🎥", "")
    df["batter_side"] = df["BatterSide"]
    df["pitcher_side"] = df["PitcherThrows"]
    return df


def filter_pitches(df: pd.DataFrame, *, batter=None, pitcher=None, innings=None,
                   types=None, show_only=None, zones=None) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    m = pd.Series(True, index=df.index)
    if batter:
        m &= df["Batter"] == batter
    if pitcher:
        m &= df["Pitcher"] == pitcher
    if innings:
        m &= df["Inning"].isin([int(i) for i in innings])
    if types:
        m &= df["TaggedPitchType"].isin(types)
    if zones:
        m &= df["ZoneWord"].isin(zones)
    flag = {"pa_end": "is_pa_end", "swing": "is_swing", "take": "is_take",
            "whiff": "is_whiff", "chase": "is_chase", "bip": "is_bip",
            "hard": "is_hard", "video": "has_video"}
    for key in show_only or []:
        if key == "two_strike":
            m &= df["Strikes"] == 2
        elif key in flag and flag[key] in df:
            m &= df[flag[key]].astype(bool)
    return df[m]


def _pct(n, d) -> str:
    return "—" if not d else f"{round(100 * n / d)}%"


def summary(df: pd.DataFrame) -> dict:
    """Game-at-a-glance line for the hitters in `df` (unfiltered pitch rows)."""
    keys = ["PA", "H", "XBH", "BB", "K", "QAB%", "Hard-Hit%", "Avg EV", "Chase%", "Whiff%"]
    if df is None or df.empty:
        return {k: "—" for k in keys}
    ends = df[df["is_pa_end"] & (df["pa_code"] != "")]
    hits = ends["PlayResult"].isin(_HITS)
    # qab_frame keys PAs on (GameID, Inning, PAofInning), which collides
    # across halves when both halves are LMU hitters (intrasquad scrimmages).
    qab = 0
    for _, half in df.groupby(df["half"].fillna("")):
        q = qab_frame(half)
        qab += int(q.loc[q.index.isin(ends.index), "QAB"].sum())
    bip = df[df["is_bip"]]
    ev = pd.to_numeric(bip["ExitSpeed"], errors="coerce").dropna()
    out_zone = df["Zone"].isin(CHASE_ZONES)
    return {
        "PA": str(len(ends)),
        "H": str(int(hits.sum())),
        "XBH": str(int(ends["PlayResult"].isin({"Double", "Triple", "HomeRun"}).sum())),
        "BB": str(int((ends["pa_code"] == "BB").sum())),
        "K": str(int(ends["pa_code"].isin({"K-Swing", "K-Look"}).sum())),
        "QAB%": _pct(qab, len(ends)),
        "Hard-Hit%": _pct(int((ev >= HARD_HIT_EV).sum()), len(ev)),
        "Avg EV": "—" if ev.empty else f"{ev.mean():.1f}",
        "Chase%": _pct(int((df["is_swing"] & out_zone).sum()), int(out_zone.sum())),
        "Whiff%": _pct(int(df["is_whiff"].sum()), int(df["is_swing"].sum())),
    }


def batter_line(df: pd.DataFrame, batter: str) -> str:
    """'2-for-4 · LD-2B, BB, K-Swing, GB-OUT, FB-1B' for one hitter's game."""
    ends = df[(df["Batter"] == batter) & df["is_pa_end"] & (df["pa_code"] != "")]
    if ends.empty:
        return ""
    hits = int(ends["PlayResult"].isin(_HITS).sum())
    non_ab = ends["pa_code"].isin({"BB", "HBP"}) | ends["PlayResult"].astype(str).str.startswith("Sac")
    return f"{hits}-for-{int((~non_ab).sum())} · " + ", ".join(ends["pa_code"])


def bip_xy(df: pd.DataFrame) -> pd.DataFrame:
    """Spray-chart frame in `charts.spray_fig`'s column shape."""
    d = df[df["is_bip"]].copy()
    br = np.radians(pd.to_numeric(d["Bearing"], errors="coerce"))
    dist = pd.to_numeric(d["Distance"], errors="coerce")
    d["x"] = np.sin(br) * dist
    d["y"] = np.cos(br) * dist
    d["hit_type"] = d["TaggedHitType"].fillna("Undefined").replace("", "Undefined")
    d["distance"] = dist
    d["exit_speed"] = pd.to_numeric(d["ExitSpeed"], errors="coerce")
    return d
