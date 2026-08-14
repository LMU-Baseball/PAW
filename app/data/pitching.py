"""Pitcher pure-transforms + figures for the postgame report and dashboards.

CAPS era: all runtime data access now lives in ``app.data.pitching_caps``
(which reads the CAPS ``GAMES`` table). This module holds only the *pure*
transforms and Plotly figure builders that operate on an already-loaded pitch
DataFrame -- no SQL, no warehouse. Percentages are returned as NUMERIC.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd
import plotly.graph_objects as go

PITCH_TYPE_COL = "tagged_pitch_type"
# GAMES.PitcherTeam Trackman code for LMU. Pure constant (not a warehouse
# object); the postgame report's LMU-only guard reads it as P.LMU_PITCHER_TEAM.
LMU_PITCHER_TEAM = "LOY_LIO"


def pitch_type(df: pd.DataFrame) -> pd.Series:
    """Tagged pitch type, falling back to auto_pitch_type when null/empty."""
    tagged = df[PITCH_TYPE_COL].replace("", np.nan)
    return tagged.fillna(df["auto_pitch_type"]).fillna("Undefined")


# ============================ TRANSFORMS ==================================
#
# NOTE on column-semantics adjustments made after checking against the live
# fixture (game_id=166, pitcher_id=1) and a full-table scan of distinct
# values:
#
# - pitch_call: the live values are StrikeCalled, StrikeSwinging, InPlay,
#   BallCalled, HitByPitch, Undefined, FoulBallNotFieldable,
#   FoulBallFieldable, BallinDirt, BallIntentional, AutomaticBall — there is
#   no plain "FoulBall" and balls aren't only "BallCalled". _STRIKE_CALLS/
#   _SWING_CALLS use the two Foul* variants instead of "FoulBall", and a new
#   _BALL_CALLS set covers all called/no-swing ball variants (BallCalled,
#   BallinDirt, BallIntentional, AutomaticBall). HitByPitch and Undefined are
#   intentionally excluded from both strikes and balls (dead-ball / no call).
#
# - zi: this column is NULL for every row in fact_tm_game_pitch (verified
#   warehouse-wide), so it cannot be used as an in-zone indicator. zone
#   location instead derives in-zone from izt_zone, whose values are the
#   strings "1".."9" (the 3x3 strike-zone grid), "Shadow" (borderline), and
#   "Ball" (clearly out). in_zone_pct = % of pitches with izt_zone in 1..9.

_STRIKE_CALLS = {"StrikeCalled", "StrikeSwinging", "FoulBallNotFieldable",
                  "FoulBallFieldable", "InPlay"}
_WHIFF_CALLS = {"StrikeSwinging"}
_SWING_CALLS = {"StrikeSwinging", "FoulBallNotFieldable", "FoulBallFieldable", "InPlay"}
_BALL_CALLS = {"BallCalled", "BallinDirt", "BallIntentional", "AutomaticBall"}
_IN_ZONE_CODES = {"1", "2", "3", "4", "5", "6", "7", "8", "9"}

_HIT_RESULTS = {"Single", "Double", "Triple", "HomeRun"}


def _pct(a: int, b: int) -> float:
    return round(100.0 * a / b, 1) if b else 0.0


def _pa_count(df: pd.DataFrame) -> int:
    """Plate appearances = distinct (game_id, inning, pa_of_inning) among the
    pitches.

    game_id is part of the key because (inning, pa_of_inning) repeats across
    games (every game has an inning-1, pa-1); keying without it conflated PAs
    across a multi-game range, undercounting the denominator and inflating
    K%/BB%/Barrel%. Falls back to (inning, pa_of_inning) when game_id is absent
    (a single-game df / inline fixture, where the pair is already unique).

    Split-safe (works on a batter-side subset), unlike batters_faced.max()
    which is a running counter over the whole outing.
    """
    if df.empty:
        return 0
    cols = ["game_id", "inning", "pa_of_inning"] if "game_id" in df.columns \
        else ["inning", "pa_of_inning"]
    return int(df[cols].drop_duplicates().shape[0])


def strike_pct(df: pd.DataFrame) -> tuple[float, int]:
    s = int(df["pitch_call"].isin(_STRIKE_CALLS).sum())
    return _pct(s, len(df)), s


def fps_pct(df: pd.DataFrame) -> tuple[float, int]:
    fp = df[df["pitch_of_pa"] == 1]
    s = int(fp["pitch_call"].isin(_STRIKE_CALLS).sum())
    return _pct(s, len(fp)), s


def k_pct(df: pd.DataFrame) -> tuple[float, int]:
    k = int((df["korbb"] == "Strikeout").sum())
    return _pct(k, _pa_count(df)), k


def bb_pct(df: pd.DataFrame) -> tuple[float, int]:
    bb = int((df["korbb"] == "Walk").sum())
    return _pct(bb, _pa_count(df)), bb


def ea_pct(df: pd.DataFrame) -> tuple[float, int]:
    """Early & Ahead %. PROVISIONAL v1 definition (confirm with coaches):
    share of PAs where the pitcher reached an ahead count (strikes-balls >= 1)
    at any point in the PA. balls/strikes are the recorded count on each pitch.
    """
    if df.empty:
        return 0.0, 0
    ahead = df.groupby(["inning", "pa_of_inning"]).apply(
        lambda p: bool(((p["strikes"] - p["balls"]).max()) >= 1), include_groups=False)
    return _pct(int(ahead.sum()), int(ahead.shape[0])), int(ahead.sum())


def pre2k_pct(df: pd.DataFrame) -> tuple[float, int]:
    """Pre-2K strike %. PROVISIONAL v1: strike% on pitches thrown in counts
    with fewer than 2 strikes."""
    sub = df[df["strikes"] < 2]
    s = int(sub["pitch_call"].isin(_STRIKE_CALLS).sum())
    return _pct(s, len(sub)), s


def twok_kill_pct(df: pd.DataFrame) -> tuple[float, int]:
    """2K Kill %. PROVISIONAL v1: strikeouts / PAs that reached a 2-strike count."""
    if df.empty:
        return 0.0, 0
    g = df.groupby(["inning", "pa_of_inning"])
    reached = g.apply(lambda p: bool((p["strikes"] >= 2).any()), include_groups=False)
    ks = g.apply(lambda p: bool((p["korbb"] == "Strikeout").any()), include_groups=False)
    kills = int((reached & ks).sum())
    return _pct(kills, int(reached.sum())), kills


def count_work_pct(df: pd.DataFrame) -> tuple[float, int]:
    """Count Work %. PROVISIONAL v1: share of pitches thrown in an ahead-or-even
    count (strikes >= balls) -- i.e. staying ahead / not falling behind. The
    count on each pitch is the count BEFORE that pitch is thrown."""
    if df.empty:
        return 0.0, 0
    ahead_even = int((df["strikes"] >= df["balls"]).sum())
    return _pct(ahead_even, len(df)), ahead_even


def barrel_pct(df: pd.DataFrame) -> tuple[float, int]:
    """Barrel %. PROVISIONAL v1 (no launch-angle column in the warehouse):
    barrels / balls in play, barrel ~ exit_speed >= 95 and tagged_hit_type in
    {LineDrive, FlyBall}."""
    bip = df[df["pitch_call"] == "InPlay"]
    barrels = int(((bip["exit_speed"] >= 95)
                   & (bip["tagged_hit_type"].isin({"LineDrive", "FlyBall"}))).sum())
    return _pct(barrels, len(bip)), barrels


def format_ip(outs: int) -> str:
    """Baseball innings-pitched from total outs: whole innings . trailing outs."""
    outs = int(outs or 0)
    return f"{outs // 3}.{outs % 3}"


def barrel_pct_ev(df: pd.DataFrame) -> tuple[float, int]:
    """Barrel% — coaches' SIMPLIFIED def: balls-in-play with exit_speed >= 95,
    over balls-in-play. Intentionally DROPS the LineDrive/FlyBall qualifier that
    `barrel_pct` keeps (the two therefore differ by design). PROVISIONAL."""
    bip = df[df["pitch_call"] == "InPlay"]
    barrels = int((bip["exit_speed"] >= 95).sum())
    return _pct(barrels, len(bip)), barrels


def header_stat_line(df: pd.DataFrame) -> dict:
    """The header line: batters faced (R/L), outs, hits, runs, BB, SO, pitches,
    strike%, and max velo."""
    n = len(df)
    strikes = int(df["pitch_call"].isin(_STRIKE_CALLS).sum()) if n else 0
    mv = df["rel_speed"].dropna().max() if n and "rel_speed" in df.columns else None
    return {
        "bf": _pa_count(df),
        "bf_r": _pa_count(df[df["batter_side"] == "Right"]),
        "bf_l": _pa_count(df[df["batter_side"] == "Left"]),
        "outs": int(df["outs_on_play"].sum()) if len(df) else 0,
        "h": int(df["play_result"].isin(_HIT_RESULTS).sum()) if len(df) else 0,
        "r": int(df["runs_scored"].sum()) if len(df) else 0,
        "bb": int((df["korbb"] == "Walk").sum()) if len(df) else 0,
        "so": int((df["korbb"] == "Strikeout").sum()) if len(df) else 0,
        "pitches": len(df),
        "strike_pct": round(100.0 * strikes / n, 1) if n else 0.0,
        "max_velo": None if mv is None or pd.isna(mv) else round(float(mv), 1),
    }


def game_overall_line(df: pd.DataFrame) -> dict:
    n = len(df)
    calls = df["pitch_call"]
    strikes = int(calls.isin(_STRIKE_CALLS).sum())
    balls = int(calls.isin(_BALL_CALLS).sum())
    swings = int(calls.isin(_SWING_CALLS).sum())
    whiffs = int(calls.isin(_WHIFF_CALLS).sum())
    korbb = df["korbb"]
    first_pitch = df[df["pitch_of_pa"] == 1]
    fps = int(first_pitch["pitch_call"].isin(_STRIKE_CALLS).sum())

    def pct(a, b):
        return round(100.0 * a / b, 1) if b else 0.0

    return {
        "pitches": n,
        "batters_faced": int(df["batters_faced"].max() or 0) if n else 0,
        "strikes": strikes,
        "balls": balls,
        "strike_pct": pct(strikes, n),
        "whiff_pct": pct(whiffs, swings),
        "k": int((korbb == "Strikeout").sum()),
        "bb": int((korbb == "Walk").sum()),
        "first_pitch_strike_pct": pct(fps, len(first_pitch)),
        "runs": int(df["runs_scored"].sum()) if n else 0,
    }


def pitch_characteristics(df: pd.DataFrame) -> pd.DataFrame:
    d = df.assign(_pt=pitch_type(df))
    n = len(d)
    g = d.groupby("_pt")
    out = pd.DataFrame({
        "count": g.size(),
        "avg_velo": g["rel_speed"].mean().round(1),
        "max_velo": g["rel_speed"].max().round(1),
        "spin_rate": g["spin_rate"].mean().round(0),
        "ivb": g["induced_vert_break"].mean().round(1),
        "hb": g["horz_break"].mean().round(1),
        "rel_height": g["rel_height"].mean().round(2),
        "rel_side": g["rel_side"].mean().round(2),
        "extension": g["extension"].mean().round(2),
    }).reset_index(names="pitch")
    out["usage_pct"] = (100.0 * out["count"] / n).round(1)
    return out.sort_values("count", ascending=False).reset_index(drop=True)


def pitch_usage(df: pd.DataFrame) -> pd.DataFrame:
    d = df.assign(_pt=pitch_type(df))
    n = len(d)
    out = (d.groupby("_pt").size().reset_index(name="count")
             .rename(columns={"_pt": "pitch"}))
    out["usage_pct"] = (100.0 * out["count"] / n).round(1)
    return out.sort_values("count", ascending=False).reset_index(drop=True)


def zone_location(df: pd.DataFrame) -> pd.DataFrame:
    d = df.assign(_pt=pitch_type(df),
                  _in_zone=df["izt_zone"].isin(_IN_ZONE_CODES))
    g = d.groupby("_pt")
    out = pd.DataFrame({
        "count": g.size(),
        "in_zone_pct": (100.0 * g["_in_zone"].mean()).round(1),
    }).reset_index(names="pitch")
    return out.sort_values("count", ascending=False).reset_index(drop=True)


def usage_by_count(df: pd.DataFrame) -> pd.DataFrame:
    d = df.assign(_pt=pitch_type(df),
                  count_state=df["balls"].astype(str) + "-" + df["strikes"].astype(str))
    return (d.pivot_table(index="count_state", columns="_pt", values="pitch_no",
                          aggfunc="count", fill_value=0)
              .reset_index())


def splits_by_batter_side(df: pd.DataFrame) -> dict:
    out = {}
    for side in ("Left", "Right"):
        sub = df[df["batter_side"] == side]
        out[side] = {
            "overall": game_overall_line(sub) if len(sub) else game_overall_line(df.iloc[0:0]),
            "usage": pitch_usage(sub) if len(sub) else pitch_usage(df.iloc[0:0]),
        }
    return out


def averages_last5(recent_df: pd.DataFrame) -> pd.DataFrame:
    if recent_df.empty:
        return recent_df
    cols = ["game_date", "away_team_name", "home_team_name",
            "appearance_avg_velo", "appearance_max_velo", "pitch_count"]
    return recent_df[cols].copy()


# ============================ FIGURES =====================================

PITCH_COLORS = {
    "Fastball": "#9A0021", "Sinker": "#7a5230", "Cutter": "#2e8b57",
    "Slider": "#0076A5", "Curveball": "#e08a1e", "ChangeUp": "#6a4c93",
    "Splitter": "#c2185b", "Sweeper": "#00897b",
}
_PT_FALLBACK = ["#9A0021", "#0076A5", "#2e8b57", "#e08a1e", "#6a4c93",
                "#7a5230", "#00897b", "#c2185b"]


def pitch_color(pt: str) -> str:
    """Stable hex color for a pitch type (chips + charts share this)."""
    import zlib
    return PITCH_COLORS.get(pt) or _PT_FALLBACK[zlib.crc32(str(pt).encode()) % len(_PT_FALLBACK)]


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _cov_ellipse(x, y, n_std: float = 1.0, n_pts: int = 40):
    """(xs, ys) polygon for the n_std covariance ellipse of points (x, y),
    or None if <3 points or a degenerate covariance."""
    x = np.asarray(x, dtype=float); y = np.asarray(y, dtype=float)
    if len(x) < 3:
        return None
    cov = np.cov(x, y)
    if not np.all(np.isfinite(cov)):
        return None
    vals, vecs = np.linalg.eigh(cov)
    if np.any(vals <= 0):
        return None
    t = np.linspace(0, 2 * np.pi, n_pts)
    circle = np.stack([np.cos(t), np.sin(t)])
    ell = (vecs @ (np.sqrt(vals)[:, None] * circle)) * n_std
    return ell[0] + x.mean(), ell[1] + y.mean()


_RESULT_LABELS = {
    "StrikeCalled": "Called Strike", "StrikeSwinging": "Swinging Strike",
    "BallCalled": "Ball", "BallinDirt": "Ball (Dirt)",
    "BallIntentional": "Intentional Ball", "AutomaticBall": "Automatic Ball",
    "FoulBallNotFieldable": "Foul", "FoulBallFieldable": "Foul",
    "InPlay": "In Play", "HitByPitch": "HBP",
}


def _spaced(s: str) -> str:
    """'HomeRun' -> 'Home Run'. Mirrors app.data.video._spaced -- kept as a
    tiny local copy rather than an import to avoid coupling this pure,
    no-SQL module to video.py's DB-backed one."""
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(s))


