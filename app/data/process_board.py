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
from app.data.hitting import CHASE_ZONES, attack_zone
from app.data.pitching_caps import LMU_PITCHER_TEAM, _PITCH_SELECT
from app.db import query_df

_CONTACT_CALLS = P._SWING_CALLS - P._WHIFF_CALLS
# Zone = Heart + Shadow, the complement of Chase%'s Chase + Waste, so every
# located pitch is one or the other.
_ZONE_AREAS = ("Heart", "Shadow")


def _zones(df: pd.DataFrame) -> pd.Series:
    return pd.Series([attack_zone(s, h) for s, h in zip(df["plate_loc_side"], df["plate_loc_height"])],
                     index=df.index, dtype=object)


def _swings(df: pd.DataFrame) -> pd.Series:
    return df["pitch_call"].isin(P._SWING_CALLS)


def _two_k(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["strikes"] >= 2]


def contact_2k_pct(df: pd.DataFrame) -> tuple[float, int]:
    """Of hitters' swings in 2-strike counts, the share put in play or fouled."""
    sub = _two_k(df)
    contact = int(sub["pitch_call"].isin(_CONTACT_CALLS).sum())
    return P._pct(contact, int(_swings(sub).sum())), contact


def swstr_2k_pct(df: pd.DataFrame) -> tuple[float, int]:
    """Swinging strikes on every pitch thrown in a 2-strike count."""
    sub = _two_k(df)
    whiffs = int(sub["pitch_call"].isin(P._WHIFF_CALLS).sum())
    return P._pct(whiffs, len(sub)), whiffs


def zone_swing_pct(df: pd.DataFrame) -> tuple[float, int]:
    """Hitters' swings on pitches in the Heart/Shadow zones."""
    sub = df[_zones(df).isin(_ZONE_AREAS)]
    swings = int(_swings(sub).sum())
    return P._pct(swings, len(sub)), swings


def chase_2k_pct(df: pd.DataFrame) -> tuple[float, int]:
    """Hitters' swings (whiffs + fouls + in play) on Chase/Waste pitches in
    2-strike counts -- the same Chase% definition as every other page."""
    sub = _two_k(df)
    sub = sub[_zones(sub).isin(CHASE_ZONES)]
    swings = int(_swings(sub).sum())
    return P._pct(swings, len(sub)), swings


# (key, label, transform, higher_is_better); None = no better direction, so
# never tinted or given a leader.
METRICS: tuple[tuple, ...] = (
    ("strike_pct", "Strike%", P.strike_pct, True),
    ("fps_pct", "FPS%", P.fps_pct, True),
    ("pre2k_pct", "Pre2K%", P.pre2k_pct, True),
    ("ea_pct", "E&A%", P.ea_pct, True),
    ("k_pct", "K%", P.k_pct, True),
    ("barrel_pct", "Barrel%", P.barrel_pct, False),
    ("bb_pct", "BB%", P.bb_pct, False),
    ("twok_kill_pct", "2K Kill%", P.twok_kill_pct, True),
    ("contact_2k_pct", "Contact 2K%", contact_2k_pct, False),
    ("swstr_2k_pct", "SwStr 2K%", swstr_2k_pct, True),
    ("zone_swing_pct", "Zone Swing%", zone_swing_pct, None),
    ("chase_2k_pct", "Chase 2K%", chase_2k_pct, True),
)
VELO_COLS: tuple[tuple, ...] = (("velo_avg", "Velo Avg"), ("velo_max", "Velo Max"))

# The coaches' standing targets, copied from the Team Process sheet. No velo
# target was ever set on the sheet, so velo stays blank on this row; the
# 2-strike and zone-swing columns (added 2026-10-28) have no target yet either.
BASELINE: dict[str, float] = {
    "strike_pct": 55.0, "fps_pct": 60.0, "pre2k_pct": 50.0, "ea_pct": 70.0,
    "k_pct": 25.0, "barrel_pct": 10.0, "bb_pct": 10.0, "twok_kill_pct": 75.0,
}

CYCLES = velo_board.VELO_CYCLES


def cycle_bounds(season_label: str, cycle: str) -> tuple[str, str]:
    return velo_board.velo_cycle_bounds(season_label, cycle)


def cycle_display(season_label: str, cycle: str) -> str:
    """'Fall 2025' / 'Spring 2026' -- the calendar year the cycle falls in."""
    a, b = season_label.split("/")
    return f"{cycle} {a if cycle == 'Fall' else b}"


