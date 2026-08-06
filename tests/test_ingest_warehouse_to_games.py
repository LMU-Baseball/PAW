"""Tests for the one-time warehouse (fact_tm_game_pitch) -> GAMES transform."""
from datetime import date

import pandas as pd
import pytest

from app.ingest import warehouse_to_games as w2g
from app.ingest.warehouse_to_games import transform_fact_to_games, load_backfill
from app.ingest.games import GAMES_COLS


def _row(**over):
    """A minimal fact+join row; override fields per test."""
    base = {"pitch_uid": "uid-x", "game_date": date(2025, 11, 22)}
    base.update(over)
    return pd.DataFrame([base])


def test_transform_uses_raw_tm_ids_not_surrogates():
    # The app matches current_user.trackman_id to GAMES.BatterId, so the RAW
    # *_tm_id must win over the surrogate *_id — else player self-scoping breaks.
    out = transform_fact_to_games(_row(
        batter_tm_id=806253, batter_id=5,
        pitcher_tm_id=999001, pitcher_id=12,
        catcher_tm_id=700700, catcher_id=3,
    ))
    assert out.iloc[0]["BatterId"] == 806253
    assert out.iloc[0]["PitcherId"] == 999001
    assert out.iloc[0]["CatcherId"] == 700700
    assert "batter_id" not in out.columns
    assert "pitcher_id" not in out.columns


def test_transform_maps_launch_angle_la_to_Angle():
    out = transform_fact_to_games(_row(la=27.5))
    assert out.iloc[0]["Angle"] == 27.5
    assert "la" not in out.columns


def test_transform_maps_names_to_short_game_columns():
    out = transform_fact_to_games(_row(pitcher_name="Smith, Joe", batter_name="Doe, Jim"))
    assert out.iloc[0]["Pitcher"] == "Smith, Joe"
    assert out.iloc[0]["Batter"] == "Doe, Jim"


def test_transform_writes_iso_date_from_game_date():
    out = transform_fact_to_games(_row(game_date=pd.Timestamp("2025-11-22")))
    assert out.iloc[0]["Date"] == "2025-11-22"


def test_transform_maps_top_bottom_with_dotted_name():
    out = transform_fact_to_games(_row(top_bottom="Top"))
    assert out.iloc[0]["Top.Bottom"] == "Top"


def test_transform_preserves_pitch_uid_for_dedup():
    out = transform_fact_to_games(_row(pitch_uid="uid-123"))
    assert out.iloc[0]["PitchUID"] == "uid-123"


def test_transform_drops_warehouse_internal_columns():
    out = transform_fact_to_games(_row(
        ml_pitch_type="Fastball", og_pitch_type="x", pitch_id=9,
        ingest_file_id=2, izt_zone="5", zi=None, created_at="2026-01-01",
    ))
    for c in ("ml_pitch_type", "og_pitch_type", "pitch_id", "ingest_file_id",
              "izt_zone", "zi", "created_at"):
        assert c not in out.columns


def test_transform_maps_game_level_ids_and_teams():
    out = transform_fact_to_games(_row(
        game_id=1, tm_game_id="2025-11-22_LOY_LIO_vs_SAN_GAU",
        home_team_id=78, away_team_id=126,
        home_team_name="Loyola Marymount", away_team_name="Santa Clara",
    ))
    r = out.iloc[0]
    assert r["GameID"] == 1
    assert r["GameUID"] == "2025-11-22_LOY_LIO_vs_SAN_GAU"
    assert r["HomeTeamForeignID"] == 78
    assert r["AwayTeamForeignID"] == 126
    assert r["HomeTeam"] == "Loyola Marymount"
    assert r["AwayTeam"] == "Santa Clara"


def test_transform_output_contains_only_valid_games_columns():
    out = transform_fact_to_games(_row(batter_tm_id=1, rel_speed=90.0))
    assert set(out.columns) <= set(GAMES_COLS)


# ---- load_backfill: monkeypatch the DB read + insert seams -----------------

def _fact_df(uids):
    """A fact ⋈ dim ⋈ tm_team-shaped frame with one row per PitchUID."""
    return pd.DataFrame([{
        "pitch_uid": u, "batter_tm_id": 806253, "pitcher_tm_id": 1, "catcher_tm_id": 2,
        "game_id": 10, "pitch_no": i + 1, "game_date": date(2025, 11, 22),
        "tm_game_id": "2025-11-22_LOY_LIO_vs_X", "home_team_id": 78, "away_team_id": 126,
        "home_team_name": "Loyola Marymount", "away_team_name": "Opp",
    } for i, u in enumerate(uids)])


def _patch(monkeypatch, fact_df, existing=frozenset()):
    monkeypatch.setattr(w2g, "_read_fact", lambda engine, since: fact_df.copy())
    monkeypatch.setattr(w2g, "existing_keys", lambda engine, table, col: set(existing))


def test_load_backfill_dry_run_does_not_insert(monkeypatch):
    _patch(monkeypatch, _fact_df(["a", "b"]))
    monkeypatch.setattr(w2g, "chunked_insert",
                        lambda *a, **k: pytest.fail("must not insert on dry_run"))
    r = load_backfill(engine=object(), dry_run=True)
    assert r.inserted == 2
    assert r.skipped == 0
    assert r.dry_run is True


def test_load_backfill_skips_pitchuids_already_in_games(monkeypatch):
    _patch(monkeypatch, _fact_df(["a", "b", "c"]), existing={"a", "c"})
    monkeypatch.setattr(w2g, "chunked_insert",
                        lambda *a, **k: pytest.fail("must not insert on dry_run"))
    r = load_backfill(engine=object(), dry_run=True)
    assert r.inserted == 1
    assert r.skipped == 2


def test_load_backfill_inserts_games_shaped_rows_when_not_dry_run(monkeypatch):
    _patch(monkeypatch, _fact_df(["a", "b"]))
    captured = {}

    def fake_insert(engine, table, rows, chunksize=500):
        captured["table"] = table
        captured["rows"] = rows

    monkeypatch.setattr(w2g, "chunked_insert", fake_insert)
    r = load_backfill(engine=object(), dry_run=False)
    assert r.inserted == 2
    assert r.dry_run is False
    assert captured["table"] == "GAMES"
    assert len(captured["rows"]) == 2
    # rows are GAMES-shaped, keyed off the RAW trackman id
    assert captured["rows"][0]["BatterId"] == 806253
    assert "batter_tm_id" not in captured["rows"][0]


def test_load_backfill_reports_game_count_and_iso_date_span(monkeypatch):
    df = _fact_df(["a", "b"])
    df.loc[1, "game_id"] = 11
    df.loc[1, "game_date"] = date(2026, 5, 16)
    _patch(monkeypatch, df)
    monkeypatch.setattr(w2g, "chunked_insert", lambda *a, **k: None)
    r = load_backfill(engine=object(), dry_run=False)
    assert r.files == 2
    assert r.date_min == "2025-11-22"
    assert r.date_max == "2026-05-16"
