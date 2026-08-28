"""Tests for app.ingest.hittrax: row_hash, csv_to_raw_rows, extract_load_raw.

No network, no live DB: `extract_load_raw` is exercised against a fake
in-memory FTPS client (`nlst`/`retrbinary` only) and a fake SQLAlchemy-like
engine (`begin` -> a fake connection whose `execute` returns a fake result
with a settable `.rowcount`), so no real FTPS connection or SQL engine is
ever touched.
"""
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from app.ingest.hittrax import csv_to_raw_rows, extract_load_raw, row_hash, _sort_key


def _reject_nonstrict_constants(_):
    """`parse_constant` hook for `json.loads`: called only for the
    non-standard `NaN`/`Infinity`/`-Infinity` tokens Python's json module
    otherwise accepts leniently. Raising here makes `json.loads` behave
    like a strict JSON RFC parser for the purposes of this test."""
    raise ValueError("non-strict JSON: encountered NaN/Infinity token")

FIXTURE = Path(__file__).parent / "fixtures" / "ingest" / "hittrax_plays_sample.csv"
FIXTURE_BYTES = FIXTURE.read_bytes()


# ---- row_hash ---------------------------------------------------------

def test_row_hash_is_deterministic_for_same_payload():
    payload = {"a": 1, "b": "two", "c": None}
    assert row_hash(payload) == row_hash(payload)


def test_row_hash_is_stable_regardless_of_key_order():
    assert row_hash({"a": 1, "b": 2}) == row_hash({"b": 2, "a": 1})


def test_row_hash_differs_for_different_payloads():
    assert row_hash({"a": 1}) != row_hash({"a": 2})


def test_row_hash_is_64_char_hex():
    h = row_hash({"a": 1})
    assert len(h) == 64
    int(h, 16)  # raises if not valid hex


# ---- csv_to_raw_rows ---------------------------------------------------

@pytest.fixture
def fixture_df():
    return pd.read_csv(FIXTURE, encoding="utf-8-sig")


def test_csv_to_raw_rows_returns_one_row_per_csv_row(fixture_df):
    rows = csv_to_raw_rows(fixture_df, source_file="PlaysExport_sample.CSV")
    assert len(rows) == 30


def test_csv_to_raw_rows_each_row_has_source_file_hash_and_json_payload(fixture_df):
    rows = csv_to_raw_rows(fixture_df, source_file="PlaysExport_sample.CSV")
    for row in rows:
        assert row["source_file"] == "PlaysExport_sample.CSV"
        assert len(row["row_hash"]) == 64
        int(row["row_hash"], 16)
        # payload must be a valid JSON string
        import json
        parsed = json.loads(row["payload"])
        assert isinstance(parsed, dict)


def test_csv_to_raw_rows_hashes_differ_across_distinct_rows(fixture_df):
    rows = csv_to_raw_rows(fixture_df, source_file="PlaysExport_sample.CSV")
    hashes = {r["row_hash"] for r in rows}
    assert len(hashes) == 30  # fixture rows are all distinct


def test_csv_to_raw_rows_blank_numeric_cells_become_strict_valid_json(fixture_df):
    # Every fixture row has at least one blank cell (e.g. SUuid/SSUuid),
    # which pandas reads as float('nan'). json.dumps(default=str) does NOT
    # sanitize NaN -- the C encoder emits it natively as a bare `NaN` token,
    # which is invalid per the JSON RFC (though Python's own json.loads
    # accepts it leniently, masking the bug). Confirm the payload has no
    # bare NaN/Infinity token and parses under a strict JSON reader.
    assert fixture_df.isna().any().any(), "fixture must contain blank cells to exercise this path"

    rows = csv_to_raw_rows(fixture_df, source_file="PlaysExport_sample.CSV")
    for row in rows:
        payload = row["payload"]
        assert "NaN" not in payload
        assert "Infinity" not in payload
        # Would raise ValueError if a bare NaN/Infinity/-Infinity token were
        # present; must NOT raise for a properly-scrubbed (null-using) payload.
        parsed = json.loads(payload, parse_constant=_reject_nonstrict_constants)
        assert isinstance(parsed, dict)
        # Any originally-NaN cell must now be JSON null (Python None), never NaN.
        assert not any(isinstance(v, float) and math.isnan(v) for v in parsed.values())


