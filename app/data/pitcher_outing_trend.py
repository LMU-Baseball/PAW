"""Data behind the pitching dashboard's "Outing Trend" tab: for the pitcher's
last-N outings (same set the tab's table/velo-trend already show), each of
the 8 standard process/outcome metrics plotted as three lines -- this
pitcher, the LMU team average on that same date, and an LMU baseline target
-- plus a velocity-by-pitch-type trend across the same outings.

Owns its own queries (unlike `pitcher_development.py`, which is a pure
composition layer) because "team average on this date" and "season-wide team
average" have no existing query to delegate to -- `pitching_caps.py` only
ever scopes to one pitcher's sibling-id union.

**Baseline** = the coach-tunable goal thresholds already in
`cauldron.read_scoring()` (Strike%/FPS%/E&A%/2K Kill%/K%/BB%/Barrel% all have
a cauldron entry). One metric, Pre-2K%, has no cauldron equivalent (cauldron
tracks a *different* "Pre-2K Zone" metric) -- and any metric whose threshold
is unset (fresh DB, scoring never seeded) falls back the same way: the LMU
team's full-season average for that metric, computed once per season and
cached.

**Team average** = the same metric recomputed across ALL LMU pitchers'
pitches on the exact calendar date of the outing (doubleheaders collapse to
one team value for that date, matching how the date axis works). This is
COACH-FACING analytics -- getting "team average" or "baseline" wrong
produces a misleading reference line, so keep both anchored to real,
re-queryable data rather than a hardcoded guess.
"""
from __future__ import annotations

import pandas as pd

from app.data import cauldron
from app.data import pitching as P
from app.data import pitching_caps as caps
from app.data import seasons
from app.data.cache import cached
from app.db import query_df

# (key, label, fn) in the reference report's display order: Strike%, FPS%,
# Pre-2K%, E&A%, K%, BB%, Barrel%, 2K Kill%. `fn` is one of pitching.py's
# existing pure metric transforms -- REUSE, not a second definition.
METRIC_SPECS: tuple[tuple[str, str, object], ...] = (
    ("strike_pct", "Strike%", P.strike_pct),
    ("fps_pct", "FPS%", P.fps_pct),
    ("pre2k_pct", "Pre-2K%", P.pre2k_pct),
    ("ea_pct", "E&A%", P.ea_pct),
    ("k_pct", "K%", P.k_pct),
    ("bb_pct", "BB%", P.bb_pct),
    ("barrel_pct", "Barrel%", P.barrel_pct),
    ("twok_kill_pct", "2K Kill%", P.twok_kill_pct),
)

# Our metric key -> cauldron_scoring's metric key, for the ones that line up.
# pre2k_pct is deliberately absent: cauldron's "pre2k_zone" is a different
# metric (in-zone rate, not strike rate), so it can't supply this baseline.
_CAULDRON_KEY = {
    "strike_pct": "strike_pct", "fps_pct": "first_pitch_strike",
    "ea_pct": "early_ahead", "twok_kill_pct": "twok_kill",
    "k_pct": "k_pct", "bb_pct": "bb_pct", "barrel_pct": "barrel",
}

# Pitch-level columns the team query needs to feed METRIC_SPECS' functions,
# plus Date/GameID for grouping -- a scoped-down `pitching_caps._PITCH_SELECT`.
_TEAM_SELECT = """
    PitchCall AS pitch_call, PitchofPA AS pitch_of_pa, KorBB AS korbb,
    Balls AS balls, Strikes AS strikes, Inning AS inning,
    PAofInning AS pa_of_inning, ExitSpeed AS exit_speed,
    TaggedHitType AS tagged_hit_type, GameID AS game_id, `Date` AS game_date
"""


def _team_pitches_on_dates(dates: list[str]) -> pd.DataFrame:
    """All LMU pitchers' pitches on exactly these calendar dates."""
    if not dates:
        return pd.DataFrame()
    ph = ", ".join(f":d{i}" for i in range(len(dates)))
    params = {f"d{i}": str(d) for i, d in enumerate(dates)}
    params["team"] = caps.LMU_PITCHER_TEAM
    df = query_df(
        f"SELECT {_TEAM_SELECT} FROM GAMES "
        f"WHERE PitcherTeam = :team AND `Date` IN ({ph})",
        params,
    )
    df["game_date"] = df["game_date"].astype(str)
    return df


def _team_pitches_range(start, end) -> pd.DataFrame:
    """All LMU pitchers' pitches in [start, end] -- for the season-average
    baseline fallback."""
    df = query_df(
        f"SELECT {_TEAM_SELECT} FROM GAMES "
        f"WHERE PitcherTeam = :team AND `Date` BETWEEN :start AND :end",
        {"team": caps.LMU_PITCHER_TEAM, "start": str(start), "end": str(end)},
    )
    df["game_date"] = df["game_date"].astype(str)
    return df


