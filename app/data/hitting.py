"""Hitting data access + analytical transforms.

Faithful port of the R "Hitter Postgame" app (src/app 1). Queries the legacy
Trackman tables (GAMES / STANDINGS / VIDEO / PLAYERS / NOTES). Selection is
role-agnostic here; the web layer decides whether a user may view a batter
(player = self only, coach = anyone).

Two deliberate deviations from the R output, for the Dash/web layer:
  * Percentage columns are returned as NUMBERS (e.g. 33.3), not "33.3%" strings.
  * Season slash line (BA/SLG/OBP) is a separate hook (`season_slash_line`) —
    the R app scraped these from lmulions.com; we defer that data source.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.db import query_df

# --- shared vocabulary (matches the R recodes / definitions) --------------

FASTBALLS = {
    "Fastball", "Sinker", "Cutter", "Splitter",
    "TwoSeamFastBall", "FourSeamFastBall", "OneSeamFastBall",
}
ZONE_LEVELS = ["Heart", "Shadow", "Chase", "Waste"]
SWING_CALLS = ["StrikeSwinging", "InPlay", "FoulBall"]
TAKE_CALLS = ["StrikeCalled", "BallCalled"]
HIT_TYPES = ["FlyBall", "GroundBall", "LineDrive", "Popup"]  # note R spelling 'Popup'
PITCH_ABBR = {
    "Fastball": "FB", "Curveball": "CB", "Sinker": "SI", "Slider": "SL",
    "Cutter": "CT", "ChangeUp": "CH", "Other": "OT",
}


# ============================ QUERIES =====================================

def hitters_for_game(trackman_game_id: str) -> pd.DataFrame:
    """LMU batters who appeared in a game (coach dropdown)."""
    return query_df(
        """
        SELECT DISTINCT Batter, BatterId
          FROM GAMES
         WHERE GameID = :gid AND BatterTeam = 'LOY_LIO'
         ORDER BY Batter
        """,
        {"gid": trackman_game_id},
    )


def games_for_batter(batter_id: int, season_prefix: str | None = "2025") -> pd.DataFrame:
    """Distinct games a batter appeared in, newest first (player game list).

    `season_prefix` filters GAMES.Date (e.g. '2025'); pass None for all seasons.
    """
    sql = """
        SELECT DISTINCT s.GameName, s.TrackmanGameId, s.LMUScore, s.OppScore
          FROM GAMES g
          JOIN STANDINGS s ON g.GameID = s.TrackmanGameId
         WHERE g.BatterId = :bid
    """
    params: dict = {"bid": batter_id}
    if season_prefix:
        sql += " AND g.Date LIKE :season"
        params["season"] = f"{season_prefix}%"
    sql += " ORDER BY s.TrackmanGameId DESC"
    return query_df(sql, params)


def game_pitches(trackman_game_id: str, batter_id: int) -> pd.DataFrame:
    """Every pitch a batter saw in a game, with video links (the df() reactive)."""
    df = query_df(
        """
        SELECT g.*, v.CenterField, v.HomeLeft, v.HomeRight, v.Broadcast
          FROM GAMES g
          LEFT JOIN VIDEO v ON g.GameID = v.GameID AND g.PitchUID = v.PitchUID
         WHERE g.GameID = :gid AND g.BatterId = :bid
         ORDER BY g.PitchNo
        """,
        {"gid": trackman_game_id, "bid": batter_id},
    )
    return _add_pitch_category(df)


def season_pitches(batter_id: int, season_prefix: str = "2025") -> pd.DataFrame:
    """All of a batter's pitches for a season (season-level tab)."""
    df = query_df(
        "SELECT * FROM GAMES WHERE BatterId = :bid AND Date LIKE :season",
        {"bid": batter_id, "season": f"{season_prefix}%"},
    )
    return _add_pitch_category(df)