def pretty_result(call: str, play_result: str | None = None) -> str:
    """Human label for a pitch's result. When the ball was put in play,
    prefer the real batted-ball outcome (``play_result``, e.g. "Single",
    "HomeRun" -> "Home Run") over the generic "In Play" pitch_call label;
    otherwise fall back to the ``_RESULT_LABELS`` mapping of ``call``."""
    if play_result is not None and not (isinstance(play_result, float) and pd.isna(play_result)):
        pr = str(play_result)
        if pr not in ("Undefined", "None", ""):
            return _spaced(pr)
    return _RESULT_LABELS.get(call, call)


_SZ = dict(x0=-0.83, x1=0.83, y0=1.5, y1=3.5)  # approx strike zone (ft)


def _base_layout(fig: go.Figure, title: str) -> go.Figure:
    fig.update_layout(
        title=title, template="simple_white",
        font=dict(family="Teko, sans-serif", size=16),
        margin=dict(l=40, r=20, t=50, b=40), showlegend=True,
    )
    return fig


def fig_velo_by_inning(df: pd.DataFrame) -> go.Figure:
    d = df.dropna(subset=["rel_speed"])
    g = d.groupby("inning")["rel_speed"].mean().reset_index()
    fig = go.Figure(go.Bar(x=g["inning"], y=g["rel_speed"].round(1),
                           hovertemplate=("Inning %{x}<br>"
                                          "Avg Velo: %{y:.1f} mph<extra></extra>")))
    fig.update_xaxes(title="Inning"); fig.update_yaxes(title="Avg Velo (mph)")
    return _base_layout(fig, "Velocity by Inning")