def test_csv_to_raw_rows_hash_matches_cleaned_payload_not_raw_nan(fixture_df):
    # The hash must be computed over the SAME cleaned (NaN->None) dict that
    # gets serialized as payload, not over the raw NaN-containing record --
    # otherwise row_hash(cleaned_dict) computed independently wouldn't match
    # what's stored.
    rows = csv_to_raw_rows(fixture_df, source_file="PlaysExport_sample.CSV")
    row = rows[0]
    cleaned = json.loads(row["payload"])
    assert row["row_hash"] == row_hash(cleaned)


# ---- extract_load_raw: fake FTPS + fake engine --------------------------

class _FakeFTPS:
    """Minimal stand-in for ftplib.FTP_TLS: `nlst` + `retrbinary` only."""

    def __init__(self, files: dict[str, bytes]):
        self.files = files  # filename -> raw bytes
        self.retrbinary_calls: list[str] = []

    def nlst(self):
        return list(self.files.keys())

    def retrbinary(self, command: str, callback):
        assert command.startswith("RETR ")
        filename = command[len("RETR "):]
        self.retrbinary_calls.append(filename)
        callback(self.files[filename])


@pytest.fixture
def fake_ftps():
    return _FakeFTPS({
        "PlaysExport_sample.CSV": FIXTURE_BYTES,
        "empty.CSV": b"x",  # < 10 bytes: offseason/empty export, must be skipped
    })


class _EngineMustNotBeCalled:
    """Fake engine that fails the test if `begin()` is ever invoked -- used
    to prove dry_run never touches the engine."""

    def begin(self):
        pytest.fail("engine.begin() must not be called when dry_run=True")


def test_extract_load_raw_dry_run_writes_nothing(fake_ftps):
    result = extract_load_raw(
        engine=_EngineMustNotBeCalled(),
        ftps=fake_ftps,
        ingested_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
        dry_run=True,
    )
    assert result.inserted == 30
    assert result.files == 1  # only the non-empty CSV counts
    assert result.dry_run is True


def test_extract_load_raw_dry_run_skips_small_files(fake_ftps):
    extract_load_raw(
        engine=_EngineMustNotBeCalled(),
        ftps=fake_ftps,
        ingested_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
        dry_run=True,
    )
    # the < 10 byte file must never even be RETR'd for CSV-parsing purposes
    # (it's fine if it was downloaded to check its size, but it must not
    # contribute any rows) -- verified indirectly via files==1 above; here
    # we also confirm retrbinary was attempted for both names.
    assert set(fake_ftps.retrbinary_calls) == {"PlaysExport_sample.CSV", "empty.CSV"}


class _FakeResult:
    def __init__(self, rowcount: int):
        self.rowcount = rowcount


class _FakeConn:
    def __init__(self, rowcount: int, calls: list):
        self._rowcount = rowcount
        self._calls = calls

    def execute(self, sql, params):
        self._calls.append((sql, params))
        return _FakeResult(self._rowcount)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeSelectResult:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeSelectConn:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def execute(self, sql):
        return _FakeSelectResult(self._rows)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeEngine:
    """Fake engine reporting a fixed `rowcount` from `execute`, simulating
    MySQL's INSERT IGNORE behavior where duplicate rows (matched row_hash)
    don't count toward rowcount. `already_loaded` seeds what
    `_already_loaded_files` reads back via `connect()` (empty by default, so
    existing tests that don't care about skip-already-loaded behavior see no
    filtering, same as before that feature existed)."""

    def __init__(self, rowcount: int, already_loaded: list[str] | None = None):
        self.rowcount = rowcount
        self.calls: list = []
        self._already_loaded = already_loaded or []

    def begin(self):
        return _FakeConn(self.rowcount, self.calls)

    def connect(self):
        return _FakeSelectConn([{"source_file": f} for f in self._already_loaded])


def test_extract_load_raw_not_dry_run_computes_inserted_and_ignored_from_rowcount(fake_ftps):
    # Simulate 20 of the 30 rows actually inserting (10 already present).
    engine = _FakeEngine(rowcount=20)

    result = extract_load_raw(
        engine=engine,
        ftps=fake_ftps,
        ingested_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
        dry_run=False,
    )

    assert result.inserted == 20
    assert result.skipped == 10  # ignored duplicates
    assert result.dry_run is False
    assert len(engine.calls) == 1
    sql_text, params = engine.calls[0]
    assert "INSERT IGNORE" in str(sql_text)
    assert len(params) == 30
    assert params[0]["ingested_at"] == datetime(2026, 7, 30, tzinfo=timezone.utc)


