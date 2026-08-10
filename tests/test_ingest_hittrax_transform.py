"""Tests for app.ingest.hittrax's TRANSFORM step: transform_sessions /
transform_plays. PURE only -- no network, no DB. Builds an in-memory
raw-table-shaped DataFrame (`source_file`, `payload`=json per CSV row) from
the two fixture CSVs, exactly as the real `RAW_PRACTICE_CSV` table would
hold them, and feeds that straight into the pure transforms.

One additional test (`test_transform_uses_delete_not_truncate_for_rebuild`)
exercises `transform()`'s DB-write path against a FAKE engine/connection
(no real DB) solely to assert it issues transactional `DELETE FROM`
statements, never DDL `TRUNCATE TABLE` -- MySQL `TRUNCATE` causes an
implicit commit and is not rollback-able, which would break the "atomic
rebuild" guarantee `transform()` exists to provide.
"""
import json
from pathlib import Path

import pandas as pd
import pytest

from app.ingest.hittrax import (
    PLAYS_FIELD_MAP,
    SESSION_FIELD_MAP,
    transform,
    transform_plays,
    transform_sessions,
)

SESSION_FIXTURE = Path(__file__).parent / "fixtures" / "ingest" / "hittrax_session_sample.csv"
PLAYS_FIXTURE = Path(__file__).parent / "fixtures" / "ingest" / "hittrax_plays_sample.csv"


def _raw_df(fixture: Path, *, source_file: str) -> pd.DataFrame:
    """Build a RAW_PRACTICE_CSV-shaped DataFrame (source_file, payload) from
    a fixture CSV, one row per CSV row -- mirrors how `csv_to_raw_rows`
    stores each row as a JSON payload string.
    """
    df = pd.read_csv(fixture, encoding="utf-8-sig")
    records = df.to_dict(orient="records")
    payloads = []
    for record in records:
        cleaned = {k: (None if v != v else v) for k, v in record.items()}  # NaN -> None
        payloads.append(json.dumps(cleaned, default=str))
    return pd.DataFrame({
        "source_file": [source_file] * len(payloads),
        "payload": payloads,
    })


@pytest.fixture
def sessions_raw_df():
    return _raw_df(SESSION_FIXTURE, source_file="SessionExport_sample.CSV")


@pytest.fixture
def plays_raw_df():
    return _raw_df(PLAYS_FIXTURE, source_file="PlaysExport_sample.CSV")


# ---------------------------------------------------------------------------
# transform_sessions
# ---------------------------------------------------------------------------

def test_transform_sessions_returns_one_row_per_raw_row(sessions_raw_df):
    out = transform_sessions(sessions_raw_df)
    assert len(out) == 30


def test_transform_sessions_field_map_has_aev_and_type():
    assert SESSION_FIELD_MAP["avg_exit_velocity"] == ("AEV", "mph")
    assert SESSION_FIELD_MAP["session_type"] == ("Type", "int")


def test_transform_sessions_avg_exit_velocity_mps_to_mph_conversion(sessions_raw_df):
    raw = pd.read_csv(SESSION_FIXTURE, encoding="utf-8-sig")
    out = transform_sessions(sessions_raw_df)

    # Spot-check every row that has a numeric AEV: converted value must
    # equal round(raw_AEV * 2.23694, 2) exactly.
    checked_any = False
    for i in range(len(raw)):
        raw_aev = raw.loc[i, "AEV"]
        if pd.isna(raw_aev):
            continue
        expected = round(float(raw_aev) * 2.23694, 2)
        assert out.loc[i, "avg_exit_velocity"] == expected
        checked_any = True
    assert checked_any, "fixture must have at least one numeric AEV row to spot-check"


def test_transform_sessions_maps_type_to_session_type(sessions_raw_df):
    raw = pd.read_csv(SESSION_FIXTURE, encoding="utf-8-sig")
    out = transform_sessions(sessions_raw_df)
    for i in range(len(raw)):
        raw_type = raw.loc[i, "Type"]
        if pd.isna(raw_type):
            assert out.loc[i, "session_type"] is None
        else:
            assert out.loc[i, "session_type"] == int(raw_type)


