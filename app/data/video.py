# app/data/video.py
"""Pitch-level video: one row per pitch with the four camera-angle S3 URLs.

Source = vw_pitch_video (public S3 .mp4 urls, Spring 2026 onward) joined to
fact_tm_game_pitch on pitch_uid for the surrogate game_id, catcher_id, velo,
plate zone, and batter_side that the video view does not carry.
"""
from __future__ import annotations

import re

import pandas as pd

from app.db import query_df

ANGLES: list[tuple[str, str]] = [
    ("HomeBehind", "Behind"), ("HomeRight", "Home R"),
    ("HomeLeft", "Home L"), ("Broadcast", "Broadcast"),
]
URL_COL: dict[str, str] = {a: f"url_{a.lower()}" for a, _ in ANGLES}
# Date is intentionally omitted from the table display (Item 2); it is still
# computed in pitch_video_df for sorting, then dropped by the _ALL_COLS projection.
DISPLAY_COLS: list[str] = ["Pitch", "Inn", "Count", "Type", "Velo", "Result", "Zone"]

_ALL_COLS = DISPLAY_COLS + list(URL_COL.values()) + ["batter_side", "pitch_uid"]

_RESULT_MAP = {
    "StrikeCalled": "Called Strike", "StrikeSwinging": "Swing & Miss",
    "BallCalled": "Ball", "BallinDirt": "Ball (dirt)", "BallIntentional": "IBB",
    "AutomaticBall": "Auto Ball", "AutomaticStrike": "Auto Strike",
    "FoulBallNotFieldable": "Foul", "FoulBallFieldable": "Foul", "HitByPitch": "HBP",
    "InPlay": "In Play",
}


def _spaced(s: str) -> str:
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(s))


def _result(pitch_call, play_result) -> str:
    if play_result is not None and not (isinstance(play_result, float) and pd.isna(play_result)):
        pr = str(play_result)
        if pr not in ("Undefined", "None", ""):
            return _spaced(pr)
    return _RESULT_MAP.get(str(pitch_call), _spaced(pitch_call))


def _sibling_ids(*, batter_id, pitcher_id, catcher_id):
    """(subject fact column, sibling id list) for whichever subject was passed."""
    given = [("batter_tm_id", batter_id, "app.data.hitting_wh", "_sibling_ids"),
             ("pitcher_id", pitcher_id, "app.data.pitching", "_sibling_pitcher_ids"),
             ("catcher_id", catcher_id, "app.data.catching", "_sibling_catcher_ids")]
    active = [(col, val, mod, fn) for col, val, mod, fn in given if val is not None]
    if len(active) != 1:
        raise ValueError("pass exactly one of batter_id / pitcher_id / catcher_id")
    col, val, mod, fn = active[0]
    import importlib
    sib = getattr(importlib.import_module(mod), fn)(int(val))
    return col, [int(x) for x in sib]


def pitch_video_df(game_id, *, batter_id=None, pitcher_id=None, catcher_id=None) -> pd.DataFrame:
    """One row per pitch (angles pivoted to url columns) for a game (or list of
    games) and one subject. Empty full-column frame when there is no video."""
    gids = [int(g) for g in (game_id if isinstance(game_id, (list, tuple)) else [game_id])]
    if not gids:
        return pd.DataFrame(columns=_ALL_COLS)
    subj_col, sib = _sibling_ids(batter_id=batter_id, pitcher_id=pitcher_id, catcher_id=catcher_id)

    gph = ", ".join(f":g{i}" for i in range(len(gids)))
    sph = ", ".join(f":s{i}" for i in range(len(sib)))
    params = {f"g{i}": g for i, g in enumerate(gids)}
    params.update({f"s{i}": s for i, s in enumerate(sib)})

    raw = query_df(
        f"""
        SELECT v.pitch_uid, v.pitch_no, v.inning, v.balls, v.strikes,
               v.tagged_pitch_type, v.pitch_call, v.play_result, v.game_date,
               v.angle, v.s3_url,
               f.rel_speed, f.izt_zone, f.batter_side
          FROM vw_pitch_video v
          JOIN fact_tm_game_pitch f ON f.pitch_uid = v.pitch_uid
         WHERE f.game_id IN ({gph}) AND f.{subj_col} IN ({sph})
        """,
        params,
    )
    if raw.empty:
        return pd.DataFrame(columns=_ALL_COLS)

    # Pivot angle -> url column (one row per pitch_uid).
    urls = (raw.pivot_table(index="pitch_uid", columns="angle", values="s3_url",
                            aggfunc="first")
               .reindex(columns=[a for a, _ in ANGLES]))
    urls.columns = [URL_COL[a] for a in urls.columns]

    meta = (raw.drop_duplicates("pitch_uid")
               .set_index("pitch_uid"))
    out = meta.join(urls)

    zone = out["izt_zone"].astype("object").where(out["izt_zone"].notna(), None)
    df = pd.DataFrame({
        "Pitch": out["pitch_no"].astype("Int64"),
        "Inn": out["inning"].astype("Int64"),
        "Count": out["balls"].astype("Int64").astype(str) + "-" + out["strikes"].astype("Int64").astype(str),
        "Type": out["tagged_pitch_type"],
        "Velo": out["rel_speed"].round(1).map(lambda v: "—" if pd.isna(v) else f"{v:.1f}"),
        "Result": [_result(pc, pr) for pc, pr in zip(out["pitch_call"], out["play_result"])],
        "Zone": [("—" if z is None else str(z)) for z in zone],
        "Date": out["game_date"].astype(str),
    })
    for a in URL_COL.values():
        df[a] = [None if pd.isna(v) else v for v in out[a]]
    df["batter_side"] = out["batter_side"].values
    df["pitch_uid"] = out.index.values
    df = df.sort_values(["Date", "Pitch"], ascending=[False, True]).reset_index(drop=True)
    return df[_ALL_COLS]