@cached
def _pitches(start: str, end: str) -> pd.DataFrame:
    return query_df(
        f"SELECT {_PITCH_SELECT}, Pitcher AS pitcher_name, "
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


def _velo(df: pd.DataFrame) -> tuple[float | None, float | None]:
    fb = df[P.pitch_type(df).isin(velo_board.VELO_PITCH_TYPES)]
    fb = velo_board._clip_velo_outliers(fb)
    v = fb["rel_speed"].dropna() if fb is not None and not fb.empty else pd.Series(dtype=float)
    if v.empty:
        return None, None
    return round(float(v.mean()), 1), round(float(v.max()), 1)


def metric_line(df: pd.DataFrame) -> dict:
    """Every board metric for one pitch frame (a pitcher, or the whole team
    pooled). Percent metrics with no denominator come back None, not 0."""
    # Intrasquads put LMU pitchers in BOTH halves of an inning, and the PA
    # key (game_id, inning, pa_of_inning) has no half -- fold the half into
    # game_id so top and bottom PAs stay separate in the pooled team line.
    if "top_bottom" in df.columns and len(df):
        df = df.assign(game_id=df["game_id"].astype(str) + "|" + df["top_bottom"].astype(str))
    out: dict = {"pitches": int(len(df))}
    denominators = {
        "fps_pct": lambda d: int((d["pitch_of_pa"] == 1).sum()),
        "pre2k_pct": lambda d: int((d["strikes"] < 2).sum()),
        "barrel_pct": lambda d: int((d["pitch_call"] == "InPlay").sum()),
        "twok_kill_pct": lambda d: int((d["strikes"] >= 2).sum()),
        "contact_2k_pct": lambda d: int(_swings(_two_k(d)).sum()),
        "swstr_2k_pct": lambda d: len(_two_k(d)),
        "zone_swing_pct": lambda d: int(_zones(d).isin(_ZONE_AREAS).sum()),
        "chase_2k_pct": lambda d: int(_zones(_two_k(d)).isin(CHASE_ZONES).sum()),
    }
    for key, _label, fn, _hib in METRICS:
        has_denominator = len(df) > 0 and denominators.get(key, len)(df) > 0
        out[key] = fn(df)[0] if has_denominator else None
    out["velo_avg"], out["velo_max"] = _velo(df) if len(df) else (None, None)
    return out


def _with_hand(name: str, throws: pd.Series) -> str:
    hand = throws.dropna()
    hand = hand.mode().iloc[0] if not hand.empty else ""
    return f"{name} ({hand[0]})" if hand in ("Right", "Left") else name


def pitcher_rows(df: pd.DataFrame) -> list[dict]:
    """One metric line per pitcher (by GAMES.Pitcher name, so a pitcher with
    split Trackman ids stays one row), alphabetical like the sheet."""
    if df.empty:
        return []
    rows = []
    for name, g in df.groupby("pitcher_name", sort=True):
        row = metric_line(g)
        row["pitcher"] = _with_hand(str(name), g["pitcher_throws"])
        rows.append(row)
    return rows


def best_values(rows: list[dict]) -> dict[str, float]:
    """The column leader per metric (max, or min where lower is better, e.g.
    BB%/Barrel%) -- ties all count as the leader."""
    best = {}
    direction = {k: hib for k, _l, _f, hib in METRICS if hib is not None}
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


def board(season_label: str, cycle: str, game_types=None) -> dict:
    """Everything the page renders: the three reference rows + pitcher rows.
    Selecting every game type is the same board as no filter, so both share
    one cache entry (the one warmup.py pre-builds)."""
    start, end = cycle_bounds(season_label, cycle)
    types = sorted(game_types) if game_types else []
    if not types or set(types) >= set(_game_types_for(start, end)):
        types = []
    return _board(season_label, cycle, tuple(types))


@cached
def _board(season_label: str, cycle: str, game_types: tuple) -> dict:
    game_types = list(game_types) or None
    start, end = cycle_bounds(season_label, cycle)
    df = window_pitches(start, end, game_types)
    # The cycle row is the whole selected cycle (every game type), so it
    # stays put while the Team Average follows the Game Type filter.
    cycle_df = window_pitches(start, end) if game_types else df

    baseline = dict(BASELINE, pitcher="LMU Baseline", kind="baseline")
    cycle_row = dict(metric_line(cycle_df) if not cycle_df.empty else {},
                     pitcher=f"LMU {cycle_display(season_label, cycle)} Average",
                     kind="cycle")
    team = dict(metric_line(df) if not df.empty else {},
                pitcher="LMU Team Average", kind="team")
    pitchers = pitcher_rows(df)
    return {"summary": [baseline, cycle_row, team], "pitchers": pitchers,
            "best": best_values(pitchers)}