def test_transform_sessions_unique_key_columns_present(sessions_raw_df):
    out = transform_sessions(sessions_raw_df)
    for col in ("session_date", "player_id", "hittrax_session_id"):
        assert col in out.columns


def test_transform_sessions_hittrax_session_id_maps_from_id(sessions_raw_df):
    raw = pd.read_csv(SESSION_FIXTURE, encoding="utf-8-sig")
    out = transform_sessions(sessions_raw_df)
    assert list(out["hittrax_session_id"]) == [int(x) for x in raw["Id"]]


def test_transform_sessions_session_date_is_date_part_of_ts(sessions_raw_df):
    raw = pd.read_csv(SESSION_FIXTURE, encoding="utf-8-sig")
    out = transform_sessions(sessions_raw_df)
    expected_dates = pd.to_datetime(raw["TS"]).dt.date
    assert list(out["session_date"]) == list(expected_dates)


def test_transform_sessions_player_id_from_usid(sessions_raw_df):
    raw = pd.read_csv(SESSION_FIXTURE, encoding="utf-8-sig")
    out = transform_sessions(sessions_raw_df)
    assert list(out["player_id"]) == [int(x) for x in raw["UsId"]]


def test_transform_sessions_source_file_populated(sessions_raw_df):
    out = transform_sessions(sessions_raw_df)
    assert (out["source_file"] == "SessionExport_sample.CSV").all()


def test_transform_sessions_missing_numeric_becomes_none_not_zero():
    payload = {"Id": 1, "TS": "1/1/2026 1:00:00 PM", "UsId": 5, "AEV": None}
    raw_df = pd.DataFrame({
        "source_file": ["SessionExport_x.CSV"],
        "payload": [json.dumps(payload)],
    })
    out = transform_sessions(raw_df)
    assert out.loc[0, "avg_exit_velocity"] is None


def test_transform_sessions_blank_string_numeric_becomes_none():
    payload = {"Id": 1, "TS": "1/1/2026 1:00:00 PM", "UsId": 5, "AEV": ""}
    raw_df = pd.DataFrame({
        "source_file": ["SessionExport_x.CSV"],
        "payload": [json.dumps(payload)],
    })
    out = transform_sessions(raw_df)
    assert out.loc[0, "avg_exit_velocity"] is None


def test_transform_sessions_first_last_name_split_from_username():
    payload = {"Id": 1, "TS": "1/1/2026 1:00:00 PM", "UsId": 5, "UserName": "Conner Larkin"}
    raw_df = pd.DataFrame({
        "source_file": ["SessionExport_x.CSV"],
        "payload": [json.dumps(payload)],
    })
    out = transform_sessions(raw_df)
    assert out.loc[0, "first_name"] == "Conner"
    assert out.loc[0, "last_name"] == "Larkin"


def test_transform_sessions_empty_raw_df_returns_empty_frame():
    empty = pd.DataFrame(columns=["source_file", "payload"])
    out = transform_sessions(empty)
    assert len(out) == 0
    assert "avg_exit_velocity" in out.columns


def test_transform_sessions_drops_row_with_blank_ts():
    # PRACTICE_SESSIONS.session_date is NOT NULL; a blank TS can't produce
    # a session_date, so the row must be excluded rather than passed
    # through with a null session_date that would fail the DB constraint.
    payload = {"Id": 1, "TS": "", "UsId": 5, "AEV": 30.0}
    raw_df = pd.DataFrame({
        "source_file": ["SessionExport_x.CSV"],
        "payload": [json.dumps(payload)],
    })
    out = transform_sessions(raw_df)
    assert len(out) == 0


def test_transform_sessions_drops_row_with_unparseable_ts():
    payload = {"Id": 1, "TS": "not-a-date", "UsId": 5, "AEV": 30.0}
    raw_df = pd.DataFrame({
        "source_file": ["SessionExport_x.CSV"],
        "payload": [json.dumps(payload)],
    })
    out = transform_sessions(raw_df)
    assert len(out) == 0