def fig_velo_by_pitch(df: pd.DataFrame) -> go.Figure:
    d = df.dropna(subset=["rel_speed"]).sort_values("pitch_no").copy()
    d["_seq"] = range(1, len(d) + 1)          # pitcher's own 1..N for THIS outing
    d["_pt"] = pitch_type(d)
    fig = go.Figure()
    for pt, sub in d.groupby("_pt"):
        fig.add_trace(go.Scatter(x=sub["_seq"], y=sub["rel_speed"],
                                 mode="markers+lines", name=pt,
                                 marker=dict(color=pitch_color(pt)),
                                 line=dict(color=pitch_color(pt)),
                                 hovertemplate=("Pitch No: %{x}<br>"
                                                "Velo: %{y:.1f} mph<br>"
                                                f"{pt}<extra></extra>")))
    fig.update_xaxes(title="Pitch # (this outing)"); fig.update_yaxes(title="Velo (mph)")
    return _base_layout(fig, "Velocity Across Outing")


def fig_movement(df: pd.DataFrame) -> go.Figure:
    d = df.dropna(subset=["horz_break", "induced_vert_break"]).copy()
    d["_pt"] = pitch_type(d)
    fig = go.Figure()
    # 1-sigma covariance ellipse per pitch type, drawn under the markers
    for pt, sub in d.groupby("_pt"):
        ell = _cov_ellipse(sub["horz_break"], sub["induced_vert_break"])
        if ell is None:
            continue
        xs, ys = ell
        fig.add_trace(go.Scatter(
            x=list(xs) + [xs[0]], y=list(ys) + [ys[0]], mode="lines",
            fill="toself", fillcolor=_rgba(pitch_color(pt), 0.15),
            line=dict(color=pitch_color(pt), width=1),
            name=f"{pt} 1σ", showlegend=False, hoverinfo="skip"))
    for pt, sub in d.groupby("_pt"):
        fig.add_trace(go.Scatter(x=sub["horz_break"], y=sub["induced_vert_break"],
                                 mode="markers", name=pt,
                                 marker=dict(color=pitch_color(pt), size=9),
                                 hovertemplate=(f"{pt}<br>HB: %{{x:.1f}} in<br>"
                                                "IVB: %{y:.1f} in<extra></extra>")))
    fig.update_xaxes(title="Horizontal Break (in)", zeroline=True)
    fig.update_yaxes(title="Induced Vert Break (in)", zeroline=True)
    return _base_layout(fig, "Pitch Movement")


