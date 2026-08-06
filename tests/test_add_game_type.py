from sqlalchemy import create_engine, text

from app.ingest.add_game_type import _ensure_column, backfill_game_type


def test_ensure_column_is_idempotent():
    eng = create_engine("sqlite://")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE GAMES (GameID INTEGER)"))
    _ensure_column(eng)   # adds GameType
    _ensure_column(eng)   # no-op second time (must not raise)
    with eng.connect() as c:
        cols = [r[1] for r in c.execute(text("PRAGMA table_info(GAMES)")).fetchall()]
    assert "GameType" in cols


def test_dry_run_does_not_add_column_when_absent():
    eng = create_engine("sqlite://")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE GAMES (GameID INTEGER)"))
        c.execute(text("CREATE TABLE dim_tm_game (game_id INTEGER, game_type TEXT)"))
        c.execute(text("INSERT INTO GAMES (GameID) VALUES (1), (2)"))
        c.execute(text(
            "INSERT INTO dim_tm_game (game_id, game_type) VALUES (1, 'Conference'), (2, 'Scrimmage')"
        ))

    result = backfill_game_type(eng, dry_run=True)

    assert result == {"would_update": 2}
    with eng.connect() as c:
        cols = [r[1] for r in c.execute(text("PRAGMA table_info(GAMES)")).fetchall()]
    assert "GameType" not in cols