def last_27_pa_pitches(batter_id: int, game_name: str,
                       season_prefix: str = "2025") -> pd.DataFrame:
    """Pitches from a batter's most recent 27 plate appearances up to `game_name`.

    Mirrors the R `last_x_df`: order by GameName DESC then game order, number PAs
    across games, keep PA <= 27, and keep only pitches with a plate location.
    """
    df = query_df(
        """
        SELECT g.*, s.GameName
          FROM GAMES g
          LEFT JOIN STANDINGS s ON g.GameID = s.TrackmanGameId
         WHERE s.GameName <= :gname AND g.BatterId = :bid AND g.Date LIKE :season
         ORDER BY s.GameName DESC, g.Inning, g.PAofInning, g.PitchofPA
        """,
        {"gname": game_name, "bid": batter_id, "season": f"{season_prefix}%"},
    )
    if df.empty:
        return df
    # PA numbering is computed over the full ordered set (matches R), then filtered.
    df = df.reset_index(drop=True)
    df["PA"] = (df["PitchofPA"] == 1).cumsum()
    df = df[df["PA"] <= 27]
    df = df[df["PlateLocSide"].notna() & df["PlateLocHeight"].notna()]
    return _add_pitch_category(df)


def game_notes(trackman_game_id: str, batter_id: int) -> str:
    """Coach note for this game/player, or '' if none."""
    df = query_df(
        "SELECT NOTES FROM NOTES WHERE GAME_ID = :gid AND PLAYER_ID = :pid",
        {"gid": trackman_game_id, "pid": batter_id},
    )
    return "" if df.empty else str(df.iloc[0]["NOTES"])


# ============================ HELPERS =====================================

def _add_pitch_category(df: pd.DataFrame) -> pd.DataFrame:
    if not df.empty and "TaggedPitchType" in df:
        df = df.copy()
        df["PitchCat"] = np.where(
            df["TaggedPitchType"].isin(FASTBALLS), "Fastball", "Offspeed"
        )
    return df


def number_plate_appearances(df: pd.DataFrame,
                             order_cols=("PitchNo",)) -> pd.DataFrame:
    """Add a `PA` column: cumulative count of PitchofPA==1 in order (R cumsum+na.locf)."""
    if df.empty:
        return df.assign(PA=pd.Series(dtype="int64"))
    d = df.sort_values(list(order_cols)).copy()
    d["PA"] = (d["PitchofPA"] == 1).cumsum()
    return d


def _is_hit(df: pd.DataFrame) -> pd.Series:
    """R hit definition: PitchCall == 'InPlay' AND PlayResult != 'Out'."""
    return (df["PitchCall"] == "InPlay") & (df["PlayResult"] != "Out")


def _pct(numer: int, denom: int) -> float:
    """round(x, 3) * 100 as a number (R displays this as a string with '%')."""
    if denom == 0:
        return 0.0
    return round(round(numer / denom, 3) * 100, 1)


# ============================ TRANSFORMS ==================================

def game_batting_line(df: pd.DataFrame) -> dict:
    """Game batting line (R `overall`): PA, H, RBI, SO, BB, 2B, 3B, HR, QAB."""
    if df.empty:
        return {k: 0 for k in ("PA", "H", "RBI", "SO", "BB", "2B", "3B", "HR", "QAB")}
    numbered = number_plate_appearances(df)
    return {
        "PA": int(numbered["PA"].max()),
        "H": int(_is_hit(df).sum()),
        "RBI": int(df["RunsScored"].fillna(0).sum()),
        "SO": int((df["KorBB"] == "Strikeout").sum()),
        "BB": int((df["KorBB"] == "Walk").sum()),
        "2B": int((df["PlayResult"] == "Double").sum()),
        "3B": int((df["PlayResult"] == "Triple").sum()),
        "HR": int((df["PlayResult"] == "HomeRun").sum()),
        "QAB": int(qab_frame(df)["QAB"].sum()),
    }


