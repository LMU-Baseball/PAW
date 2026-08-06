"""One-time backfill: transform warehouse rows -> GAMES-shaped rows.

Populates the ALL-CAPS ``GAMES`` table with the LMU games that currently live
only in the ``tm_*`` warehouse (the 2025-11-22 -> 2026-05-16 gap; GAMES has 0
rows in that span). ``fact_tm_game_pitch`` is already the clean, LMU-filtered
142-game set, so this reads the warehouse (fact ⋈ dim_tm_game ⋈ tm_team),
renames columns to GAMES names, and inserts new rows (insert-only, dedup on
``PitchUID``; skipped entirely on ``dry_run``).

``FACT_TO_GAMES`` is explicit (not a heuristic) because one mapping is safety-
critical: GAMES.BatterId/PitcherId/CatcherId must come from fact's RAW
``*_tm_id`` columns (== a player's ``trackman_id``), NOT the surrogate
``*_id`` columns — the app matches ``current_user.trackman_id`` to
GAMES.BatterId for player self-scoping. Warehouse-internal columns (ml_*,
surrogate ids, bookkeeping) are dropped by omission.
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy import text

from app.ingest.common import LoadResult, chunked_insert, existing_keys
from app.ingest.games import GAMES_COLS, dedup_key

# fact_tm_game_pitch column (+ joined dim/tm_team aliases) -> GAMES column.
# Columns absent from this map are dropped (surrogate ids, ml_*, bookkeeping).
# ``game_date`` is handled separately (formatted to an ISO ``Date`` string).
FACT_TO_GAMES: dict[str, str] = {
    # identity / ids  (RAW *_tm_id -> *Id; surrogate *_id intentionally absent)
    "pitch_uid": "PitchUID",
    "pitcher_tm_id": "PitcherId",
    "batter_tm_id": "BatterId",
    "catcher_tm_id": "CatcherId",
    "game_id": "GameID",
    "tm_game_id": "GameUID",
    # names (fact uses long names; GAMES uses short ones)
    "pitcher_name": "Pitcher",
    "batter_name": "Batter",
    "catcher": "Catcher",
    # handedness / side / team
    "pitcher_throws": "PitcherThrows",
    "batter_side": "BatterSide",
    "catcher_throws": "CatcherThrows",
    "pitcher_team": "PitcherTeam",
    "batter_team": "BatterTeam",
    "catcher_team": "CatcherTeam",
    # game situation
    "inning": "Inning",
    "top_bottom": "Top.Bottom",
    "balls": "Balls",
    "strikes": "Strikes",
    "outs": "Outs",
    "pa_of_inning": "PAofInning",
    "pitch_of_pa": "PitchofPA",
    "pitch_no": "PitchNo",
    # pitch classification
    "tagged_pitch_type": "TaggedPitchType",
    "auto_pitch_type": "AutoPitchType",
    # pitch physics
    "rel_speed": "RelSpeed",
    "vert_rel_angle": "VertRelAngle",
    "horz_rel_angle": "HorzRelAngle",
    "spin_rate": "SpinRate",
    "spin_axis": "SpinAxis",
    "tilt": "Tilt",
    "rel_height": "RelHeight",
    "rel_side": "RelSide",
    "extension": "Extension",
    "induced_vert_break": "InducedVertBreak",
    "horz_break": "HorzBreak",
    "plate_loc_height": "PlateLocHeight",
    "plate_loc_side": "PlateLocSide",
    "zone_speed": "ZoneSpeed",
    "vert_appr_angle": "VertApprAngle",
    "horz_appr_angle": "HorzApprAngle",
    "zone_time": "ZoneTime",
    # outcome
    "pitch_call": "PitchCall",
    "play_result": "PlayResult",
    "korbb": "KorBB",
    "outs_on_play": "OutsOnPlay",
    "runs_scored": "RunsScored",
    # batted ball  (la == launch angle -> GAMES 'Angle')
    "tagged_hit_type": "TaggedHitType",
    "exit_speed": "ExitSpeed",
    "la": "Angle",
    "hit_spin_axis": "HitSpinAxis",
    "hit_spin_rate": "HitSpinRate",
    "direction": "Direction",
    "distance": "Distance",
    "bearing": "Bearing",
    "hang_time": "HangTime",
    "max_height": "MaxHeight",
    "contact_pos_x": "ContactPositionX",
    "contact_pos_y": "ContactPositionY",
    "contact_pos_z": "ContactPositionZ",
    # catcher throws
    "throw_speed": "ThrowSpeed",
    "pop_time": "PopTime",
    "exchange_time": "ExchangeTime",
    "time_to_base": "TimeToBase",
    "catch_position_x": "CatchPositionX",
    "catch_position_y": "CatchPositionY",
    "catch_position_z": "CatchPositionZ",
    "throw_position_x": "ThrowPositionX",
    "throw_position_y": "ThrowPositionY",
    "throw_position_z": "ThrowPositionZ",
    "base_position_x": "BasePositionX",
    "base_position_y": "BasePositionY",
    "base_position_z": "BasePositionZ",
    # game-level, from the dim_tm_game / tm_team join
    "home_team_id": "HomeTeamForeignID",
    "away_team_id": "AwayTeamForeignID",
    "home_team_name": "HomeTeam",
    "away_team_name": "AwayTeam",
}


def transform_fact_to_games(df: pd.DataFrame) -> pd.DataFrame:
    """Rename a warehouse fact(+join) frame to GAMES columns and select the
    columns present in ``GAMES_COLS``.

    ``game_date`` becomes an ISO ``YYYY-MM-DD`` ``Date`` string (fixing the
    mixed-format issue for the new rows). Columns not in ``FACT_TO_GAMES`` are
    dropped. Returns a copy; filters no rows.
    """
    renamed = df.rename(columns=FACT_TO_GAMES)
    if "game_date" in df.columns:
        renamed["Date"] = pd.to_datetime(df["game_date"]).dt.strftime("%Y-%m-%d")
    cols = [c for c in GAMES_COLS if c in renamed.columns]
    return renamed[cols].copy()


_FACT_QUERY = """
    SELECT f.*, g.game_date, g.tm_game_id, g.home_team_id, g.away_team_id,
           ht.team_name AS home_team_name, awt.team_name AS away_team_name
      FROM fact_tm_game_pitch f
      JOIN dim_tm_game g ON g.game_id = f.game_id
      LEFT JOIN tm_team ht ON ht.team_id = g.home_team_id
      LEFT JOIN tm_team awt ON awt.team_id = g.away_team_id
     {where}
     ORDER BY f.game_id, f.pitch_no
