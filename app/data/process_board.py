"""All Things Process board: per-pitcher process leaderboard over GAMES.

Rebuilds the coaches' "Team Process" Google Sheet (last used Spring 2026,
e.g. "Team Process - Non-Conference Spring 3_3_2026"): one row per LMU
pitcher with Strike% / FPS% / Pre2K% / E&A% / K% / Barrel% / BB% / 2K Kill%
plus fastball velo, under three reference rows -- the coaches' fixed LMU
Baseline, the selected cycle's average (all game types), and the team
average for the selected game types.

"Throwing on the stadium field" = GAMES (games, scrimmages, intrasquads,
live ABs loaded as games), never BULLPEN. Every metric is the same
`app.data.pitching` transform the postgame report uses, so this board can't
disagree with a pitcher's own report.
"""
from __future__ import annotations

import pandas as pd

from app.data import pitching as P
from app.data import velo_board
from app.data.cache import cached
from app.data.pitching_caps import LMU_PITCHER_TEAM, _PITCH_SELECT
from app.db import query_df

# (key, label, transform, higher_is_better)
METRICS: tuple[tuple, ...] = (
    ("strike_pct", "Strike%", P.strike_pct, True),
    ("fps_pct", "FPS%", P.fps_pct, True),
    ("pre2k_pct", "Pre2K%", P.pre2k_pct, True),
    ("ea_pct", "E&A%", P.ea_pct, True),
    ("k_pct", "K%", P.k_pct, True),
    ("barrel_pct", "Barrel%", P.barrel_pct, False),
    ("bb_pct", "BB%", P.bb_pct, False),
    ("twok_kill_pct", "2K Kill%", P.twok_kill_pct, True),
)
VELO_COLS: tuple[tuple, ...] = (("velo_avg", "Velo Avg"), ("velo_max", "Velo Max"))

# The coaches' standing targets, copied from the Team Process sheet. No velo
# target was ever set on the sheet, so velo stays blank on this row.
BASELINE: dict[str, float] = {
    "strike_pct": 55.0, "fps_pct": 60.0, "pre2k_pct": 50.0, "ea_pct": 70.0,
    "k_pct": 25.0, "barrel_pct": 10.0, "bb_pct": 10.0, "twok_kill_pct": 75.0,
}

CYCLES = velo_board.VELO_CYCLES

# Handedness filter: the pitcher board splits on the batter's side.
HAND_COL = "batter_side"
HAND_LABEL = "Batters"
HAND_OPTIONS = (("all", "All Batters"), ("Right", "vs RHH"), ("Left", "vs LHH"))
# Under a Pitch Type filter these are scored over the PAs that ENDED on a
# selected pitch (a K% "on the slider"); the rest use only the selected pitches.
PA_METRICS = frozenset({"k_pct", "bb_pct", "ea_pct", "twok_kill_pct"})

# Per-game columns the Date/Games filters need, shared with the hitter board.
GAME_SELECT = "Date AS game_date, HomeTeam AS home_team, AwayTeam AS away_team"


def cycle_bounds(season_label: str, cycle: str) -> tuple[str, str]:
    return velo_board.velo_cycle_bounds(season_label, cycle)


def cycle_display(season_label: str, cycle: str) -> str:
    """'Fall 2025' / 'Spring 2026' -- the calendar year the cycle falls in."""
    a, b = season_label.split("/")
    return f"{cycle} {a if cycle == 'Fall' else b}"


@cached
def _pitches(start: str, end: str) -> pd.DataFrame:
    return query_df(
        f"SELECT {_PITCH_SELECT}, Pitcher AS pitcher_name, {GAME_SELECT}, "
        f"COALESCE(GameType, 'Untyped') AS game_type "
        f"FROM GAMES WHERE PitcherTeam = :t AND Date BETWEEN :s AND :e "
        f"ORDER BY GameID, PitchNo",
        {"t": LMU_PITCHER_TEAM, "s": str(start), "e": str(end)},
    )