def test_extract_load_raw_not_dry_run_all_new_rows_inserted(fake_ftps):
    engine = _FakeEngine(rowcount=30)

    result = extract_load_raw(
        engine=engine,
        ftps=fake_ftps,
        ingested_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
        dry_run=False,
    )

    assert result.inserted == 30
    assert result.skipped == 0


def test_extract_load_raw_limit_caps_files_processed(fake_ftps):
    result = extract_load_raw(
        engine=_EngineMustNotBeCalled(),
        ftps=fake_ftps,
        ingested_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
        dry_run=True,
        limit=0,
    )
    assert result.files == 0
    assert result.inserted == 0


# ---- _sort_key: real HitTrax filename shapes ----------------------------

def test_sort_key_interleaves_plays_and_session_chronologically():
    # A plain alphabetical sort would put every PlaysExport_* name before
    # every SessionExport_* name regardless of date (P < S) -- this is
    # exactly the bug docs/PIPELINE_CRON.md documents. _sort_key must not
    # reproduce it.
    names = [
        "SessionExport_2026-08-20-08-40-14_UTC.CSV",
        "PlaysExport_2026-08-21-08-40-09_UTC.CSV",
        "PlaysExport_2026-08-19-08-40-11_UTC.CSV",
    ]
    assert sorted(names, key=_sort_key) == [
        "PlaysExport_2026-08-19-08-40-11_UTC.CSV",
        "SessionExport_2026-08-20-08-40-14_UTC.CSV",
        "PlaysExport_2026-08-21-08-40-09_UTC.CSV",
    ]


def test_sort_key_falls_back_to_filename_for_unexpected_shapes():
    # No embedded timestamp -> sorts by its own name rather than crashing.
    assert _sort_key("weird_export.CSV") == "weird_export.CSV"


# ---- extract_load_raw: live-mode skip-already-loaded + newest-first -----

@pytest.fixture
def dated_fake_ftps():
    names = [
        "PlaysExport_2026-08-19-08-40-11_UTC.CSV",
        "PlaysExport_2026-08-20-08-40-09_UTC.CSV",
        "PlaysExport_2026-08-21-08-40-14_UTC.CSV",
    ]
    return _FakeFTPS({n: FIXTURE_BYTES for n in names})


def test_extract_load_raw_live_skips_already_loaded_files(dated_fake_ftps):
    # 08-20 was already fully loaded by a prior run; only 08-19/08-21 remain
    # candidates, and with limit=1 only the newest of those two is picked.
    engine = _FakeEngine(rowcount=30, already_loaded=[
        "PlaysExport_2026-08-20-08-40-09_UTC.CSV",
    ])

    extract_load_raw(
        engine=engine,
        ftps=dated_fake_ftps,
        ingested_at=datetime(2026, 8, 28, tzinfo=timezone.utc),
        dry_run=False,
        limit=1,
    )

    assert dated_fake_ftps.retrbinary_calls == ["PlaysExport_2026-08-21-08-40-14_UTC.CSV"]


def test_extract_load_raw_live_processes_newest_first(dated_fake_ftps):
    engine = _FakeEngine(rowcount=30)

    extract_load_raw(
        engine=engine,
        ftps=dated_fake_ftps,
        ingested_at=datetime(2026, 8, 28, tzinfo=timezone.utc),
        dry_run=False,
        limit=2,
    )

    assert dated_fake_ftps.retrbinary_calls == [
        "PlaysExport_2026-08-21-08-40-14_UTC.CSV",
        "PlaysExport_2026-08-20-08-40-09_UTC.CSV",
    ]


def test_extract_load_raw_dry_run_does_not_skip_already_loaded(dated_fake_ftps):
    # dry_run never touches the engine at all (see
    # test_extract_load_raw_dry_run_writes_nothing), so the skip-already-
    # loaded exclusion -- which requires a read -- deliberately does not
    # apply here. It still gets the newest-first ordering, which needs no DB
    # access.
    result = extract_load_raw(
        engine=_EngineMustNotBeCalled(),
        ftps=dated_fake_ftps,
        ingested_at=datetime(2026, 8, 28, tzinfo=timezone.utc),
        dry_run=True,
        limit=2,
    )
    assert dated_fake_ftps.retrbinary_calls == [
        "PlaysExport_2026-08-21-08-40-14_UTC.CSV",
        "PlaysExport_2026-08-20-08-40-09_UTC.CSV",
    ]
    assert result.files == 2