def test_transform_sessions_keeps_good_rows_alongside_dropped_bad_ts_row():
    good = {"Id": 1, "TS": "1/1/2026 1:00:00 PM", "UsId": 5, "AEV": 30.0}
    bad = {"Id": 2, "TS": "", "UsId": 6, "AEV": 20.0}
    raw_df = pd.DataFrame({
        "source_file": ["SessionExport_x.CSV", "SessionExport_x.CSV"],
        "payload": [json.dumps(good), json.dumps(bad)],
    })
    out = transform_sessions(raw_df)
    assert len(out) == 1
    assert out.loc[0, "hittrax_session_id"] == 1


# ---------------------------------------------------------------------------
# transform_plays
# ---------------------------------------------------------------------------

def test_transform_plays_returns_one_row_per_raw_row(plays_raw_df):
    empty_sessions = pd.DataFrame(columns=["session_id", "session_date", "player_id"])
    out = transform_plays(plays_raw_df, empty_sessions)
    assert len(out) == 30


def test_transform_plays_field_map_has_velo_dist_id():
    assert PLAYS_FIELD_MAP["exit_velocity"] == ("Velo", "mph")
    assert PLAYS_FIELD_MAP["distance_feet"] == ("Dist", "ft")
    assert PLAYS_FIELD_MAP["play_id"] == ("Id", "int")


def test_transform_plays_exit_velocity_velo_mps_to_mph(plays_raw_df):
    raw = pd.read_csv(PLAYS_FIXTURE, encoding="utf-8-sig")
    empty_sessions = pd.DataFrame(columns=["session_id", "session_date", "player_id"])
    out = transform_plays(plays_raw_df, empty_sessions)

    checked_any = False
    for i in range(len(raw)):
        raw_velo = raw.loc[i, "Velo"]
        if pd.isna(raw_velo):
            continue
        expected = round(float(raw_velo) * 2.23694, 2)
        assert out.loc[i, "exit_velocity"] == expected
        checked_any = True
    assert checked_any


def test_transform_plays_distance_feet_dist_meters_to_feet(plays_raw_df):
    raw = pd.read_csv(PLAYS_FIXTURE, encoding="utf-8-sig")
    empty_sessions = pd.DataFrame(columns=["session_id", "session_date", "player_id"])
    out = transform_plays(plays_raw_df, empty_sessions)

    checked_any = False
    for i in range(len(raw)):
        raw_dist = raw.loc[i, "Dist"]
        if pd.isna(raw_dist):
            continue
        expected = round(float(raw_dist) * 3.28084, 2)
        assert out.loc[i, "distance_feet"] == expected
        checked_any = True
    assert checked_any


def test_transform_plays_play_id_maps_from_id(plays_raw_df):
    raw = pd.read_csv(PLAYS_FIXTURE, encoding="utf-8-sig")
    empty_sessions = pd.DataFrame(columns=["session_id", "session_date", "player_id"])
    out = transform_plays(plays_raw_df, empty_sessions)
    assert list(out["play_id"]) == [int(x) for x in raw["Id"]]


def test_transform_plays_missing_numeric_becomes_none_not_zero():
    payload = {"Id": 1, "TS": "1/1/2026 1:00:00 PM", "UsId": 5, "Velo": None, "Dist": ""}
    raw_df = pd.DataFrame({
        "source_file": ["PlaysExport_x.CSV"],
        "payload": [json.dumps(payload)],
    })
    empty_sessions = pd.DataFrame(columns=["session_id", "session_date", "player_id"])
    out = transform_plays(raw_df, empty_sessions)
    assert out.loc[0, "exit_velocity"] is None
    assert out.loc[0, "distance_feet"] is None


def test_transform_plays_session_id_matches_on_date_and_player(plays_raw_df):
    raw = pd.read_csv(PLAYS_FIXTURE, encoding="utf-8-sig")
    first_ts = pd.to_datetime(raw.loc[0, "TS"])
    first_player = int(raw.loc[0, "UsId"])

    sessions_with_ids = pd.DataFrame({
        "session_id": [42],
        "session_date": [first_ts.date()],
        "player_id": [first_player],
    })
    out = transform_plays(plays_raw_df, sessions_with_ids)
    assert out.loc[0, "session_id"] == 42


def test_transform_plays_session_id_is_null_when_no_match(plays_raw_df):
    sessions_with_ids = pd.DataFrame({
        "session_id": [999],
        "session_date": [pd.Timestamp("1901-01-01").date()],
        "player_id": [-99999],
    })
    out = transform_plays(plays_raw_df, sessions_with_ids)
    assert out["session_id"].isna().all()