def _add_zone(fig: go.Figure) -> None:
    fig.add_shape(type="rect", line=dict(color="black", width=2), **_SZ)


def result_labels(d: pd.DataFrame) -> pd.Series:
    """Pretty result label per pitch, using play_result when the column is
    present (the live CAPS read path always includes it -- see
    pitching_caps._PITCH_SELECT) and falling back to the pitch_call-only
    label otherwise (e.g. minimal hand-built frames in tests)."""
    if "play_result" not in d.columns:
        return d["pitch_call"].map(pretty_result)
    return d.apply(lambda r: pretty_result(r["pitch_call"], r["play_result"]), axis=1)


def fig_location(df: pd.DataFrame) -> go.Figure:
    d = df.dropna(subset=["plate_loc_side", "plate_loc_height"]).copy()
    d["_pt"] = pitch_type(d)
    d["_res"] = result_labels(d)
    fig = go.Figure()
    for pt, sub in d.groupby("_pt"):
        fig.add_trace(go.Scatter(
            x=sub["plate_loc_side"], y=sub["plate_loc_height"], mode="markers", name=pt,
            marker=dict(color=pitch_color(pt), size=9), customdata=sub[["_res"]],
            hovertemplate=f"{pt}<br>Result: %{{customdata[0]}}<extra></extra>"))
    _add_zone(fig)
    fig.update_xaxes(title="Plate Side (ft)", range=[-2.5, 2.5])
    fig.update_yaxes(title="Plate Height (ft)", range=[0, 5], scaleanchor="x")
    return _base_layout(fig, "Pitch Location (Catcher View)")


