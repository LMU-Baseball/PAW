"""One-time: backfill GAMES.Zone from fact_tm_game_pitch.izt_zone.

GAMES.Zone already exists as a column but is NULL for CAPS-migration-backfilled
rows; fact_tm_game_pitch.izt_zone is fully populated. Backfilling preserves
in-zone% (zone_location) for pitching and the video Zone column.
"""
from __future__ import annotations
from sqlalchemy import text

_MISMATCH_EXISTS = (
    "EXISTS (SELECT 1 FROM fact_tm_game_pitch f WHERE f.pitch_uid = g.PitchUID "
    "AND (g.Zone IS NULL OR g.Zone <> f.izt_zone))"
)

# Correlated-subquery form (rather than a MySQL-style multi-table UPDATE...JOIN)
# so the same SQL runs against both MySQL (prod) and SQLite (tests).
_COUNT_SQL = text(f"SELECT COUNT(*) FROM GAMES g WHERE {_MISMATCH_EXISTS}")

_UPDATE_SQL = text(
    "UPDATE GAMES AS g SET Zone = "
    "(SELECT f.izt_zone FROM fact_tm_game_pitch f WHERE f.pitch_uid = g.PitchUID) "
    f"WHERE {_MISMATCH_EXISTS}"
)


def backfill_zone(engine, *, dry_run: bool = True) -> dict:
    """Backfill GAMES.Zone from fact_tm_game_pitch.izt_zone, joined on PitchUID.

    dry_run=True (default) is strictly read-only: it only reports how many
    rows would be updated. dry_run=False performs the UPDATE.
    """
    with engine.connect() as conn:
        would = conn.execute(_COUNT_SQL).scalar()

    if dry_run:
        return {"would_update": int(would)}

    with engine.begin() as conn:
        conn.execute(_UPDATE_SQL)
    return {"would_update": int(would)}