def test_transform_plays_session_dedup_keeps_first_match_only(plays_raw_df):
    raw = pd.read_csv(PLAYS_FIXTURE, encoding="utf-8-sig")
    first_ts = pd.to_datetime(raw.loc[0, "TS"])
    first_player = int(raw.loc[0, "UsId"])

    # Two candidate sessions share the same (date, player) -- dedup must
    # keep the FIRST and must not fan the play out into two rows.
    sessions_with_ids = pd.DataFrame({
        "session_id": [42, 43],
        "session_date": [first_ts.date(), first_ts.date()],
        "player_id": [first_player, first_player],
    })
    out = transform_plays(plays_raw_df, sessions_with_ids)
    assert len(out) == 30  # no row fan-out
    assert out.loc[0, "session_id"] == 42


def test_transform_plays_source_file_populated(plays_raw_df):
    empty_sessions = pd.DataFrame(columns=["session_id", "session_date", "player_id"])
    out = transform_plays(plays_raw_df, empty_sessions)
    assert (out["source_file"] == "PlaysExport_sample.CSV").all()


def test_transform_plays_practice_plays_column_present_no_session_date_leak():
    payload = {"Id": 1, "TS": "1/1/2026 1:00:00 PM", "UsId": 5}
    raw_df = pd.DataFrame({
        "source_file": ["PlaysExport_x.CSV"],
        "payload": [json.dumps(payload)],
    })
    empty_sessions = pd.DataFrame(columns=["session_id", "session_date", "player_id"])
    out = transform_plays(raw_df, empty_sessions)
    assert "session_date" not in out.columns
    assert "session_id" in out.columns


def test_transform_plays_empty_raw_df_returns_empty_frame():
    empty = pd.DataFrame(columns=["source_file", "payload"])
    empty_sessions = pd.DataFrame(columns=["session_id", "session_date", "player_id"])
    out = transform_plays(empty, empty_sessions)
    assert len(out) == 0
    assert "exit_velocity" in out.columns


# ---------------------------------------------------------------------------
# transform(): DB-write path, exercised against a FAKE engine/connection
# (no real DB) -- only to prove the destructive statements are DELETE, not
# TRUNCATE. `RAW_PRACTICE_CSV` is faked as empty (via the fake connection's
# `.execute(...).mappings().all()` returning `[]`), and `pd.read_sql` (used
# to re-fetch PRACTICE_SESSIONS' auto-generated session_ids) is monkeypatched
# to a canned empty frame, so nothing here depends on real SQLAlchemy/pandas
# DB-execution semantics.
# ---------------------------------------------------------------------------

class _FakeExecResult:
    """Stands in for a SQLAlchemy `CursorResult`: supports the handful of
    methods `transform()`/`_load_raw()` call on whatever `conn.execute(...)`
    returns (`.scalar()`, and `.mappings().all()` for the raw-row fetch)."""

    def scalar(self):
        return 0

    def mappings(self):
        return self

    def all(self):
        return []


class _FakeTrans:
    """Stands in for a SQLAlchemy Transaction (`conn.begin()`'s return
    value): records `commit()`/`rollback()` calls in the same `executed`
    log as the connection's SQL statements, so tests can assert ordering."""

    def __init__(self, executed: list[str]):
        self.executed = executed

    def commit(self):
        self.executed.append("TRANS_COMMIT")

    def rollback(self):
        self.executed.append("TRANS_ROLLBACK")


class _FakeConn:
    """Fake SQLAlchemy Connection: records every SQL statement's text (as a
    plain string) in `executed`, usable both as `engine.begin()`'s context
    manager and as `engine.connect()`'s (both are used by `transform()`)."""

    def __init__(self, executed: list[str]):
        self.executed = executed

    def execute(self, sql, params=None):
        self.executed.append(str(sql))
        return _FakeExecResult()

    def begin(self):
        return _FakeTrans(self.executed)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeEngine:
    """Fake engine whose `begin()`/`connect()` both hand back the SAME
    `_FakeConn` (so every statement `transform()` issues lands in one
    `executed` list, in call order)."""

    def __init__(self):
        self.executed: list[str] = []

    def begin(self):
        return _FakeConn(self.executed)

    def connect(self):
        return _FakeConn(self.executed)