def fig_location_split(df: pd.DataFrame) -> go.Figure:
    d = df.dropna(subset=["plate_loc_side", "plate_loc_height"]).copy()
    d["_pt"] = pitch_type(d)
    d["_res"] = result_labels(d)
    fig = go.Figure()
    for pt, sub in d.groupby("_pt"):
        fig.add_trace(go.Scatter(
            x=sub["plate_loc_side"], y=sub["plate_loc_height"], mode="markers", name=pt,
            marker=dict(color=pitch_color(pt), size=9), customdata=sub[["_res"]],
            hovertemplate=f"{pt}<br>Result: %{{customdata[0]}}<extra></extra>"))
    _add_zone(fig)
    fig.update_xaxes(title="Plate Side (ft)", range=[-2.5, 2.5])
    fig.update_yaxes(title="Plate Height (ft)", range=[0, 5], scaleanchor="x")
    return _base_layout(fig, "Location by Pitch Type")


def fig_velo_trend(trend_df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if not trend_df.empty:
        fig.add_trace(go.Scatter(x=trend_df["game_date"], y=trend_df["avg_velo"],
                                 mode="markers+lines", name="Avg Velo"))
    fig.update_xaxes(title="Game Date"); fig.update_yaxes(title="Avg Velo (mph)")
    return _base_layout(fig, "Velocity Trend (Season)")


def _heatmap(d: pd.DataFrame, title: str) -> go.Figure:
    fig = go.Figure(go.Histogram2dContour(
        x=d["plate_loc_side"], y=d["plate_loc_height"],
        colorscale="YlOrRd", showscale=False, ncontours=12,
    ))
    _add_zone(fig)
    fig.update_xaxes(title="", range=[-2.5, 2.5], showticklabels=False)
    fig.update_yaxes(title="", range=[0, 5], scaleanchor="x", showticklabels=False)
    out = _base_layout(fig, title); out.update_layout(showlegend=False)
    return out


def fig_heatmap_overall(df: pd.DataFrame) -> go.Figure:
    d = df.dropna(subset=["plate_loc_side", "plate_loc_height"])
    return _heatmap(d, "Location Heatmap (All Pitches)")


def fig_heatmaps_by_pitch_type(df: pd.DataFrame) -> list:
    d = df.dropna(subset=["plate_loc_side", "plate_loc_height"]).copy()
    d["_pt"] = pitch_type(d)
    items = []
    for pt, sub in d.groupby("_pt"):
        if len(sub) >= 3:
            items.append((pt, _heatmap(sub, pt)))
    return items


def fig_outings_velo_trend(recent_df: pd.DataFrame) -> go.Figure:
    """Avg + Max velo across the selected outings (chronological)."""
    fig = go.Figure()
    if not recent_df.empty:
        d = recent_df.sort_values("game_date")
        fig.add_trace(go.Scatter(x=d["game_date"], y=d["appearance_avg_velo"].round(1),
                                 mode="markers+lines", name="Avg Velo",
                                 line=dict(color="#0076A5"),
                                 hovertemplate=("Date: %{x}<br>"
                                                "Avg Velo: %{y:.1f} mph<extra></extra>")))
        fig.add_trace(go.Scatter(x=d["game_date"], y=d["appearance_max_velo"].round(1),
                                 mode="markers+lines", name="Max Velo",
                                 line=dict(color="#9A0021"),
                                 hovertemplate=("Date: %{x}<br>"
                                                "Max Velo: %{y:.1f} mph<extra></extra>")))
    fig.update_xaxes(title="Outing Date"); fig.update_yaxes(title="Velo (mph)")
    return _base_layout(fig, "Velocity Trend (Selected Outings)")


def count_states(df: pd.DataFrame) -> list[str]:
    """Sorted distinct '{balls}-{strikes}' count states present in df."""
    if df is None or df.empty:
        return []
    cs = (df["balls"].astype("Int64").astype(str) + "-"
          + df["strikes"].astype("Int64").astype(str))
    return sorted(c for c in cs.dropna().unique() if "<NA>" not in c)


def fig_heatmap(df: pd.DataFrame) -> go.Figure:
    """White->yellow->red 2-D density heatmap of plate locations, over the zone."""
    d = df.dropna(subset=["plate_loc_side", "plate_loc_height"]) if df is not None else None
    fig = go.Figure()
    if d is not None and not d.empty:
        fig.add_trace(go.Histogram2dContour(
            x=d["plate_loc_side"], y=d["plate_loc_height"],
            colorscale=[[0.0, "white"], [0.5, "yellow"], [1.0, "red"]],
            contours=dict(coloring="fill"), line=dict(width=0),
            showscale=False, ncontours=18, hoverinfo="skip"))
    _add_zone(fig)
    fig.update_xaxes(title="Plate Side (ft)", range=[-2.5, 2.5])
    fig.update_yaxes(title="Plate Height (ft)", range=[0, 5], scaleanchor="x")
    _base_layout(fig, "Location Heatmap (Catcher View)")
    fig.update_layout(showlegend=False)
    return fig


# ============================ TABLE ASSEMBLERS ============================

def _r1(x) -> float | None:
    """Round to 1 dp, or None if NaN/empty."""
    return None if x is None or pd.isna(x) else round(float(x), 1)


def _metric_rows(df: pd.DataFrame, specs: list[tuple]) -> list[dict]:
    rhh = df[df["batter_side"] == "Right"]
    lhh = df[df["batter_side"] == "Left"]
    rows = []
    for label, key, fn in specs:
        pct, cnt = fn(df)
        rows.append({
            "metric": label, "key": key,
            "value_pct": pct, "value_count": cnt,
            "vrhh": fn(rhh)[0], "vlhh": fn(lhh)[0],
        })
    return rows


def process_metrics(df: pd.DataFrame) -> list[dict]:
    return _metric_rows(df, [
        ("Strike%", "strike_pct", strike_pct),
        ("FPS%", "fps_pct", fps_pct),
        ("E&A%", "ea_pct", ea_pct),
        ("Pre2K%", "pre2k_pct", pre2k_pct),
        ("2K Kill%", "twok_kill_pct", twok_kill_pct),
    ])


def outcome_metrics(df: pd.DataFrame) -> list[dict]:
    return _metric_rows(df, [
        ("K%", "k_pct", k_pct),
        ("BB%", "bb_pct", bb_pct),
        ("Barrel%", "barrel_pct", barrel_pct),
    ])


def pitch_usage_table(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []
    d = df.assign(_pt=pitch_type(df))
    n = len(d)
    n_r = len(d[d["batter_side"] == "Right"]) or 1
    n_l = len(d[d["batter_side"] == "Left"]) or 1
    n_2k = len(d[d["strikes"] == 2]) or 1
    rows = []
    for pt, sub in d.groupby("_pt"):
        rows.append({
            "pitch": pt,
            "strike_pct": _pct(int(sub["pitch_call"].isin(_STRIKE_CALLS).sum()), len(sub)),
            "usage_pct": _pct(len(sub), n),
            # PROVISIONAL: share of the pitcher's 2-strike-count pitches that
            # were this pitch type.
            "twok_usage_pct": _pct(len(sub[sub["strikes"] == 2]), n_2k),
            "vrhh": _pct(len(sub[sub["batter_side"] == "Right"]), n_r),
            "vlhh": _pct(len(sub[sub["batter_side"] == "Left"]), n_l),
            "_count": len(sub),
        })
    rows.sort(key=lambda r: r["_count"], reverse=True)
    for r in rows:
        del r["_count"]
    return rows


def fastball_callout(df: pd.DataFrame, pt_col: str = "tagged_pitch_type") -> dict:
    """Fastball Avg Velo / Max Velo / Avg Spin for a pitch df."""
    none = {"avg_velo": None, "max_velo": None, "avg_spin": None}
    if df is None or df.empty or pt_col not in df.columns:
        return none
    fb = df[df[pt_col] == "Fastball"]
    v = fb["rel_speed"].dropna()
    s = fb["spin_rate"].dropna() if "spin_rate" in fb else None
    if v.empty:
        return none
    return {"avg_velo": round(float(v.mean()), 1), "max_velo": round(float(v.max()), 1),
            "avg_spin": (int(round(float(s.mean()))) if s is not None and not s.empty else None)}


def movement_summary(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []
    d = df.assign(_pt=pitch_type(df))
    rows = []
    for pt, sub in d.groupby("_pt"):
        rhh = sub[sub["batter_side"] == "Right"]
        lhh = sub[sub["batter_side"] == "Left"]
        rows.append({
            "pitch": pt,
            "velo_avg": _r1(sub["rel_speed"].mean()),
            "velo_max": _r1(sub["rel_speed"].max()),
            "ivb_avg": _r1(sub["induced_vert_break"].mean()),
            "ivb_rhh": _r1(rhh["induced_vert_break"].mean()) if len(rhh) else None,
            "ivb_lhh": _r1(lhh["induced_vert_break"].mean()) if len(lhh) else None,
            "hb_avg": _r1(sub["horz_break"].mean()),
            "hb_rhh": _r1(rhh["horz_break"].mean()) if len(rhh) else None,
            "hb_lhh": _r1(lhh["horz_break"].mean()) if len(lhh) else None,
            # VAA — average vertical approach angle (deg); replaces old "Spread".
            "vaa": _r1(sub["vert_appr_angle"].mean()),
            "_count": len(sub),
        })
    rows.sort(key=lambda r: r["_count"], reverse=True)
    for r in rows:
        del r["_count"]
    return rows
