"""Shared helpers for ingestion loaders: unit conversions, numeric parsing,
a LoadResult summary type, and generic dedup-insert DB helpers.

`existing_keys` / `chunked_insert` take an explicit `engine` argument (never
import the global `app.db` engine here) so tests can pass a fake/in-memory
engine.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Engine


@dataclass
class LoadResult:
    inserted: int
    skipped: int
    files: int
    date_min: str | None
    date_max: str | None
    dry_run: bool


def safe_numeric(x) -> float | None:
    """Parse x as a float; return None for missing/blank/unparseable input."""
    if x is None:
        return None
    if isinstance(x, str) and x.strip() == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def mps_to_mph(x) -> float | None:
    """Meters/sec -> miles/hour, rounded to 2 decimals. None for missing input."""
    v = safe_numeric(x)
    if v is None:
        return None
    return round(v * 2.23694, 2)


def meters_to_feet(x) -> float | None:
    """Meters -> feet, rounded to 2 decimals. None for missing input."""
    v = safe_numeric(x)
    if v is None:
        return None
    return round(v * 3.28084, 2)


def existing_keys(engine: Engine, table: str, col: str) -> set[str]:
    """Distinct values of `col` in `table`, as strings, with None dropped."""
    sql = text(f"SELECT DISTINCT {col} AS k FROM {table}")
    with engine.connect() as conn:
        rows = conn.execute(sql).fetchall()
    return {str(r.k) for r in rows if r.k is not None}


def chunked_insert(engine: Engine, table: str, rows: list[dict], chunksize: int = 500) -> int:
    """Insert `rows` into `table` in chunks of `chunksize`, parameterized.

    Caller is responsible for pre-filtering out rows that already exist
    (e.g. via `existing_keys`). Returns the number of rows inserted.
    """
    if not rows:
        return 0

    cols = list(rows[0].keys())
    col_list = ", ".join(cols)
    placeholders = ", ".join(f":{c}" for c in cols)
    sql = text(f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})")

    inserted = 0
    with engine.begin() as conn:
        for start in range(0, len(rows), chunksize):
            chunk = rows[start:start + chunksize]
            conn.execute(sql, chunk)
            inserted += len(chunk)
    return inserted