def window_pitches(start: str, end: str, game_types=None) -> pd.DataFrame:
    """LMU pitches in [start, end], optionally limited to some GameTypes
    (None = every type; GameType NULL is offered as 'Untyped')."""
    df = _pitches(start, end)
    if game_types and not df.empty:
        df = df[df["game_type"].isin(list(game_types))]
    return df


@cached
def _game_types_for(start: str, end: str) -> list[str]:
    df = _pitches(start, end)
    return sorted(df["game_type"].unique()) if not df.empty else []


def game_types(start: str, end: str) -> list[str]:
    return list(_game_types_for(start, end))


def narrow(df: pd.DataFrame, start=None, end=None, game_ids=None) -> pd.DataFrame:
    """Keep pitches dated [start, end] (inclusive; either None = no date
    limit) and, when `game_ids` is given, only those games."""
    if df.empty:
        return df
    if start and end:
        day = df["game_date"].astype(str).str[:10]
        df = df[(day >= str(start)[:10]) & (day <= str(end)[:10])]
    if game_ids:
        df = df[df["game_id"].astype(str).isin({str(g) for g in game_ids})]
    return df


def games_in(df: pd.DataFrame) -> pd.DataFrame:
    """One row per game in a pitch frame, newest first:
    game_id / game_date / GameLabel ('YYYY-MM-DD vs OPP', '@ OPP', or
    'Intrasquad', plus ' · GameType' when Trackman typed it). LMU is found by
    team code: the Fall 2026 files carry a different HomeTeamForeignID than
    the 78 older games use."""
    cols = ["game_id", "game_date", "GameLabel"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    g = (df.assign(game_id=df["game_id"].astype(str),
                   game_date=df["game_date"].astype(str).str[:10])
         .drop_duplicates("game_id")
         .sort_values(["game_date", "game_id"], ascending=[False, False])
         .reset_index(drop=True))
    lmu_home = g["home_team"] == LMU_PITCHER_TEAM
    opp = g["away_team"].where(lmu_home, g["home_team"]).fillna("?")
    vs = pd.Series("vs ", index=g.index).where(lmu_home, "@ ") + opp
    vs = vs.where(opp != LMU_PITCHER_TEAM, "Intrasquad")
    typed = g["game_type"].astype(str)
    suffix = (" · " + typed).where(typed != "Untyped", "")
    g["GameLabel"] = g["game_date"] + " " + vs + suffix
    return g[cols]


def by_hand(df: pd.DataFrame, col: str, hand=None) -> pd.DataFrame:
    if not hand or hand == "all" or df.empty:
        return df
    return df[df[col] == hand]


def pitch_types_in(df: pd.DataFrame) -> list[str]:
    """Pitch types thrown in a frame (tagged, falling back to auto), most
    thrown first; Undefined/Other aren't offered as a filter choice."""
    if df.empty:
        return []
    kinds = P.pitch_type(df)
    kinds = kinds[~kinds.isin(["Undefined", "Other"])]
    return list(kinds.value_counts().index)


def by_pitch_type(df: pd.DataFrame, pitch_types=None) -> pd.DataFrame:
    if not pitch_types or df.empty:
        return df
    return df[P.pitch_type(df).isin(list(pitch_types))]


def window_bounds(season_label: str, cycle: str, start=None, end=None):
    """The (start, end) the Date filter asks for, clamped inside the cycle.
    (None, None) when it spans the whole cycle, so that view shares the
    unfiltered cache entry."""
    c_start, c_end = cycle_bounds(season_label, cycle)
    if not start or not end:
        return None, None
    s, e = max(str(start)[:10], str(c_start)), min(str(end)[:10], str(c_end))
    if s <= str(c_start) and e >= str(c_end):
        return None, None
    return s, e


def latest_day(pitches_fn, season_label: str, cycle: str) -> str:
    """The cycle's most recent game day (the Past Day/Week/Month anchor), or
    the cycle's last day when nothing has been thrown yet."""
    c_start, c_end = cycle_bounds(season_label, cycle)
    df = pitches_fn(c_start, c_end)
    if df.empty:
        return str(c_end)
    return str(df["game_date"].astype(str).str[:10].max())


def filter_key(pitches_fn, types_fn, season_label, cycle, game_types=None,
               start=None, end=None, game_ids=None, hand=None, pitch_types=None) -> tuple:
    """Normalize a filter selection to the board's cache key. "Everything
    selected" collapses to the empty/None form so it shares one entry with
    the unfiltered view (the one warmup.py pre-builds)."""
    c_start, c_end = cycle_bounds(season_label, cycle)
    types = sorted(game_types) if game_types else []
    if not types or set(types) >= set(types_fn(c_start, c_end)):
        types = []
    start, end = window_bounds(season_label, cycle, start, end)
    ids = sorted({str(g) for g in game_ids}) if game_ids else []
    if ids:
        df = pitches_fn(c_start, c_end)
        if types:
            df = df[df["game_type"].isin(types)]
        in_window = set(games_in(narrow(df, start, end))["game_id"])
        if in_window <= set(ids):
            ids = []
    hand = hand if hand in ("Right", "Left") else None
    kinds = sorted(pitch_types) if pitch_types else []
    if kinds and set(kinds) >= set(pitch_types_in(pitches_fn(c_start, c_end))):
        kinds = []
    return season_label, cycle, tuple(types), start, end, tuple(ids), hand, tuple(kinds)


def latest_game_date(season_label: str, cycle: str) -> str:
    return latest_day(_pitches, season_label, cycle)


def pitch_types(season_label: str, cycle: str) -> list[str]:
    return pitch_types_in(_pitches(*cycle_bounds(season_label, cycle)))


def games(season_label: str, cycle: str, game_types=None, start=None, end=None) -> pd.DataFrame:
    """Games in the cycle under the Game Type + Date filters, newest first."""
    c_start, c_end = cycle_bounds(season_label, cycle)
    start, end = window_bounds(season_label, cycle, start, end)
    return games_in(narrow(window_pitches(c_start, c_end, game_types), start, end))


def _velo(df: pd.DataFrame, pitch_types=None) -> tuple[float | None, float | None]:
    fb = df[P.pitch_type(df).isin(list(pitch_types or velo_board.VELO_PITCH_TYPES))]
    fb = velo_board._clip_velo_outliers(fb)
    v = fb["rel_speed"].dropna() if fb is not None and not fb.empty else pd.Series(dtype=float)
    if v.empty:
        return None, None
    return round(float(v.mean()), 1), round(float(v.max()), 1)


def _pas_ending_on(df: pd.DataFrame, pitch_types) -> pd.DataFrame:
    """Every pitch of the PAs whose last pitch is one of `pitch_types`."""
    keys = ["game_id", "inning", "pa_of_inning"]
    df = df.reset_index(drop=True)
    last = df.loc[df.groupby(keys)["pitch_of_pa"].idxmax()]
    ended = last[P.pitch_type(last).isin(list(pitch_types))][keys]
    return df.merge(ended, on=keys, how="inner")


def metric_line(df: pd.DataFrame, pitch_types=None) -> dict:
    """Every board metric for one pitch frame (a pitcher, or the whole team
    pooled). Percent metrics with no denominator come back None, not 0.
    With `pitch_types`, pitch metrics and velo use only those pitches and
    PA_METRICS use the PAs that ended on one (see PA_METRICS)."""
    # Intrasquads put LMU pitchers in BOTH halves of an inning, and the PA
    # key (game_id, inning, pa_of_inning) has no half -- fold the half into
    # game_id so top and bottom PAs stay separate in the pooled team line.
    if "top_bottom" in df.columns and len(df):
        df = df.assign(game_id=df["game_id"].astype(str) + "|" + df["top_bottom"].astype(str))
    pa_df = df
    if pitch_types and len(df):
        pa_df = _pas_ending_on(df, pitch_types)
        df = by_pitch_type(df, pitch_types)
    out: dict = {"pitches": int(len(df))}
    denominators = {
        "fps_pct": lambda d: int((d["pitch_of_pa"] == 1).sum()),
        "pre2k_pct": lambda d: int((d["strikes"] < 2).sum()),
        "barrel_pct": lambda d: int((d["pitch_call"] == "InPlay").sum()),
        "twok_kill_pct": lambda d: int((d["strikes"] >= 2).sum()),
    }
    for key, _label, fn, _hib in METRICS:
        src = pa_df if key in PA_METRICS else df
        has_denominator = len(src) > 0 and denominators.get(key, len)(src) > 0
        out[key] = fn(src)[0] if has_denominator else None
    out["velo_avg"], out["velo_max"] = _velo(df, pitch_types) if len(df) else (None, None)
    return out


def _with_hand(name: str, throws: pd.Series) -> str:
    hand = throws.dropna()
    hand = hand.mode().iloc[0] if not hand.empty else ""
    return f"{name} ({hand[0]})" if hand in ("Right", "Left") else name


def pitcher_rows(df: pd.DataFrame, pitch_types=None) -> list[dict]:
    """One metric line per pitcher (by GAMES.Pitcher name, so a pitcher with
    split Trackman ids stays one row), alphabetical like the sheet. Under a
    Pitch Type filter, pitchers who threw none of those pitches drop out."""
    if df.empty:
        return []
    rows = []
    for name, g in df.groupby("pitcher_name", sort=True):
        if pitch_types and by_pitch_type(g, pitch_types).empty:
            continue
        row = metric_line(g, pitch_types)
        row["pitcher"] = _with_hand(str(name), g["pitcher_throws"])
        rows.append(row)
    return rows


def best_values(rows: list[dict]) -> dict[str, float]:
    """The column leader per metric (max, or min where lower is better, e.g.
    BB%/Barrel%) -- ties all count as the leader."""
    best = {}
    direction = {k: hib for k, _l, _f, hib in METRICS}
    direction.update({k: True for k, _l in VELO_COLS})
    for key, hib in direction.items():
        vals = [r[key] for r in rows if r.get(key) is not None]
        if vals:
            best[key] = max(vals) if hib else min(vals)
    return best


def meets_baseline(key: str, value) -> bool | None:
    """Whether `value` hits the coaches' baseline for `key` (None when the
    metric has no baseline or the value is missing)."""
    target = BASELINE.get(key)
    if target is None or value is None:
        return None
    higher = next(hib for k, _l, _f, hib in METRICS if k == key)
    return value >= target if higher else value <= target


def board(season_label: str, cycle: str, game_types=None, start=None, end=None,
          game_ids=None, hand=None, pitch_types=None) -> dict:
    """Everything the page renders: the reference rows + pitcher rows, under
    the Game Type / Date / Games / Batters / Pitch Type filters (empty Games
    or Pitch Type = all of them)."""
    return _board(*filter_key(_pitches, _game_types_for, season_label, cycle,
                              game_types, start, end, game_ids, hand, pitch_types))


@cached
def _board(season_label: str, cycle: str, game_types: tuple, start=None, end=None,
           game_ids: tuple = (), hand=None, pitch_types: tuple = ()) -> dict:
    game_types = list(game_types) or None
    c_start, c_end = cycle_bounds(season_label, cycle)
    df = narrow(window_pitches(c_start, c_end, game_types), start, end, game_ids)
    df = by_hand(df, HAND_COL, hand)
    # The cycle row is the whole selected cycle (every game type, date,
    # batter and pitch), so it stays put while the pitcher rows filter.
    filtered = bool(game_types or start or game_ids or hand)
    cycle_df = window_pitches(c_start, c_end) if filtered else df

    baseline = dict(BASELINE, pitcher="LMU Baseline", kind="baseline")
    cycle_row = dict(metric_line(cycle_df) if not cycle_df.empty else {},
                     pitcher=f"LMU {cycle_display(season_label, cycle)} Average",
                     kind="cycle")
    pitchers = pitcher_rows(df, list(pitch_types) or None)
    return {"summary": [baseline, cycle_row], "pitchers": pitchers,
            "best": best_values(pitchers)}