"""


def _read_fact(engine, since: str | None) -> pd.DataFrame:
    """Read the warehouse fact ⋈ dim ⋈ tm_team frame (a seam tests monkeypatch
    so no live DB is touched). ``since`` optionally bounds to game_date >= since."""
    where = "WHERE g.game_date >= :since" if since else ""
    params = {"since": since} if since else {}
    # text() so the :since named param binds (a raw string would send ':since'
    # literally to MySQL -> syntax error).
    return pd.read_sql(text(_FACT_QUERY.format(where=where)), engine, params=params)


def load_backfill(engine, *, dry_run: bool = True, since: str | None = None) -> LoadResult:
    """Read the warehouse, transform to GAMES shape, dedup against
    GAMES.PitchUID, and insert the new rows (skipped on ``dry_run``).

    Insert-only: never DELETEs/DROPs. Idempotent — re-running skips rows whose
    PitchUID is already in GAMES. ``since`` optionally bounds to game_date.
    """
    games = transform_fact_to_games(_read_fact(engine, since))

    already = existing_keys(engine, "GAMES", "PitchUID")
    seen: set[str] = set()
    rows_to_insert: list[dict] = []
    skipped = 0
    for row in games.to_dict(orient="records"):
        key = dedup_key(row)
        if key in already or key in seen:
            skipped += 1
            continue
        seen.add(key)
        rows_to_insert.append(row)

    inserted = len(rows_to_insert)
    if not dry_run and rows_to_insert:
        chunked_insert(engine, "GAMES", rows_to_insert)

    dates = [r.get("Date") for r in rows_to_insert if r.get("Date") not in (None, "")]
    n_games = games["GameID"].nunique() if "GameID" in games.columns and not games.empty else 0
    return LoadResult(
        inserted=inserted,
        skipped=skipped,
        files=int(n_games),
        date_min=min(dates) if dates else None,
        date_max=max(dates) if dates else None,
        dry_run=dry_run,
    )


