# app/data/video.py
"""Pitch-level video: one row per pitch with the four camera-angle S3 URLs.

Source = video_clips (base table: pitch_uid/angle/s3_url/game_date, public S3
.mp4 urls) joined to GAMES on PitchUID for the pitch metadata (velo, plate
zone, count, result, batter side) and the surrogate GameID. Fully on CAPS --
no legacy warehouse (view/fact) dependency, so video survives the tm_* drop.
(The `test_video_source_is_caps_only` guard enforces the absence of any
warehouse-object reference in this module.)
"""
from __future__ import annotations

import re

import pandas as pd

from app.db import query_df
from app.data.cache import cached
from app.data.catching import CS_RESULTS

ANGLES: list[tuple[str, str]] = [
    ("HomeBehind", "Behind"), ("HomeRight", "Home R"),
    ("HomeLeft", "Home L"), ("Broadcast", "Broadcast"),
]
URL_COL: dict[str, str] = {a: f"url_{a.lower()}" for a, _ in ANGLES}
# Date is intentionally omitted from the table display (Item 2); it is still
# computed in pitch_video_df for sorting, then dropped by the _ALL_COLS projection.
DISPLAY_COLS: list[str] = ["Pitch", "Inn", "Count", "Type", "Velo", "Result", "Zone"]
# CATCHING tab only: swaps Velo for a Steal-attempt (SB/CS/blank) column.
CATCHING_DISPLAY_COLS: list[str] = ["Pitch", "Inn", "Count", "Type", "Steal", "Result", "Zone"]

# "Steal" is built for every subject (not just catcher) so pitch_video_df keeps a
# stable column shape; only the CATCHING tab chooses to display it. Mirrors the
# steal-attempt outcomes in app.data.catching.CS_RESULTS.
_STEAL_LABEL = {"StolenBase": "SB", "CaughtStealing": "CS"}
assert set(_STEAL_LABEL) == CS_RESULTS

_ALL_COLS = DISPLAY_COLS + ["Steal"] + list(URL_COL.values()) + ["batter_side", "pitch_uid"]

_RESULT_MAP = {
    "StrikeCalled": "Called Strike", "StrikeSwinging": "Swing & Miss",
    "BallCalled": "Ball", "BallinDirt": "Ball (dirt)", "BallIntentional": "IBB",
    "AutomaticBall": "Auto Ball", "AutomaticStrike": "Auto Strike",
    "FoulBallNotFieldable": "Foul", "FoulBallFieldable": "Foul", "HitByPitch": "HBP",
    "InPlay": "In Play",
}


def _spaced(s: str) -> str:
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(s))


def _steal(play_result) -> str:
    """"SB" for a stolen base, "CS" for caught stealing, else blank. NaN/None-safe."""
    if isinstance(play_result, float) and pd.isna(play_result):
        return ""
    return _STEAL_LABEL.get(play_result, "")


def _result(pitch_call, play_result) -> str:
    if play_result is not None and not (isinstance(play_result, float) and pd.isna(play_result)):
        pr = str(play_result)
        if pr not in ("Undefined", "None", ""):
            return _spaced(pr)
    return _RESULT_MAP.get(str(pitch_call), _spaced(pitch_call))


def _sibling_ids(*, batter_id, pitcher_id, catcher_id):
    """(subject GAMES column, sibling id list) for whichever subject was passed.

    All three subjects use the RAW trackman id space (== GAMES.BatterId /
    GAMES.PitcherId / GAMES.CatcherId), matching what the post-cutover
    dashboards/report pass. Siblings are resolved in that same raw space --
    batter via `hitting_caps._sibling_ids`, pitcher via
    `pitching_caps._sibling_pitcher_ids`, catcher via
    `catching_caps._sibling_catcher_ids` -- and filtered against the GAMES
    column named in the first tuple element.
    """
    given = [("BatterId", batter_id, "app.data.hitting_caps", "_sibling_ids"),
             ("PitcherId", pitcher_id, "app.data.pitching_caps", "_sibling_pitcher_ids"),
             ("CatcherId", catcher_id, "app.data.catching_caps", "_sibling_catcher_ids")]
    active = [(col, val, mod, fn) for col, val, mod, fn in given if val is not None]
    if len(active) != 1:
        raise ValueError("pass exactly one of batter_id / pitcher_id / catcher_id")
    col, val, mod, fn = active[0]
    import importlib
    sib = getattr(importlib.import_module(mod), fn)(int(val))
    return col, [int(x) for x in sib]