def test_transform_uses_delete_not_truncate_for_rebuild(monkeypatch):
    import app.ingest.hittrax as hittrax_module

    # transform() re-queries PRACTICE_SESSIONS (via pd.read_sql) after
    # inserting sessions, to get real auto-increment session_ids for the
    # play merge -- faked here as an empty frame with the right columns.
    monkeypatch.setattr(
        hittrax_module.pd,
        "read_sql",
        lambda *a, **k: pd.DataFrame(columns=["session_id", "session_date", "player_id"]),
    )

    engine = _FakeEngine()
    result = transform(engine, dry_run=False)

    executed_upper = [s.upper() for s in engine.executed]
    assert any("DELETE FROM PRACTICE_PLAYS" in s for s in executed_upper)
    assert any("DELETE FROM PRACTICE_SESSIONS" in s for s in executed_upper)
    assert any("DELETE FROM PLAYER_STATS_SUMMARY" in s for s in executed_upper)
    assert not any("TRUNCATE" in s for s in executed_upper), (
        "transform() must never issue TRUNCATE -- it's DDL with an implicit "
        "commit in MySQL, breaking this transaction's atomic rebuild guarantee"
    )
    # FK checks toggled off then back on, around the deletes/inserts.
    assert any("FOREIGN_KEY_CHECKS = 0" in s for s in executed_upper)
    assert any("FOREIGN_KEY_CHECKS = 1" in s for s in executed_upper)
    assert result == {"sessions": 0, "plays": 0, "players": 0}


def test_transform_reenables_fk_checks_after_failed_rebuild(monkeypatch):
    """If any statement in the rebuild raises, `transform()` must still
    re-enable FK checks on the SAME (pooled) connection before the
    exception propagates -- `SET FOREIGN_KEY_CHECKS` is a per-connection
    session variable, not transactional DML, so the transaction rollback
    does NOT undo it. Without the `finally`, a failed rebuild would check a
    connection with FK checks permanently off back into the pool.
    """
    import app.ingest.hittrax as hittrax_module

    monkeypatch.setattr(
        hittrax_module.pd,
        "read_sql",
        lambda *a, **k: pd.DataFrame(columns=["session_id", "session_date", "player_id"]),
    )

    class _BoomConn(_FakeConn):
        def execute(self, sql, params=None):
            s = str(sql)
            if "INSERT INTO player_stats_summary" in s:
                # Record it (as the real connection would, having received
                # the statement) before raising, so the test can still
                # assert on ordering relative to the failure.
                self.executed.append(s)
                raise RuntimeError("boom: aggregation step failed")
            return super().execute(sql, params)

    class _BoomEngine(_FakeEngine):
        def connect(self):
            return _BoomConn(self.executed)

    engine = _BoomEngine()

    with pytest.raises(RuntimeError, match="boom: aggregation step failed"):
        hittrax_module.transform(engine, dry_run=False)

    executed_upper = [s.upper() for s in engine.executed]
    # Turned off once at the top of the rebuild...
    assert executed_upper.count("SET FOREIGN_KEY_CHECKS = 0") == 1
    # ...and turned back on in the `finally`, even though the rebuild raised
    # (the happy-path `SET ... = 1` right before the failing statement never
    # ran, so this can only be the `finally`'s safety net).
    assert executed_upper.count("SET FOREIGN_KEY_CHECKS = 1") == 1
    assert "TRANS_ROLLBACK" in engine.executed
    assert "TRANS_COMMIT" not in engine.executed
    # The FK-checks reset must come after the rollback, and the rollback
    # must come after the failing statement -- i.e. cleanup order is
    # (fail) -> rollback -> re-enable FK checks.
    fail_idx = next(i for i, s in enumerate(engine.executed) if "INSERT INTO player_stats_summary" in s)
    rollback_idx = engine.executed.index("TRANS_ROLLBACK")
    fk_reenable_idx = executed_upper.index("SET FOREIGN_KEY_CHECKS = 1")
    assert fail_idx < rollback_idx < fk_reenable_idx
