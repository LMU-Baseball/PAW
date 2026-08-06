"""One-time: add GAMES.GameType and backfill from dim_tm_game.game_type."""
from __future__ import annotations
from sqlalchemy import text, inspect


def _has_game_type_column(engine) -> bool:
    insp = inspect(engine)
    cols = [c["name"] for c in insp.get_columns("GAMES")]
    return "GameType" in cols


def _ensure_column(engine):
    if not _has_game_type_column(engine):
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE GAMES ADD COLUMN GameType VARCHAR(64)"))


def backfill_game_type(engine, *, dry_run: bool = True) -> dict:
    """Ensure GAMES.GameType exists and backfill it from dim_tm_game.game_type.

    dry_run=True (default) is strictly read-only: it does NOT alter the schema,
    even to add the column. It only reports how many rows would be updated.
    """
    if dry_run:
        if _has_game_type_column(engine):
            count_sql = text(
                "SELECT COUNT(*) FROM GAMES g JOIN dim_tm_game d ON d.game_id = g.GameID "
                "WHERE (g.GameType IS NULL OR g.GameType <> d.game_type)"
            )
        else:
            # Column doesn't exist yet: every joined row would be backfilled.
            count_sql = text(
                "SELECT COUNT(*) FROM GAMES g JOIN dim_tm_game d ON d.game_id = g.GameID"
            )
        with engine.connect() as conn:
            would = conn.execute(count_sql).scalar()
        return {"would_update": int(would)}

    _ensure_column(engine)
    count_sql = text(
        "SELECT COUNT(*) FROM GAMES g JOIN dim_tm_game d ON d.game_id = g.GameID "
        "WHERE (g.GameType IS NULL OR g.GameType <> d.game_type)"
    )
    with engine.connect() as conn:
        would = conn.execute(count_sql).scalar()
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE GAMES g JOIN dim_tm_game d ON d.game_id = g.GameID "
            "SET g.GameType = d.game_type"
        ))
    return {"would_update": int(would)}