@cached
def games_with_video(game_ids, *, batter_id=None, pitcher_id=None, catcher_id=None) -> set:
    """Of the given game_ids, the subset that have at least one video clip for the
    subject (Item 3: used to tag the game dropdown). Empty input -> empty set.
    GameID is an opaque string (numeric surrogate or composite), so ids are
    carried as strings, never int()'d."""
    gids = [str(g) for g in (game_ids if isinstance(game_ids, (list, tuple, set)) else [game_ids])]
    if not gids:
        return set()
    subj_col, sib = _sibling_ids(batter_id=batter_id, pitcher_id=pitcher_id, catcher_id=catcher_id)
    if not sib:
        return set()
    gph = ", ".join(f":g{i}" for i in range(len(gids)))
    sph = ", ".join(f":s{i}" for i in range(len(sib)))
    params = {f"g{i}": str(g) for i, g in enumerate(gids)}
    params.update({f"s{i}": s for i, s in enumerate(sib)})
    df = query_df(
        f"""
        SELECT DISTINCT g.GameID
          FROM video_clips v
          JOIN GAMES g ON g.PitchUID = v.pitch_uid
         WHERE g.GameID IN ({gph}) AND g.{subj_col} IN ({sph})
        """,
        params,
    )
    return set() if df.empty else {str(g) for g in df["GameID"]}


def video_game_ids(games_df, **subject) -> set:
    """Safe convenience for dropdown tagging (Item 3): of the games in `games_df`
    (needs a `game_id` column), the subset that have video for the subject. Pass
    exactly one of batter_id / pitcher_id / catcher_id. Never raises — returns an
    empty set on any error so a video-view hiccup can't blank the game dropdown."""
    try:
        if games_df is None or getattr(games_df, "empty", True):
            return set()
        return games_with_video([str(x) for x in games_df["game_id"]], **subject)
    except Exception:
        return set()


def pitch_video_df(game_id, *, batter_id=None, pitcher_id=None, catcher_id=None) -> pd.DataFrame:
    """One row per pitch (angles pivoted to url columns) for a game (or list of
    games) and one subject. Empty full-column frame when there is no video."""
    gids = [str(g) for g in (game_id if isinstance(game_id, (list, tuple)) else [game_id])]
    if not gids:
        return pd.DataFrame(columns=_ALL_COLS)
    subj_col, sib = _sibling_ids(batter_id=batter_id, pitcher_id=pitcher_id, catcher_id=catcher_id)
    if not sib:  # resolvers currently always return >=1; guard the IN () trap defensively
        return pd.DataFrame(columns=_ALL_COLS)

    gph = ", ".join(f":g{i}" for i in range(len(gids)))
    sph = ", ".join(f":s{i}" for i in range(len(sib)))
    params = {f"g{i}": str(g) for i, g in enumerate(gids)}
    params.update({f"s{i}": s for i, s in enumerate(sib)})

    raw = query_df(
        f"""
        SELECT v.pitch_uid, g.PitchNo AS pitch_no, g.Inning AS inning,
               g.Balls AS balls, g.Strikes AS strikes,
               g.TaggedPitchType AS tagged_pitch_type, g.PitchCall AS pitch_call,
               g.PlayResult AS play_result, v.game_date,
               v.angle, v.s3_url,
               g.RelSpeed AS rel_speed, g.Zone AS izt_zone,
               g.BatterSide AS batter_side
          FROM video_clips v
          JOIN GAMES g ON g.PitchUID = v.pitch_uid
         WHERE g.GameID IN ({gph}) AND g.{subj_col} IN ({sph})
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
        "Steal": [_steal(pr) for pr in out["play_result"]],
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
