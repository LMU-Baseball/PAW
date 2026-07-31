"""HitTrax raw ELT: FTPS -> `raw_practice_csv` staging table.

Reproduces the "Extract & Load Phase" of the original pipeline (see
``docs/reference/hittrax-practice-analytics/pipeline-architecture.md`` §1):
list the HitTrax FTPS root, read each CSV (``PlaysExport_*``/
``SessionExport_*``), convert every row to a JSON payload, compute a
SHA-256 ``row_hash`` for dedup, and ``INSERT IGNORE`` into
``raw_practice_csv`` keyed on that hash (UNIQUE column) -- idempotent by
construction, so re-running never creates duplicate rows.

Pure helpers (``row_hash``/``csv_to_raw_rows``) take no network/DB
arguments so they're trivially unit-testable. The loader
(``extract_load_raw``) takes an explicit ``engine``/``ftps`` (never the
global ``app.db`` engine or a real connection) so tests can pass fakes.
``ingested_at`` is supplied by the caller (e.g. the CLI) rather than
computed inside this module, keeping the loader's only side effects
network I/O and the single INSERT IGNORE statement.
"""
from __future__ import annotations

import hashlib
import io
import json

import pandas as pd
from sqlalchemy import text

from app.ingest.common import LoadResult

_MIN_FILE_BYTES = 10  # smaller than this = an offseason/empty export; skip it


def row_hash(payload: dict) -> str:
    """SHA-256 hex digest of `payload`, stable across dict key order and
    non-JSON-native values (dates, NaN, etc. via ``default=str``)."""
    encoded = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def csv_to_raw_rows(df: pd.DataFrame, *, source_file: str) -> list[dict]:
    """Convert every row of `df` into a `raw_practice_csv` insert-ready dict:
    ``{"source_file", "row_hash", "payload"}`` where ``payload`` is the row's
    JSON string (the hash is computed from the same row dict, not the
    string, so key order never affects it)."""
    rows: list[dict] = []
    for record in df.to_dict(orient="records"):
        rows.append({
            "source_file": source_file,
            "row_hash": row_hash(record),
            "payload": json.dumps(record, default=str),
        })
    return rows


def _list_csv_files(ftps) -> list[str]:
    """List the FTPS root via `nlst()` and keep `*.csv`/`*.CSV` names.

    Real HitTrax exports sit flat at the remote root (no subdirectories),
    so no recursive walk is needed here (unlike the Trackman SFTP loaders).
    """
    names = ftps.nlst()
    return sorted(n for n in names if n.lower().endswith(".csv"))


def _download(ftps, filename: str) -> bytes:
    """Fetch `filename` from the FTPS root into memory via RETR."""
    buf = io.BytesIO()
    ftps.retrbinary(f"RETR {filename}", buf.write)
    return buf.getvalue()


def _read_csv_bytes(data: bytes) -> pd.DataFrame:
    """Parse downloaded HitTrax CSV bytes with pandas.

    HitTrax exports a UTF-8 byte-order-mark on every file, hence
    ``utf-8-sig`` (plain ``utf-8`` would leave a BOM glyph glued onto the
    first column name).
    """
    return pd.read_csv(io.BytesIO(data), encoding="utf-8-sig")


def extract_load_raw(
    engine,
    ftps,
    *,
    ingested_at,
    dry_run: bool = True,
    limit: int | None = None,
) -> LoadResult:
    """List the HitTrax FTPS root, read each CSV, and `INSERT IGNORE` every
    row (as JSON) into `raw_practice_csv`.

    Skips files smaller than 10 bytes (offseason/empty exports). `limit`
    caps the number of files processed, not rows. `ingested_at` is a
    caller-supplied timestamp (this function never calls `datetime.now`
    itself) written into every row's `ingested_at_utc`.

    Idempotent via `row_hash` (UNIQUE column) + `INSERT IGNORE`: re-running
    against the same files inserts nothing new. `dry_run=True` (default)
    never touches `engine` at all -- rows are parsed and counted, but no
    SQL is issued.
    """
    filenames = _list_csv_files(ftps)
    if limit is not None:
        filenames = filenames[:limit]

    rows_to_insert: list[dict] = []
    files_read = 0
    files_skipped = 0

    for filename in filenames:
        data = _download(ftps, filename)
        if len(data) < _MIN_FILE_BYTES:
            files_skipped += 1
            continue
        df = _read_csv_bytes(data)
        rows_to_insert.extend(csv_to_raw_rows(df, source_file=filename))
        files_read += 1

    inserted = len(rows_to_insert)
    ignored = 0

    if not dry_run and rows_to_insert:
        sql = text(
            "INSERT IGNORE INTO raw_practice_csv "
            "(source_file, ingested_at_utc, row_hash, payload) "
            "VALUES (:source_file, :ingested_at, :row_hash, CAST(:payload AS JSON))"
        )
        params = [{**row, "ingested_at": ingested_at} for row in rows_to_insert]
        with engine.begin() as conn:
            result = conn.execute(sql, params)
        inserted = result.rowcount if result.rowcount is not None and result.rowcount >= 0 else 0
        ignored = len(rows_to_insert) - inserted

    return LoadResult(
        inserted=inserted,
        skipped=ignored,
        files=files_read,
        date_min=None,
        date_max=None,
        dry_run=dry_run,
    )
