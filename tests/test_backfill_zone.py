from sqlalchemy import create_engine, text

from app.ingest.backfill_zone import backfill_zone


def _make_engine():
    eng = create_engine("sqlite://")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE GAMES (GameID INTEGER, PitchUID TEXT, Zone TEXT)"))
        c.execute(text("CREATE TABLE fact_tm_game_pitch (pitch_uid TEXT, izt_zone TEXT)"))
        c.execute(text(
            "INSERT INTO GAMES (GameID, PitchUID, Zone) VALUES (1, 'abc-123', NULL)"
        ))
        c.execute(text(
            "INSERT INTO fact_tm_game_pitch (pitch_uid, izt_zone) VALUES ('abc-123', '5')"
        ))
    return eng


def test_dry_run_counts_but_does_not_write():
    eng = _make_engine()

    result = backfill_zone(eng, dry_run=True)

    assert result == {"would_update": 1}
    with eng.connect() as c:
        zone = c.execute(text("SELECT Zone FROM GAMES WHERE GameID = 1")).scalar()
    assert zone is None


def test_real_run_sets_zone_from_fact():
    eng = _make_engine()

    result = backfill_zone(eng, dry_run=False)

    assert result == {"would_update": 1}
    with eng.connect() as c:
        zone = c.execute(text("SELECT Zone FROM GAMES WHERE GameID = 1")).scalar()
    assert zone == "5"


def test_real_run_is_idempotent():
    eng = _make_engine()

    backfill_zone(eng, dry_run=False)
    result = backfill_zone(eng, dry_run=False)

    assert result == {"would_update": 0}
    with eng.connect() as c:
        zone = c.execute(text("SELECT Zone FROM GAMES WHERE GameID = 1")).scalar()
    assert zone == "5"
