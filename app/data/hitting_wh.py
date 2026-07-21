"""Warehouse hitting data layer.

Queries the modern Trackman warehouse (fact_tm_game_pitch / dim_tm_game / tm_team)
and returns DataFrames whose columns are aliased to the LEGACY names the transforms
in app/data/hitting.py expect, so those transforms are reused unchanged. Adds a
computed attack `Zone` and NaN `QC`/`PathQ`/`Angle` (columns the warehouse lacks).
Canonical id = batter_tm_id (== a player's current_user.trackman_id). LMU = team 78.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.db import query_df
from app.data.hitting import _add_pitch_category, qab_frame
from app.data.roster_media import player_media

LMU_TEAM_ID = 78
LMU_BATTER_TEAM = "LOY_LIO"

# fact -> legacy alias list, shared by game + season loaders.
_PITCH_SELECT = """
    plate_loc_side AS PlateLocSide, plate_loc_height AS PlateLocHeight,
    pitch_call AS PitchCall, play_result AS PlayResult, korbb AS KorBB,
    tagged_hit_type AS TaggedHitType, tagged_pitch_type AS TaggedPitchType,
    exit_speed AS ExitSpeed, distance AS Distance, bearing AS Bearing,
    hang_time AS HangTime, inning AS Inning, pa_of_inning AS PAofInning,
    pitch_of_pa AS PitchofPA, pitch_no AS PitchNo, balls AS Balls,
    strikes AS Strikes, runs_scored AS RunsScored, outs_on_play AS OutsOnPlay,
    batter_side AS BatterSide, pitcher_name AS Pitcher, game_id AS GameID
"""


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


def _sibling_ids(batter_tm_id) -> list[int]:
    """All LMU batter_tm_ids sharing this id's batter_name.

    The warehouse assigns some players TWO Trackman ids across the season (an
    early-season and a late-season id scheme). They share the same batter_name,
    so we merge them by name to give one hitter one dropdown entry + all games.
    """
    name = query_df(
        """
        SELECT batter_name FROM fact_tm_game_pitch
         WHERE batter_tm_id = :b AND batter_team = :team LIMIT 1
        """,
        {"b": int(batter_tm_id), "team": LMU_BATTER_TEAM},
    )
    if name.empty:
        return [int(batter_tm_id)]
    ids = query_df(
        """
        SELECT DISTINCT batter_tm_id FROM fact_tm_game_pitch
         WHERE batter_name = :n AND batter_team = :team AND batter_tm_id IS NOT NULL
        """,
        {"n": str(name.iloc[0]["batter_name"]), "team": LMU_BATTER_TEAM},
    )
    out = [int(x) for x in ids["batter_tm_id"]]
    return out or [int(batter_tm_id)]


def wh_lmu_hitters() -> pd.DataFrame:
    """One row per LMU hitter (name deduped; canonical id = most-tracked id)."""
    return query_df(
        """
        SELECT Batter, BatterId FROM (
          SELECT batter_name AS Batter, batter_tm_id AS BatterId,
                 ROW_NUMBER() OVER (PARTITION BY batter_name
                                    ORDER BY COUNT(*) DESC, batter_tm_id) AS rn
            FROM fact_tm_game_pitch
           WHERE batter_team = :team AND batter_tm_id IS NOT NULL
           GROUP BY batter_name, batter_tm_id
        ) t WHERE rn = 1 ORDER BY Batter
        """,
        {"team": LMU_BATTER_TEAM},
    )


def wh_games_for_batter(batter_tm_id) -> pd.DataFrame:
    ph, idp = _in_clause(_sibling_ids(batter_tm_id))
    df = query_df(
        f"""
        SELECT g.game_id, g.game_date, g.home_team_id,
               CASE WHEN g.home_team_id = :lmu THEN 'vs' ELSE '@' END AS loc,
               t.team_name AS opp
          FROM (SELECT DISTINCT game_id FROM fact_tm_game_pitch
                 WHERE batter_tm_id IN ({ph})) bg
          JOIN dim_tm_game g ON g.game_id = bg.game_id
          JOIN tm_team t ON t.team_id = CASE WHEN g.home_team_id = :lmu
                                             THEN g.away_team_id ELSE g.home_team_id END
         ORDER BY g.game_date DESC
        """,
        {"lmu": LMU_TEAM_ID, **idp},
    )
    if df.empty:
        return pd.DataFrame(columns=["game_id", "game_date", "GameLabel"])
    df["GameLabel"] = [f"{pd.to_datetime(d).strftime('%m/%d/%y')} {l} {o}"
                       for d, l, o in zip(df["game_date"], df["loc"], df["opp"])]
    return df[["game_id", "game_date", "GameLabel"]]


def wh_game_pitches(game_id, batter_tm_id) -> pd.DataFrame:
    ph, idp = _in_clause(_sibling_ids(batter_tm_id))
    df = query_df(
        f"""
        SELECT {_PITCH_SELECT}
          FROM fact_tm_game_pitch
         WHERE game_id = :g AND batter_tm_id IN ({ph})
         ORDER BY pitch_no
        """,
        {"g": int(game_id), **idp},
    )
    return _finish(df)


def wh_season_pitches(batter_tm_id) -> pd.DataFrame:
    ph, idp = _in_clause(_sibling_ids(batter_tm_id))
    df = query_df(
        f"""
        SELECT {_PITCH_SELECT}
          FROM fact_tm_game_pitch
         WHERE batter_tm_id IN ({ph})
         ORDER BY game_id, pitch_no
        """,
        idp,
    )
    return _finish(df)


def wh_season_qab_rate(batter_tm_id) -> float | None:
    df = wh_season_pitches(batter_tm_id)
    if df.empty:
        return None
    q = qab_frame(df)
    total = len(q)
    return round(q["QAB"].sum() / total, 3) if total else None


_HITS = {"Single", "Double", "Triple", "HomeRun"}
_TOTAL_BASES = {"Single": 1, "Double": 2, "Triple": 3, "HomeRun": 4}
_AB_OUTS = {"Out", "Error", "FieldersChoice", "Strikeout"}  # non-hit at-bats


def _fmt_avg(v) -> str:
    """Baseball three-decimal string, leading zero dropped for < 1 (e.g. .326)."""
    if v is None:
        return "—"
    s = f"{v:.3f}"
    return s[1:] if 0 <= v < 1 else s


def wh_slash_line(batter_tm_id) -> dict:
    """Season BA/SLG/OBP computed from warehouse game plate appearances.

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
    df = wh_season_pitches(batter_tm_id)
    if df.empty:
        return blank
    pas = qab_frame(df)
    if pas.empty:
        return blank

    ab = h = tb = bb = hbp = sf = 0
    for _, r in pas.iterrows():
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