def batted_ball_profile(df: pd.DataFrame, by_pitch_type: bool = False) -> pd.DataFrame:
    """Batted-ball metrics (R `batted_ball_overall` / `batted_ball_pt`)."""
    def agg(g: pd.DataFrame) -> dict:
        ev = g["ExitSpeed"]
        return {
            "Avg EV": round(ev.mean(), 1),
            "EV 90+": int(((ev >= 90) & ev.notna()).sum()),
            "EV <90": int(((ev < 90) & ev.notna()).sum()),
            "Avg Distance": round(g["Distance"].mean(), 1),
            "Avg Hang Time": round(g["HangTime"].mean(), 3),
            "Avg QC+": round(g["QC"].mean(), 0),
            "Avg PathQ+": round(g["PathQ"].mean(), 0),
            "FlyBall": int((g["TaggedHitType"] == "FlyBall").sum()),
            "GroundBall": int((g["TaggedHitType"] == "GroundBall").sum()),
            "LineDrive": int((g["TaggedHitType"] == "LineDrive").sum()),
            "PopUp": int((g["TaggedHitType"] == "Popup").sum()),
        }

    if df.empty:
        cols = ["Avg EV", "EV 90+", "EV <90", "Avg Distance", "Avg Hang Time",
                "Avg QC+", "Avg PathQ+", "FlyBall", "GroundBall", "LineDrive", "PopUp"]
        return pd.DataFrame(columns=(["Pitch Type"] if by_pitch_type else []) + cols)

    if by_pitch_type:
        # dplyr summarise returns groups ordered by the key (pitch type) ascending
        rows = [{"Pitch Type": pt, **agg(g)}
                for pt, g in df.groupby("TaggedPitchType", sort=True)]
        return pd.DataFrame(rows)
    return pd.DataFrame([agg(df)])


def swing_decisions_by_zone(df: pd.DataFrame) -> pd.DataFrame:
    """Swing/Take counts by zone area (R `swing_decisions_zone`)."""
    out = pd.DataFrame({"Zone": ZONE_LEVELS, "Total": 0, "Swing": 0, "Take": 0})
    if df.empty:
        return out
    d = df.copy()
    d["Decision"] = np.where(d["PitchCall"].isin(SWING_CALLS), "Swing", "Take")
    grp = d[d["Zone"].isin(ZONE_LEVELS)].groupby("Zone")
    agg = grp.agg(
        Total=("Decision", "size"),
        Swing=("Decision", lambda s: (s == "Swing").sum()),
        Take=("Decision", lambda s: (s == "Take").sum()),
    ).reindex(ZONE_LEVELS).fillna(0).astype(int).reset_index()
    return agg


def plate_discipline(df: pd.DataFrame, by: str = "zone") -> pd.DataFrame:
    """Swing%/Whiff%/Take%/Contact% by zone area or pitch type.

    R `plate_discipline` (by='zone') / `plate_discipline_pt` (by='pitch_type').
    Percentages are numeric (e.g. 33.3).
    """
    key = "Zone" if by == "zone" else "TaggedPitchType"
    label = "Zone" if by == "zone" else "Pitch Type"
    cols = [label, "Total", "Swing %", "Whiff %", "Take %", "Contact %"]
    if df.empty:
        return pd.DataFrame(columns=cols)

    d = df.copy()
    groups = ZONE_LEVELS if by == "zone" else None
    if by == "zone":
        d = d[d["Zone"].isin(ZONE_LEVELS)]

    rows = []
    for gval, g in d.groupby(key):
        n = len(g)
        swing = g["PitchCall"].isin(SWING_CALLS).sum()
        whiff = (g["PitchCall"] == "StrikeSwinging").sum()
        take = g["PitchCall"].isin(TAKE_CALLS).sum()
        contact = (g["PitchCall"] == "InPlay").sum()
        rows.append({label: gval, "Total": n,
                     "Swing %": _pct(swing, n), "Whiff %": _pct(whiff, n),
                     "Take %": _pct(take, n), "Contact %": _pct(contact, n)})
    out = pd.DataFrame(rows, columns=cols)
    if by == "zone":
        out = out.set_index(label).reindex(groups).reset_index()
        out["Total"] = out["Total"].fillna(0).astype(int)
        for c in ("Swing %", "Whiff %", "Take %", "Contact %"):
            out[c] = out[c].fillna(0.0)
    else:
        out = out.sort_values("Total", ascending=False, ignore_index=True)
    return out