def _metric_values(df: pd.DataFrame) -> dict[str, float]:
    """Every METRIC_SPECS value for one pitch dataframe (0.0 on an empty/zero
    denominator, matching pitching.py's `_pct` -- never None, so a light day
    reads as 0 rather than breaking the line)."""
    return {key: fn(df)[0] for key, _label, fn in METRIC_SPECS}


@cached
def _season_team_baselines(season: str) -> dict[str, float]:
    """Full-season LMU team average per metric -- the baseline fallback for
    any metric without a cauldron threshold."""
    s, e = seasons.season_bounds(season)
    df = _team_pitches_range(s, e)
    if df.empty:
        return {key: 0.0 for key, _label, _fn in METRIC_SPECS}
    return _metric_values(df)


@cached
def _baselines(season: str) -> dict[str, float]:
    """One flat target value per metric key: cauldron's coach-tuned threshold
    where one exists and is set, else the team's season average."""
    scoring = cauldron.read_scoring()
    thresholds = {}
    if not scoring.empty:
        thresholds = dict(zip(scoring["metric"], scoring["threshold"]))
    fallback = _season_team_baselines(season)
    out = {}
    for key, _label, _fn in METRIC_SPECS:
        ck = _CAULDRON_KEY.get(key)
        val = thresholds.get(ck) if ck else None
        out[key] = float(val) if val is not None and not pd.isna(val) else fallback.get(key, 0.0)
    return out


def outing_trend(pitcher_id, game_id, n: int = 5) -> dict:
    """Everything the Outing Trend tab needs: per-metric player/team/baseline
    series across the pitcher's last `n` outings (same anchor/count semantics
    as `pitching_caps.recent_outings`, so this matches the table above it
    exactly), plus a velocity-by-pitch-type series across those same outings.

    Empty-safe: fewer than 2 outings returns empty rows/velo (a single point
    isn't a trend), same threshold the bullpen Development Trends tab uses.

    No `season` parameter: the baseline's season-average fallback (see module
    docstring) is derived from the outings' OWN most recent date, not from
    whatever season happens to be selected in the dashboard's season
    dropdown. Trusting the caller's season here was a real bug during
    development -- a coach reviewing last spring's trailing outings from
    today (already in the new academic year) got an all-zero fallback
    baseline because "current season" had no games yet.
    """
    empty = {"rows": [], "velo": {"dates": [], "series": {}}}
    if pitcher_id is None:
        return empty
    outings = caps.recent_outings(int(pitcher_id), game_id, int(n))
    if len(outings) < 2:
        return empty

    outings = outings.sort_values("game_date").reset_index(drop=True)  # chronological
    game_ids = outings["game_id"].astype(str).tolist()
    dates = outings["game_date"].astype(str).tolist()
    date_by_gid = dict(zip(game_ids, dates))

    start, end = outings["game_date"].min(), outings["game_date"].max()
    player_df = caps.range_pitches_for(int(pitcher_id), start, end)
    if not player_df.empty:
        player_df = player_df[player_df["game_id"].astype(str).isin(game_ids)].copy()
        player_df["game_date"] = player_df["game_id"].astype(str).map(date_by_gid)

    team_df = _team_pitches_on_dates(sorted(set(dates)))
    baselines = _baselines(seasons.season_label_for(dates[-1]))

    player_by_date = {d: sub for d, sub in (player_df.groupby("game_date") if not player_df.empty else [])}
    team_by_date = {d: sub for d, sub in (team_df.groupby("game_date") if not team_df.empty else [])}

    rows = []
    for key, label, fn in METRIC_SPECS:
        player_vals = [fn(player_by_date[d])[0] if d in player_by_date else 0.0 for d in dates]
        team_vals = [fn(team_by_date[d])[0] if d in team_by_date else 0.0 for d in dates]
        rows.append({
            "key": key, "label": label, "dates": dates,
            "player": player_vals, "team": team_vals, "baseline": baselines.get(key, 0.0),
        })

    velo_series: dict[str, list] = {}
    if not player_df.empty and "rel_speed" in player_df.columns:
        pdf = player_df.assign(_pt=P.pitch_type(player_df)).dropna(subset=["rel_speed"])
        for pt, sub in pdf.groupby("_pt"):
            by_date = sub.groupby("game_date")["rel_speed"].mean()
            velo_series[str(pt)] = [
                round(float(by_date[d]), 1) if d in by_date.index else None for d in dates
            ]

    return {"rows": rows, "velo": {"dates": dates, "series": velo_series}}
