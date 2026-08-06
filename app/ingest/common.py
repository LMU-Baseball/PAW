"""Shared helpers for ingestion loaders: unit conversions, numeric parsing,
a LoadResult summary type, and generic dedup-insert DB helpers.

`existing_keys` / `chunked_insert` take an explicit `engine` argument (never
import the global `app.db` engine here) so tests can pass a fake/in-memory
engine.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Engine

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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


def _scrub_value(v):
    """NaN (float) -> None; every other value passed through unchanged.

    PyMySQL raises ``nan can not be used with MySQL`` if a bare float NaN
    reaches a bound parameter -- every real Trackman export has blank
    numeric cells that pandas represents as NaN, so this scrub is required
    on every value before binding.
    """
    return None if isinstance(v, float) and math.isnan(v) else v


def chunked_insert(engine: Engine, table: str, rows: list[dict], chunksize: int = 500) -> int:
    """Insert `rows` into `table` in chunks of `chunksize`, parameterized.

    Caller is responsible for pre-filtering out rows that already exist
    (e.g. via `existing_keys`). Returns the number of rows inserted.

    Two safety nets applied per chunk (rows are built by concatenating many
    parsed CSV files, so neither can be assumed):

    - NaN scrub: every value is passed through `_scrub_value` so a bare
      float NaN never reaches a bound parameter (PyMySQL raises `nan can
      not be used with MySQL` otherwise).
    - Column union: the INSERT's column list is the union of every row's
      keys in the chunk (not just `rows[0].keys()`), with missing keys
      filled `None`, so a chunk mixing rows from files with different
      column subsets still produces one consistent INSERT rather than
      silently dropping columns or raising mid-load.
    """
    if not rows:
        return 0

    inserted = 0
    with engine.begin() as conn:
        for start in range(0, len(rows), chunksize):
            chunk = rows[start:start + chunksize]

            cols: list[str] = []
            seen = set()
            for row in chunk:
                for k in row.keys():
                    if k not in seen:
                        seen.add(k)
                        cols.append(k)

            # Backtick-quote column names (handles dots/reserved words/spaces,
            # e.g. GAMES.`Top.Bottom`). Bind-param names must be valid
            # identifiers -- `:Top.Bottom` would parse as param `Top` + literal
            # `.Bottom` -- so any non-identifier column gets a positional alias
            # `p{i}`; ordinary columns keep their name (callers/tests that
            # inspect bound params by column name are unaffected).
            param_names = [c if _IDENTIFIER.match(c) else f"p{i}"
                           for i, c in enumerate(cols)]
            col_list = ", ".join(f"`{c}`" for c in cols)
            placeholders = ", ".join(f":{p}" for p in param_names)
            sql = text(f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})")

            scrubbed_chunk = [
                {param_names[i]: _scrub_value(row.get(c)) for i, c in enumerate(cols)}
                for row in chunk
            ]
            conn.execute(sql, scrubbed_chunk)
            inserted += len(chunk)
    return inserted