def wh_player_profile(batter_tm_id) -> dict:
    blank = {"name": "", "bats": "", "class_year": "", "position": "",
             "photo": "", "jersey": ""}
    df = query_df(
        """
        SELECT batter_name, batter_side FROM fact_tm_game_pitch
         WHERE batter_tm_id = :b ORDER BY game_id DESC LIMIT 1
        """,
        {"b": int(batter_tm_id)},
    )
    if df.empty:
        return blank
    name = "" if pd.isna(df.iloc[0]["batter_name"]) else str(df.iloc[0]["batter_name"])
    bats = "" if pd.isna(df.iloc[0]["batter_side"]) else str(df.iloc[0]["batter_side"])
    cy, pos = _roster_lookup(name)
    media = player_media(int(batter_tm_id))  # scraped headshot + jersey (blanks if none)
    return {"name": name, "bats": bats, "class_year": cy, "position": pos,
            "photo": media["photo_url"], "jersey": media["jersey"]}


def wh_scoreboard(game_id) -> dict:
    df = query_df(
        """
        SELECT g.game_date, g.game_type, g.home_team_id, t.team_name AS opp
          FROM dim_tm_game g
          JOIN tm_team t ON t.team_id = CASE WHEN g.home_team_id = :lmu
                                             THEN g.away_team_id ELSE g.home_team_id END
         WHERE g.game_id = :g
        """,
        {"g": int(game_id), "lmu": LMU_TEAM_ID},
    )
    if df.empty:
        return {"date": "", "loc": "", "opp": "", "game_type": ""}
    r = df.iloc[0]
    return {"date": pd.to_datetime(r["game_date"]).strftime("%m/%d/%y"),
            "loc": "vs" if r["home_team_id"] == LMU_TEAM_ID else "@",
            "opp": "" if pd.isna(r["opp"]) else str(r["opp"]),
            "game_type": "" if pd.isna(r["game_type"]) else str(r["game_type"])}
