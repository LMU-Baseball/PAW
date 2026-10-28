"""All Things Process, hitter edition: per-batter Trackman process leaderboard
over GAMES (games, scrimmages, intrasquads -- never HitTrax or bullpens).

Mirrors `app.data.process_board` for pitchers. There is no fixed coach
baseline here: the LMU Team Average (pooled over every pitch LMU hitters saw
under the selected game types) IS the baseline each hitter is colored against.
"""
from __future__ import annotations

import pandas as pd

from app.data import process_board as PB
from app.data.pitching import is_barrel
from app.data.cache import cached
from app.data.hitting import CHASE_ZONES, attack_zone
from app.data.hitting_caps import LMU_BATTER_TEAM
from app.db import query_df

# (key, label, higher_is_better). Lower is better for whiffs, chase and GB%.
METRICS: tuple[tuple, ...] = (
    ("swing_pct", "Swing%", True),
    ("contact_pct", "Contact%", True),
    ("barrel_pct", "Barrel%", True),
    ("max_ev", "Max EV", True),
    ("avg_ev", "Avg EV", True),
    ("gb_pct", "GB%", False),
    ("fb_pct", "FB%", True),
    ("ld_pct", "LD%", True),
    ("chase_pct", "Chase%", False),
    ("whiff_pct", "Whiff%", False),
    ("iz_whiff_pct", "IZ Whiff%", False),
)
EV_KEYS = ("max_ev", "avg_ev")

# Trackman logs fouls as FoulBallNotFieldable/FoulBallFieldable, so
# hitting.SWING_CALLS ("FoulBall") would silently drop them from swings.
_FOUL_CALLS = ["FoulBall", "FoulBallNotFieldable", "FoulBallFieldable"]

# Rulebook zone in feet (same box the bullpen/practice/game-log code uses).
_SZ_X, _SZ_Y0, _SZ_Y1 = 0.83, 1.5, 3.5
# A hitter needs this many pitches seen to be eligible for a gold leader cell.
MIN_PITCHES_FOR_LEADER = 20

CYCLES = PB.CYCLES
cycle_bounds = PB.cycle_bounds
cycle_display = PB.cycle_display


def clean_names(names: pd.Series) -> pd.Series:
    """Trim and collapse whitespace. Trackman loaded 'Marucci, Luca' and
    'Marucci, Luca ' (same BatterId) and the board, which groups by name,
    showed him as two hitters."""
    return names.str.split().str.join(" ").replace("", pd.NA)


@cached
def _pitches(start: str, end: str) -> pd.DataFrame:
    df = _query_pitches(start, end)
    if not df.empty:
        df["batter_name"] = clean_names(df["batter_name"])
    return df


def _query_pitches(start: str, end: str) -> pd.DataFrame:
    return query_df(
        "SELECT Batter AS batter_name, BatterSide AS batter_side, "
        "PlateLocSide AS plate_side, PlateLocHeight AS plate_height, "
        "PitchCall AS pitch_call, ExitSpeed AS exit_speed, Angle AS launch_angle, "
        "TaggedHitType AS hit_type, "
        "COALESCE(GameType, 'Untyped') AS game_type "
        "FROM GAMES WHERE BatterTeam = :t AND Date BETWEEN :s AND :e",
        {"t": LMU_BATTER_TEAM, "s": str(start), "e": str(end)},
    )


def window_pitches(start: str, end: str, game_types=None) -> pd.DataFrame:
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


def _rate(numer: int, denom: int) -> float | None:
    return round(100.0 * numer / denom, 1) if denom else None


def metric_line(df: pd.DataFrame) -> dict:
    """Every board metric for one pitch frame (a hitter, or the whole team
    pooled). A rate with no denominator comes back None, not 0."""
    out: dict = {"pitches": int(len(df))}
    whiffs = df["pitch_call"] == "StrikeSwinging"
    contact = df["pitch_call"].isin(_FOUL_CALLS + ["InPlay"])
    swings = whiffs | contact

    located = df["plate_side"].notna() & df["plate_height"].notna()
    in_zone = located & df["plate_side"].between(-_SZ_X, _SZ_X) \
        & df["plate_height"].between(_SZ_Y0, _SZ_Y1)
    chase_zone = pd.Series([attack_zone(s, h) in CHASE_ZONES
                           for s, h in zip(df["plate_side"], df["plate_height"])],
                          index=df.index, dtype=bool)

    bip = df[df["pitch_call"] == "InPlay"]
    ev = bip["exit_speed"].dropna()
    typed = bip["hit_type"].dropna()

    out["swing_pct"] = _rate(int(swings.sum()), len(df))
    out["contact_pct"] = _rate(int((swings & contact).sum()), int(swings.sum()))
    out["whiff_pct"] = _rate(int(whiffs.sum()), int(swings.sum()))
    out["iz_whiff_pct"] = _rate(int((in_zone & whiffs).sum()), int((in_zone & swings).sum()))
    out["chase_pct"] = _rate(int((chase_zone & swings).sum()), int(chase_zone.sum()))
    out["barrel_pct"] = _rate(int(is_barrel(bip["exit_speed"], bip["launch_angle"]).sum()), len(bip))
    out["max_ev"] = round(float(ev.max()), 1) if len(ev) else None
    out["avg_ev"] = round(float(ev.mean()), 1) if len(ev) else None
    out["gb_pct"] = _rate(int((typed == "GroundBall").sum()), len(typed))
    out["ld_pct"] = _rate(int((typed == "LineDrive").sum()), len(typed))
    # Popups are folded into fly balls.
    out["fb_pct"] = _rate(int(typed.isin(["FlyBall", "Popup"]).sum()), len(typed))
    return out


def _with_side(name: str, sides: pd.Series) -> str:
    seen = set(sides.dropna()) & {"Right", "Left"}
    if seen == {"Right", "Left"}:
        return f"{name} (S)"
    return f"{name} ({next(iter(seen))[0]})" if seen else name


def hitter_rows(df: pd.DataFrame) -> list[dict]:
    """One metric line per hitter (by GAMES.Batter name, so split Trackman ids
    stay one row), alphabetical like the pitcher board."""
    if df.empty:
        return []
    rows = []
    for name, g in df.groupby("batter_name", sort=True):
        row = metric_line(g)
        row["hitter"] = _with_side(str(name), g["batter_side"])
        rows.append(row)
    return rows


def best_values(rows: list[dict]) -> dict[str, float]:
    """Column leader per metric (max, or min where lower is better); ties all
    count. Hitters under MIN_PITCHES_FOR_LEADER can't be the leader."""
    eligible = [r for r in rows if r["pitches"] >= MIN_PITCHES_FOR_LEADER]
    best = {}
    for key, _label, hib in METRICS:
        vals = [r[key] for r in eligible if r.get(key) is not None]
        if vals:
            best[key] = max(vals) if hib else min(vals)
    return best


def board(season_label: str, cycle: str, game_types=None) -> dict:
    """Everything the page renders: cycle + team-average rows and hitter rows.
    Selecting every game type is the same board as no filter (one cache entry)."""
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
    cycle_df = window_pitches(start, end) if game_types else df

    cycle_row = dict(metric_line(cycle_df) if not cycle_df.empty else {},
                     hitter=f"LMU {cycle_display(season_label, cycle)} Average", kind="cycle")
    team = dict(metric_line(df) if not df.empty else {},
                hitter="LMU Team Average", kind="team")
    hitters = hitter_rows(df)
    return {"summary": [cycle_row, team], "hitters": hitters,
            "best": best_values(hitters),
            "baseline": {k: team.get(k) for k, _l, _h in METRICS}}
