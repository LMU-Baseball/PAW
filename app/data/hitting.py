"""Hitting data access + analytical transforms.

Faithful port of the R "Hitter Postgame" app (src/app 1). Queries the legacy
Trackman tables (GAMES / STANDINGS / VIDEO / PLAYERS / NOTES). Selection is
role-agnostic here; the web layer decides whether a user may view a batter
(team-transparent: any authenticated account may view anyone -- write access is
gated separately, coach-only).

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


# --- shared helpers (moved from the deleted hitting_wh warehouse module in
#     Phase 3; reused by hitting_caps and catching, so they live here in the
#     CAPS-reading module). All are pure except _roster_lookup, which reads the
#     surviving roster_players table (not a warehouse table). -----------------

def attack_zone(side_ft, height_ft) -> str:
    """Heart/Shadow/Chase/Waste from plate coords (inches; zone-box boundaries).

    Missing coords (None/NaN) return "" so untracked pitches are excluded from
    zone-based tables rather than being miscounted as genuine "Waste" pitches.
    """
    if side_ft is None or height_ft is None or pd.isna(side_ft) or pd.isna(height_ft):
        return ""
    x = abs(float(side_ft) * 12)
    y = abs(float(height_ft) * 12 - 30)
    if x <= 7.25 and y <= 8.75:
        return "Heart"
    if x <= 13.5 and y <= 15.125:
        return "Shadow"
    if x <= 20.5 and y <= 25.5:
        return "Chase"
    return "Waste"


def _finish(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["Zone"] = [attack_zone(s, h)
                  for s, h in zip(df["PlateLocSide"], df["PlateLocHeight"])]
    for c in ("QC", "PathQ", "Angle"):
        df[c] = np.nan
    return _add_pitch_category(df)


def _in_clause(ids) -> tuple[str, dict]:
    """Build a parameterized `IN (...)` fragment + params dict for a list of ids."""
    ph = ", ".join(f":id{i}" for i in range(len(ids)))
    return ph, {f"id{i}": int(v) for i, v in enumerate(ids)}


def _roster_lookup(name_last_first: str) -> tuple[str, str]:
    """Best-effort class_year/position from roster_players (name is 'First Last')."""
    if "," not in name_last_first:
        return "", ""
    last, first = (p.strip() for p in name_last_first.split(",", 1))
    df = query_df(
        """
        SELECT class_year, position FROM roster_players
         WHERE season LIKE '2025%' AND player_name = :n LIMIT 1
        """,
        {"n": f"{first} {last}"},
    )
    if df.empty:
        return "", ""
    r = df.iloc[0]
    cy = "" if pd.isna(r["class_year"]) else str(r["class_year"])
    pos = "" if pd.isna(r["position"]) else str(r["position"])
    return cy, pos


_BIP_COLS = ["hit_type", "exit_speed", "la", "bearing", "distance",
             "x", "y", "rx", "ry", "Count", "Result", "PitchType", "Pitcher",
             "GameID", "Inning", "PAofInning",
             "PlayResult"]  # added for Task 2's xBA numerator population filter


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


def _pa_outcome(r) -> str:
    """Classify one qab_frame row (one PA, last pitch) into exactly one of
    "bb"/"hbp"/"sf"/"hit"/"ab_out"/"other" -- the single source of truth for
    AB/Hit/BB/HBP/SF, shared by `_slash_counts` (season slash line) and
    `zone_frequency_grid` (batting-average-by-zone).

    PROVISIONAL definitions (one place to change; confirm with coaches):
      * Walk = KorBB=='Walk'; HBP = last PitchCall=='HitByPitch';
        Sacrifice = PlayResult starts with 'Sac' (excluded from AB).
      * Hit = PlayResult in {Single,Double,Triple,HomeRun}.
      * AB = a completed PA that is not a walk/HBP/sacrifice ("hit" or
        "ab_out"); "other" = undefined/incomplete PA, not counted anywhere.
    """
    korbb = r.get("KorBB")
    pr = r.get("PlayResult")
    pc = r.get("PitchCall")
    if korbb == "Walk":
        return "bb"
    if pc == "HitByPitch":
        return "hbp"
    if isinstance(pr, str) and pr.startswith("Sac"):
        return "sf"
    if pr in _HITS:
        return "hit"
    if pr in _AB_OUTS or korbb == "Strikeout":
        return "ab_out"
    return "other"


def _slash_counts(pas_df: pd.DataFrame) -> dict:
    """Int counting components behind the slash line, from a one-row-per-PA
    frame (qab_frame output). Single source of truth for the AB/H/BB/HBP/SF
    definitions (so `_slash_from_pas` and the Phase 4 precalc rollup can't
    drift), and additionally breaks out doubles/triples/hr/so and pa.

    Per-row classification lives in `_pa_outcome`; this just tallies it plus
    the SO/total-bases/extra-base breakdowns.
    """
    c = {"pa": int(len(pas_df)), "ab": 0, "h": 0, "tb": 0, "bb": 0, "hbp": 0,
         "sf": 0, "doubles": 0, "triples": 0, "hr": 0, "so": 0}
    if pas_df.empty:
        return c
    for _, r in pas_df.iterrows():
        if r.get("KorBB") == "Strikeout":
            c["so"] += 1
        outcome = _pa_outcome(r)
        if outcome == "bb":
            c["bb"] += 1
        elif outcome == "hbp":
            c["hbp"] += 1
        elif outcome == "sf":
            c["sf"] += 1
        elif outcome == "hit":
            pr = r.get("PlayResult")
            c["ab"] += 1
            c["h"] += 1
            c["tb"] += _TOTAL_BASES[pr]
            if pr == "Double":
                c["doubles"] += 1
            elif pr == "Triple":
                c["triples"] += 1
            elif pr == "HomeRun":
                c["hr"] += 1
        elif outcome == "ab_out":
            c["ab"] += 1
        # else "other": undefined/incomplete PA — not counted
    return c


def _slash_from_pas(pas_df: pd.DataFrame) -> dict:
    """Season BA/SLG/OBP display strings from a one-row-per-PA frame.

    Pure function shared by hitting_caps.slash_line and the Phase 4 precalc
    rebuild so both format season slash the same way. Delegates the counting to
    `_slash_counts` (the single source of truth for the definitions).
      * BA = H/AB ; SLG = TotalBases/AB ; OBP = (H+BB+HBP)/(AB+BB+HBP+SF).
    Returns display strings ("—" when undefined).
    """
    c = _slash_counts(pas_df)
    ab, h, tb, bb, hbp, sf = c["ab"], c["h"], c["tb"], c["bb"], c["hbp"], c["sf"]
    ba = h / ab if ab else None
    slg = tb / ab if ab else None
    ob_denom = ab + bb + hbp + sf
    obp = (h + bb + hbp) / ob_denom if ob_denom else None
    return {"BA": _fmt_avg(ba), "SLG": _fmt_avg(slg), "OBP": _fmt_avg(obp)}


# ============================ ZONE FREQUENCY ================================
#
# 9-pocket (3x3) rulebook-zone grid for the hitting dashboard's Zone Frequency
# tab. Classifies in the exact same transformed (inches) coordinate system as
# app.dashboards.hitting.charts's zone_scatter -- x=PlateLocSide*-12,
# y=PlateLocHeight*12-30 -- against that chart's own zone box/gridlines
# (_SZ=(-10,-13,10,13), _VLINES=(-3.33,3.33), _HLINES=(-4.33,4.33)), so this
# grid lines up with the Zone Location tab's scatter and "col ascending"
# genuinely means "left->right on screen" (if either set of constants
# changes, check the other).


def zone9_cell(side_ft, height_ft) -> tuple[int, int] | None:
    """Bucket a pitch location into one of 9 rulebook-zone cells as
    (row, col), row 0 = bottom third / col 0 = catcher's-view left, or None
    if outside the zone box or the location is missing."""
    if side_ft is None or height_ft is None or pd.isna(side_ft) or pd.isna(height_ft):
        return None
    x = float(side_ft) * -12.0
    y = float(height_ft) * 12.0 - 30.0
    if not (-10.0 <= x <= 10.0 and -13.0 <= y <= 13.0):
        return None
    col = 0 if x < -3.33 else (2 if x > 3.33 else 1)
    row = 0 if y < -4.33 else (2 if y > 4.33 else 1)
    return (row, col)


def _empty_zone9_grid() -> list:
    return [[{"value": None, "n": 0} for _ in range(3)] for _ in range(3)]


def _narrow_zone_pop(d: pd.DataFrame, *, pitch_group: str, throws: str) -> pd.DataFrame:
    """Shared pitch_group/throws narrowing for the Zone Frequency tab's
    grids -- "All" is the no-filter sentinel for both."""
    if pitch_group != "All" and "PitchCat" in d.columns:
        d = d[d["PitchCat"] == pitch_group]
    if throws != "All" and "PitcherThrows" in d.columns:
        d = d[d["PitcherThrows"] == throws]
    return d


def zone_frequency_grid(df: pd.DataFrame, *, metric: str = "ev",
                        pitch_group: str = "All", throws: str = "All") -> list:
    """3x3 grid (see `zone9_cell`) of {"value": float|None, "n": int} for one
    damage metric, narrowed by pitch group ("All"/"Fastball"/"Offspeed",
    matching the `PitchCat` column) and pitcher throws ("All"/"Right"/
    "Left", matching the raw `PitcherThrows` column):

      * "ev"/"distance" -- Avg ExitSpeed/Distance of batted balls
        (PitchCall=='InPlay') whose OWN pitch lands in a cell; pitch_group/
        throws filter those rows directly since each batted ball is a
        complete, independent event.
      * "avg" -- Batting average (H/AB, `_pa_outcome`'s definitions) over
        plate-appearance-ending pitches. `qab_frame` is computed on the
        UNFILTERED df first so the true last pitch of every PA is always
        found correctly, and pitch_group/throws are applied to the
        resulting one-row-per-PA frame afterward (both columns are on that
        row already) -- filtering pitch-level rows first would let
        `PitchofPA.idxmax()` pick a non-final pitch as if it ended the PA.
    """
    grid = _empty_zone9_grid()
    if df is None or df.empty:
        return grid

    if metric in ("ev", "distance"):
        col = "ExitSpeed" if metric == "ev" else "Distance"
        bip = df[(df["PitchCall"] == "InPlay") & df[col].notna()]
        bip = _narrow_zone_pop(bip, pitch_group=pitch_group, throws=throws)
        buckets: dict = {}
        for _, r in bip.iterrows():
            cell = zone9_cell(r.get("PlateLocSide"), r.get("PlateLocHeight"))
            if cell is None:
                continue
            buckets.setdefault(cell, []).append(float(r[col]))
        for (row, c), vals in buckets.items():
            grid[row][c] = {"value": round(sum(vals) / len(vals), 1), "n": len(vals)}
        return grid

    pas = qab_frame(df)
    if pas.empty:
        return grid
    pas = _narrow_zone_pop(pas, pitch_group=pitch_group, throws=throws)
    buckets = {}
    for _, r in pas.iterrows():
        cell = zone9_cell(r.get("PlateLocSide"), r.get("PlateLocHeight"))
        if cell is None:
            continue
        outcome = _pa_outcome(r)
        if outcome not in ("hit", "ab_out"):
            continue  # not an AB -- no zone credit either way
        ab, h = buckets.get(cell, (0, 0))
        buckets[cell] = (ab + 1, h + (1 if outcome == "hit" else 0))
    for (row, c), (ab, h) in buckets.items():
        grid[row][c] = {"value": round(h / ab, 3) if ab else None, "n": ab}
    return grid


def zone_pitch_frequency_grid(df: pd.DataFrame, *, pitch_group: str = "All",
                              throws: str = "All") -> list:
    """3x3 grid (see `zone9_cell`) of {"value": int, "n": int} raw PITCH
    COUNT per cell -- every pitch with a placeable location, regardless of
    `PitchCall` (unlike `zone_frequency_grid`'s "ev"/"distance", which only
    count contact). Answers a question the damage grids can't: is a "cold"
    cell actually attacked often, or just rarely thrown there at all. Both
    `value` and `n` are the same count (kept for shape parity with
    `zone_frequency_grid`'s cells)."""
    grid = _empty_zone9_grid()
    if df is None or df.empty:
        return grid
    d = _narrow_zone_pop(df, pitch_group=pitch_group, throws=throws)
    counts: dict = {}
    for _, r in d.iterrows():
        cell = zone9_cell(r.get("PlateLocSide"), r.get("PlateLocHeight"))
        if cell is None:
            continue
        counts[cell] = counts.get(cell, 0) + 1
    for (row, c), n in counts.items():
        grid[row][c] = {"value": n, "n": n}
    return grid


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