def qab_frame(df: pd.DataFrame) -> pd.DataFrame:
    """One row per plate appearance (last pitch) with a QAB flag.

    Faithful port of the SQL CASE in the R app: a PA is a Quality At-Bat if any of
      - in play for a non-out       - a run scored
      - a walk                      - hit by pitch
      - a productive bunt           - hard hit (EV>=95 & LA>0)
      - a 7+ pitch PA               - a full 8+ pitch battle from 0-2
    """
    cols = list(df.columns) + ["QAB"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    # last pitch of each PA within the game(s)
    keys = ["GameID", "Inning", "PAofInning"]
    idx = df.groupby(keys)["PitchofPA"].idxmax()
    last = df.loc[idx].copy()

    def qab(r) -> int:
        rs = r.get("RunsScored") or 0
        ev = r.get("ExitSpeed")
        ang = r.get("Angle")
        if r["PitchCall"] == "InPlay" and r["PlayResult"] != "Out":
            return 1
        if rs > 0:
            return 1
        if r["KorBB"] == "Walk":
            return 1
        if r["PitchCall"] == "HitByPitch":
            return 1
        if r["TaggedHitType"] == "Bunt" and (rs > 0 or r.get("OutsOnPlay") == 0):
            return 1
        if pd.notna(ev) and ev >= 95 and pd.notna(ang) and ang > 0:
            return 1
        if r["PitchofPA"] >= 7:
            return 1
        if r["Strikes"] == 2 and r["Balls"] == 0 and r["PitchofPA"] >= 8:
            return 1
        return 0

    last["QAB"] = last.apply(qab, axis=1)
    return last


_HITS = {"Single", "Double", "Triple", "HomeRun"}
_TOTAL_BASES = {"Single": 1, "Double": 2, "Triple": 3, "HomeRun": 4}
_AB_OUTS = {"Out", "Error", "FieldersChoice", "Strikeout"}  # non-hit at-bats


def _fmt_avg(v) -> str:
    """Baseball three-decimal string, leading zero dropped for < 1 (e.g. .326)."""
    if v is None:
        return "—"
    s = f"{v:.3f}"
    return s[1:] if 0 <= v < 1 else s


def _slash_from_pas(pas_df: pd.DataFrame) -> dict:
    """Season BA/SLG/OBP from a one-row-per-PA frame (qab_frame output).

    Pure function shared by hitting_wh.wh_slash_line and hitting_caps.slash_line
    so both compute season slash the same way regardless of data source.

    PROVISIONAL definitions (one place to change; confirm with coaches):
      * one row per PA = last pitch of the PA (via qab_frame).
      * Walk = KorBB=='Walk'; HBP = last PitchCall=='HitByPitch';
        Sacrifice = PlayResult starts with 'Sac' (excluded from AB).
      * Hit = PlayResult in {Single,Double,Triple,HomeRun}.
      * AB = a completed PA that is not a walk/HBP/sacrifice.
      * BA = H/AB ; SLG = TotalBases/AB ; OBP = (H+BB+HBP)/(AB+BB+HBP+SF).
    Returns display strings ("—" when undefined).
    """
    blank = {"BA": "—", "SLG": "—", "OBP": "—"}
    if pas_df.empty:
        return blank

    ab = h = tb = bb = hbp = sf = 0
    for _, r in pas_df.iterrows():
        korbb = r.get("KorBB")
        pr = r.get("PlayResult")
        pc = r.get("PitchCall")
        is_walk = korbb == "Walk"
        is_hbp = pc == "HitByPitch"
        is_sac = isinstance(pr, str) and pr.startswith("Sac")
        if is_walk:
            bb += 1
            continue
        if is_hbp:
            hbp += 1
            continue
        if is_sac:
            sf += 1
            continue
        if pr in _HITS:
            ab += 1
            h += 1
            tb += _TOTAL_BASES[pr]
        elif pr in _AB_OUTS or korbb == "Strikeout":
            ab += 1
        # else: undefined/incomplete PA — not counted

    ba = h / ab if ab else None
    slg = tb / ab if ab else None
    ob_denom = ab + bb + hbp + sf
    obp = (h + bb + hbp) / ob_denom if ob_denom else None
    return {"BA": _fmt_avg(ba), "SLG": _fmt_avg(slg), "OBP": _fmt_avg(obp)}


def season_qab_rate(batter_id: int, since: str = "2025-02-14") -> float | None:
    """Season QAB% = TotalQAB / TotalAB (R `qab` tile), from Date >= `since`."""
    df = query_df(
        "SELECT * FROM GAMES WHERE BatterId = :bid AND Date >= :since",
        {"bid": batter_id, "since": since},
    )
    if df.empty:
        return None
    q = qab_frame(_add_pitch_category(df))
    total_ab = len(q)
    return round(q["QAB"].sum() / total_ab, 3) if total_ab else None


def kpi_by_date(batter_id: int, dates: list) -> pd.DataFrame:
    """Per-game-date KPI totals for the last-27-PA date set (R `kpi_table`)."""
    cols = ["Date", "H", "RBI", "SO", "BB", "2B", "3B", "HR",
            "AVGEV", "EVO90", "EVU90", "AVGDIS"]
    if not dates:
        return pd.DataFrame(columns=cols)
    df = query_df("SELECT * FROM GAMES WHERE BatterId = :bid", {"bid": batter_id})
    df = df[df["Date"].isin(set(dates))]
    if df.empty:
        return pd.DataFrame(columns=cols)

    rows = []
    for date, g in df.groupby("Date"):
        ev = g["ExitSpeed"]
        rows.append({
            "Date": date,
            "H": int(_is_hit(g).sum()),
            "RBI": int(g["RunsScored"].fillna(0).sum()),
            "SO": int((g["KorBB"] == "Strikeout").sum()),
            "BB": int((g["KorBB"] == "Walk").sum()),
            "2B": int((g["PlayResult"] == "Double").sum()),
            "3B": int((g["PlayResult"] == "Triple").sum()),
            "HR": int((g["PlayResult"] == "HomeRun").sum()),
            "AVGEV": round(ev.mean(), 1),
            "EVO90": int(((ev >= 90) & ev.notna()).sum()),
            "EVU90": int(((ev < 90) & ev.notna()).sum()),
            "AVGDIS": round(g["Distance"].mean(), 1),
        })
    return pd.DataFrame(rows, columns=cols).sort_values("Date", ascending=False,
                                                        ignore_index=True)


def balls_in_play(df: pd.DataFrame) -> pd.DataFrame:
    """Just the balls in play (PitchCall == 'InPlay')."""
    return df[df["PitchCall"] == "InPlay"].copy() if not df.empty else df


def spray_coordinates(df: pd.DataFrame) -> pd.DataFrame:
    """Add field x/y from Bearing & Distance (R spray charts).

    x = sin(Bearing°) * Distance, y = cos(Bearing°) * Distance.
    """
    bip = balls_in_play(df)
    bip = bip[bip["Distance"].notna() & bip["Direction"].notna()].copy()
    if bip.empty:
        return bip.assign(spray_x=pd.Series(dtype=float), spray_y=pd.Series(dtype=float))
    rad = np.pi / 180 * bip["Bearing"]
    bip["spray_x"] = np.sin(rad) * bip["Distance"]
    bip["spray_y"] = np.cos(rad) * bip["Distance"]
    return bip


def radial_coordinates(df: pd.DataFrame) -> pd.DataFrame:
    """Add launch-angle radial x/y (R `radial_plot`).

    Xcoord = EV/120 * cos(LA°), Ycoord = EV/120 * sin(LA°).
    """
    bip = balls_in_play(df)
    if bip.empty:
        return bip.assign(Xcoord=pd.Series(dtype=float), Ycoord=pd.Series(dtype=float))
    ang = bip["Angle"] * np.pi / 180
    bip["Xcoord"] = bip["ExitSpeed"] / 120 * np.cos(ang)
    bip["Ycoord"] = bip["ExitSpeed"] / 120 * np.sin(ang)
    return bip


def avg_ev_intervals(season_df: pd.DataFrame, days: int = 14) -> pd.DataFrame:
    """Average exit velocity in `days`-wide date bins across the season (R `avg_ev`)."""
    if season_df.empty:
        return pd.DataFrame(columns=["Interval_Date", "Avg_EV"])
    s = season_df.copy()
    s["Date"] = pd.to_datetime(s["Date"])
    start = s["Date"].min()
    interval = ((s["Date"] - start).dt.days // days).astype(int)
    s["Interval_Date"] = start + pd.to_timedelta(interval * days, unit="D")
    out = (s.groupby("Interval_Date")["ExitSpeed"].mean()
             .reset_index(name="Avg_EV").sort_values("Interval_Date", ignore_index=True))
    return out


def season_slash_line(batter_id: int) -> dict:
    """Season BA/SLG/OBP. TODO: wire to a data source.

    The R app scraped these from lmulions.com (fragile). Left as a hook until we
    decide the source (re-scrape, official stats API, or player_stats_summary).
    """
    return {"BA": None, "SLG": None, "OBP": None}
