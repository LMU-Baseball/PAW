"""HitTrax raw ELT: FTPS -> `RAW_PRACTICE_CSV` staging table, PLUS the
transform step from that raw layer into the clean analytics tables
(`PRACTICE_SESSIONS` / `PRACTICE_PLAYS`).

Note on `player_stats_summary`: the original pipeline maintained a third table
by that name, and this module used to rebuild it. It does not any more. That
table belongs to the separate Streamlit practice-analytics app, whose scheduled
ETL drops and recreates it (lowercase) on its own timetable, and PAW never read
it -- `app.data.practice.load_player_stats` aggregates the same shape from
PRACTICE_SESSIONS + PRACTICE_PLAYS instead. Writing it from here meant two apps
fighting over one table, and left `transform()` failing outright whenever the
other app's ETL had dropped it.

Reproduces the "Extract & Load Phase" of the original pipeline (see
``docs/reference/hittrax-practice-analytics/pipeline-architecture.md`` §1):
list the HitTrax FTPS root, read each CSV (``PlaysExport_*``/
``SessionExport_*``), convert every row to a JSON payload, compute a
SHA-256 ``row_hash`` for dedup, and ``INSERT IGNORE`` into
``RAW_PRACTICE_CSV`` keyed on that hash (UNIQUE column) -- idempotent by
construction, so re-running never creates duplicate rows.

Pure helpers (``row_hash``/``csv_to_raw_rows``) take no network/DB
arguments so they're trivially unit-testable. The loader
(``extract_load_raw``) takes an explicit ``engine``/``ftps`` (never the
global ``app.db`` engine or a real connection) so tests can pass fakes.
``ingested_at`` is supplied by the caller (e.g. the CLI) rather than
computed inside this module, keeping the loader's only side effects
network I/O and the single INSERT IGNORE statement.

The transform step (§2 of the same doc) reproduces
``scripts/practice_transform.py``: ``transform_sessions``/``transform_plays``
are PURE (raw JSON-payload DataFrame in, clean-table-shaped DataFrame out --
column names + unit conversions follow
``docs/reference/hittrax-practice-analytics/transformed_schema.sql``'s
per-column source-code comments exactly); ``transform`` is the impure
orchestrator that reads the raw table, runs both pure transforms, and
truncates+reloads the three analytics tables inside one transaction.

A few clean columns have NO HitTrax-source comment in ``transformed_schema.sql``
(e.g. sessions/plays ``player_id``/``player_uuid``/names). Those are filled via
a documented PROVISIONAL inference -- see each function's docstring and the
task report (``.superpowers/sdd/2026-07-30-data-ingestion-loaders/task-7-report.md``)
for the full list and rationale.
"""
from __future__ import annotations

import hashlib
import io
import json

import pandas as pd
from sqlalchemy import text

from app.ingest.common import LoadResult, meters_to_feet, mps_to_mph, safe_numeric

_MIN_FILE_BYTES = 10  # smaller than this = an offseason/empty export; skip it


def row_hash(payload: dict) -> str:
    """SHA-256 hex digest of `payload`, stable across dict key order and
    non-JSON-native values (dates, etc. via ``default=str``).

    NOTE: this does NOT sanitize NaN/NaT -- Python's json encoder emits
    those as bare (invalid-JSON) `NaN`/`Infinity` tokens without ever
    consulting ``default``. Callers must scrub NaN/NaT to `None` in the
    payload dict *before* calling this (see `csv_to_raw_rows`), so the hash
    is computed over the same cleaned dict that gets stored as JSON.
    """
    encoded = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _clean_record(record: dict) -> dict:
    """Replace NaN/NaT values with `None` so JSON-encoding emits `null`
    instead of the bare (invalid-JSON) `NaN` token.

    pandas represents missing numeric/datetime cells as `float('nan')` /
    `pandas.NaT`. Python's `json` module encodes `float('nan')` as the
    literal `NaN` by default (a JSON5/JS extension, not valid per the JSON
    RFC) -- `json.dumps`'s ``default`` hook is never even consulted for
    floats, so this can't be fixed at serialization time. MySQL's
    `CAST(... AS JSON)` rejects `NaN`, and every real HitTrax export has
    blank cells, so this scrub is required before every row hash/payload.
    """
    # `v != v` is the classic NaN self-inequality check (IEEE 754); it also
    # catches `pandas.NaT` (which implements the same not-equal-to-self
    # semantics) without needing an `isinstance(v, float)` guard that would
    # miss NaT.
    return {k: (None if v != v else v) for k, v in record.items()}


def csv_to_raw_rows(df: pd.DataFrame, *, source_file: str) -> list[dict]:
    """Convert every row of `df` into a `RAW_PRACTICE_CSV` insert-ready dict:
    ``{"source_file", "row_hash", "payload"}`` where ``payload`` is the row's
    JSON string (the hash is computed from the same cleaned row dict as the
    stored payload -- see `_clean_record` -- so key order never affects the
    hash and NaN cells never produce invalid JSON)."""
    rows: list[dict] = []
    for record in df.to_dict(orient="records"):
        cleaned = _clean_record(record)
        rows.append({
            "source_file": source_file,
            "row_hash": row_hash(cleaned),
            "payload": json.dumps(cleaned, default=str),
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
    row (as JSON) into `RAW_PRACTICE_CSV`.

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
            "INSERT IGNORE INTO RAW_PRACTICE_CSV "
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


# ===========================================================================
# TRANSFORM: RAW_PRACTICE_CSV -> PRACTICE_SESSIONS / PRACTICE_PLAYS
#
# Column-by-column mapping source of truth:
# docs/reference/hittrax-practice-analytics/transformed_schema.sql
# Flow reference: docs/reference/hittrax-practice-analytics/pipeline-architecture.md §2
# ===========================================================================


def _to_int(x) -> int | None:
    """`safe_numeric(x)` rounded to the nearest int, or None for missing input."""
    v = safe_numeric(x)
    return None if v is None else int(round(v))


def _to_str(x) -> str | None:
    """None/NaN/blank -> None; otherwise `str(x).strip()` (empty-after-strip -> None)."""
    if x is None:
        return None
    if isinstance(x, float) and pd.isna(x):
        return None
    s = str(x).strip()
    return s or None


def _col(data: pd.DataFrame, name: str) -> pd.Series:
    """`data[name]` if present, else an all-None Series aligned to `data`'s
    index -- HitTrax payloads don't always carry every possible column, and a
    plain `data[name]` would raise KeyError."""
    if name in data.columns:
        return data[name]
    return pd.Series([None] * len(data), index=data.index)


# Converter keys used by SESSION_FIELD_MAP / PLAYS_FIELD_MAP below.
_CONVERTERS = {
    "num": lambda s: s.apply(safe_numeric),   # numeric, no unit conversion
    "mph": lambda s: s.apply(mps_to_mph),     # m/s -> mph
    "ft": lambda s: s.apply(meters_to_feet),  # meters -> feet
    "int": lambda s: s.apply(_to_int),
    "str": lambda s: s.apply(_to_str),
}


def _payload_frame(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Parse every row's JSON `payload` string into one normalized column per
    HitTrax field (`pd.json_normalize`), producing a fresh 0..n-1 RangeIndex.
    Returns an empty DataFrame (no columns) if `raw_df` has no rows.
    """
    if raw_df.empty:
        return pd.DataFrame()
    records = [json.loads(p) for p in raw_df["payload"]]
    return pd.json_normalize(records)


def _apply_field_map(data: pd.DataFrame, field_map: dict[str, tuple[str, str]]) -> pd.DataFrame:
    """Build one output column per `field_map` entry ``{out_col: (src_col,
    converter_key)}``. A source column absent from `data` yields an all-None
    output column rather than raising.
    """
    out = pd.DataFrame(index=data.index)
    for out_col, (src_col, kind) in field_map.items():
        out[out_col] = _CONVERTERS[kind](_col(data, src_col))
    return out


def _parse_timestamp(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce")


def _split_name(name: str | None) -> tuple[str | None, str | None]:
    """Split a "First Last" (or "First Middle Last") display name on the
    first whitespace run: first token -> first name, remainder -> last name.
    PROVISIONAL heuristic (see module docstring) -- SessionExport has no
    separate first/last columns, only the combined `UserName`.
    """
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return None, None
    parts = name.split(None, 1)
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], parts[1]


# ---------------------------------------------------------------------------
# PRACTICE_SESSIONS
# ---------------------------------------------------------------------------

# Every entry here has an explicit HitTrax source-code comment in
# transformed_schema.sql (e.g. "avg_exit_velocity ... -- AEV (m/s -> mph)").
# {clean_column: (SessionExport_column, converter_key)}
SESSION_FIELD_MAP: dict[str, tuple[str, str]] = {
    "hittrax_session_id": ("Id", "int"),
    "session_type": ("Type", "int"),
    "session_tag": ("Tag", "str"),
    "game_type": ("GT", "int"),
    "skill_level": ("SL", "int"),
    "avg_exit_velocity": ("AEV", "mph"),
    "max_exit_velocity": ("MEV", "mph"),
    "avg_distance": ("AD", "ft"),
    "max_distance": ("MD", "ft"),
    "avg_ground_distance": ("AGD", "ft"),
    "max_ground_distance": ("MGD", "ft"),
    "avg_launch_angle": ("AElv", "num"),
    "avg_pitch_velocity": ("APV", "mph"),
    "max_pitch_velocity": ("MPV", "mph"),
    "avg_barrel_velocity": ("ABRV", "mph"),
    "max_barrel_velocity": ("MBRV", "mph"),
    "ground_ball_pct": ("GBP", "num"),
    "fly_ball_pct": ("FBP", "num"),
    "line_drive_pct": ("LDP", "num"),
    "left_infield_pct": ("LIP", "num"),
    "right_infield_pct": ("RIP", "num"),
    "center_infield_pct": ("CIP", "num"),
    "left_outfield_pct": ("LOP", "num"),
    "right_outfield_pct": ("ROP", "num"),
    "center_outfield_pct": ("COP", "num"),
    "pitch_count": ("PC", "int"),
    "at_bats": ("AB", "int"),
    "hit_count": ("HC", "int"),
    "singles": ("Sing", "int"),
    "doubles": ("Doub", "int"),
    "triples": ("Trip", "int"),
    "home_runs": ("Home", "int"),
    "fouls": ("Foul", "int"),
    "strikes": ("Strk", "int"),
    "balls": ("Ball", "int"),
    "rbi": ("RBI", "int"),
    "batting_avg": ("AVG", "num"),
    "slugging_pct": ("SLG", "num"),
    "score": ("SCR", "int"),
    "hard_hit_count": ("HHC", "int"),
    "hard_hit_velocity": ("HHV", "mph"),
    "strike_zone_top": ("SZT", "ft"),
    "strike_zone_bottom": ("SZB", "ft"),
    "strike_zone_width": ("SZW", "ft"),
    "zone_avg_1": ("AHZ1", "num"),
    "zone_avg_2": ("AHZ2", "num"),
    "zone_avg_3": ("AHZ3", "num"),
    "zone_avg_4": ("AHZ4", "num"),
    "zone_avg_5": ("AHZ5", "num"),
    "zone_avg_6": ("AHZ6", "num"),
    "zone_avg_7": ("AHZ7", "num"),
    "zone_avg_8": ("AHZ8", "num"),
    "zone_avg_9": ("AHZ9", "num"),
    "zone_avg_10": ("AHZ10", "num"),
    "zone_avg_11": ("AHZ11", "num"),
    "zone_avg_12": ("AHZ12", "num"),
    "zone_avg_13": ("AHZ13", "num"),
    "pelotero_drill_id": ("PeloteroDrillId", "str"),
    "pelotero_block_id": ("PeloteroBlockId", "str"),
    "game_uuid": ("GameUuid", "str"),
    "event_uuid": ("EventUuid", "str"),
}

# Columns produced by transform_sessions that are NOT in SESSION_FIELD_MAP
# (either derived, e.g. session_date/session_timestamp from TS, PROVISIONAL
# player-identity inferences, or left permanently NULL -- see docstring).
_SESSION_EXTRA_COLS = [
    "session_date", "session_timestamp", "player_id", "player_uuid",
    "user_name", "first_name", "last_name", "team_name", "practice_type",
    "duration_minutes", "total_plays", "source_file",
]


def transform_sessions(raw_df: pd.DataFrame) -> pd.DataFrame:
    """SessionExport raw rows (``{source_file, payload}``, payload = one
    HitTrax SessionExport row as a JSON string) -> `PRACTICE_SESSIONS`
    columns.

    Every column in `SESSION_FIELD_MAP` follows its `transformed_schema.sql`
    source-code + unit-conversion comment exactly (e.g. `AEV` m/s -> mph via
    `mps_to_mph`). A handful of columns have no HitTrax-source comment in the
    schema and are filled via a documented PROVISIONAL inference:

    - ``session_date``/``session_timestamp`` <- `TS` (the full HitTrax
      session datetime string); `session_date` is `TS`'s date part. (`St` is
      NOT used -- it's a small integer in every fixture row, not a
      timestamp, despite the brief's "St or TS" phrasing; `TS` is the only
      field that actually parses as a datetime.)
    - ``player_id`` <- `UsId` (int), ``player_uuid`` <- `UserUuid` (the
      full-UUID-format field; `UsUId` is a separate short numeric id, not a
      UUID, despite the similar name).
    - ``user_name`` <- `UserName`; ``first_name``/``last_name`` <- splitting
      `UserName` on the first whitespace run (SessionExport has no separate
      first/last columns).
    - ``team_name``/``practice_type``/``duration_minutes`` have no
      corresponding SessionExport field at all and are left NULL.
    - ``total_plays`` is left NULL here (schema DEFAULT 0) -- `transform()`
      fills it in after plays are linked to sessions via an UPDATE
      (COUNT(*) of linked `PRACTICE_PLAYS` rows per session_id).

    Never touches a DB; missing/blank source cells become `None` (never 0),
    per Task 1's `safe_numeric`/`mps_to_mph`/`meters_to_feet`.

    `PRACTICE_SESSIONS.session_date` is `NOT NULL` in the schema, but `TS`
    is occasionally blank/unparseable in real exports (`pd.to_datetime` with
    `errors="coerce"` yields `NaT` -> `None` for those). Rows whose derived
    `session_date` is null are dropped here (before the caller ever builds
    an insert dict) rather than left to fail the DB constraint -- they also
    can't be keyed or joined against `PRACTICE_PLAYS` without a date.
    """
    data = _payload_frame(raw_df)
    if data.empty:
        return pd.DataFrame(columns=list(SESSION_FIELD_MAP) + _SESSION_EXTRA_COLS)

    out = _apply_field_map(data, SESSION_FIELD_MAP)

    ts = _parse_timestamp(_col(data, "TS"))
    out["session_timestamp"] = ts
    out["session_date"] = ts.dt.date

    out["player_id"] = _CONVERTERS["int"](_col(data, "UsId"))
    out["player_uuid"] = _CONVERTERS["str"](_col(data, "UserUuid"))
    user_name = _CONVERTERS["str"](_col(data, "UserName"))
    out["user_name"] = user_name
    names = user_name.apply(_split_name)
    out["first_name"] = names.apply(lambda t: t[0])
    out["last_name"] = names.apply(lambda t: t[1])

    out["team_name"] = None
    out["practice_type"] = None
    out["duration_minutes"] = None
    out["total_plays"] = None

    out["source_file"] = raw_df["source_file"].reset_index(drop=True)

    out = out.reset_index(drop=True)
    # session_date is NOT NULL downstream: a blank/unparseable TS can't be
    # keyed or joined anyway, so drop it here rather than fail the whole
    # atomic rebuild on one bad row.
    out = out[out["session_date"].notna()].reset_index(drop=True)
    return out


# ---------------------------------------------------------------------------
# PRACTICE_PLAYS
# ---------------------------------------------------------------------------

# {clean_column: (PlaysExport_column, converter_key)} -- every entry has an
# explicit HitTrax source-code comment in transformed_schema.sql.
PLAYS_FIELD_MAP: dict[str, tuple[str, str]] = {
    "play_id": ("Id", "int"),
    "hand": ("Hand", "int"),
    "exit_velocity": ("Velo", "mph"),
    "launch_angle": ("Elv", "num"),
    "distance_feet": ("Dist", "ft"),
    "ground_distance": ("GD", "ft"),
    "horizontal_angle": ("HorzAngle", "num"),
    "hang_time_ms": ("Ms", "int"),
    "exit_velo_x": ("EBV1", "mph"),
    "exit_velo_y": ("EBV2", "mph"),
    "exit_velo_z": ("EBV3", "mph"),
    "hit_type": ("HT", "int"),
    "result": ("Res", "int"),
    "pitch_type": ("PT", "int"),
    "zone_section": ("QD", "int"),
    "fielder": ("Fld", "int"),
    "pitch_location_x": ("PP1", "ft"),
    "pitch_location_y": ("PP2", "ft"),
    "pitch_location_z": ("PP3", "ft"),
    "pitch_velocity": ("RadarVelo", "mph"),
    "pitch_angle": ("PitchAngle", "num"),
    "pitch_break_h": ("PBH", "num"),   # already inches per schema comment -- no conversion
    "pitch_break_v": ("PBV", "num"),   # already inches per schema comment -- no conversion
    "bat_id": ("BatId", "int"),
    "bat_uuid": ("BatUId", "str"),
    "points": ("Points", "int"),
    "result_runs": ("ResultRuns", "int"),
    "master_id": ("MasterID", "str"),
    "uuid": ("Uuid", "str"),
}

_PLAYS_EXTRA_COLS = [
    "player_id", "player_name", "player_uuid", "first_name", "last_name",
    "user_id", "user_uuid", "play_timestamp", "source_file", "ingested_at",
    "session_id",
]


def transform_plays(raw_df: pd.DataFrame, sessions_with_ids: pd.DataFrame) -> pd.DataFrame:
    """PlaysExport raw rows -> `PRACTICE_PLAYS` columns, with `session_id`
    attached via a left merge on `(session_date, player_id)`.

    Every column in `PLAYS_FIELD_MAP` follows its `transformed_schema.sql`
    source-code + unit-conversion comment exactly (e.g. `Velo` m/s -> mph,
    `Dist` meters -> feet). Columns with no HitTrax-source comment in the
    schema are filled via a documented PROVISIONAL inference:

    - ``player_id`` <- `UsId`, ``player_uuid`` <- `UsUuid` -- same "Us"
      (User/batter) field family as SessionExport's `UsId`/`UserUuid`, so
      this is the consistent join key against `PRACTICE_SESSIONS.player_id`.
    - ``user_id`` <- `OId`, ``user_uuid`` <- `OUId` -- PlaysExport's other
      id pair ("Owner"?), kept distinct from player_id/player_uuid per the
      schema's separate `user_id`/`user_uuid` columns. In every sample row
      these are sentinel `-1`/`0` ("none"), consistent with the `-1=none`
      convention used elsewhere in this schema (e.g. `BatId`) -- stored as-is,
      not coerced to NULL, since the schema gives no override rule for them.
    - ``player_name``/``first_name``/``last_name`` have no PlaysExport field
      at all (only ids/uuids) and are left NULL; name info is resolved at read
      time by joining `PRACTICE_SESSIONS`.
    - ``play_timestamp`` <- `TS` (parsed datetime); the play's `session_date`
      (for the merge key only, not a `PRACTICE_PLAYS` column) is `TS`'s date
      part, per pipeline-architecture.md's "Session-to-Play Mapping Logic".

    `sessions_with_ids` must have `session_id`/`session_date`/`player_id`
    columns (as returned by re-querying `PRACTICE_SESSIONS` after it's
    loaded); it is deduped to one row per `(session_date, player_id)`
    (`keep='first'`) before the merge, matching the reference's dedup step,
    so a play never fans out into duplicate rows when multiple sessions
    share a date+player. Plays with no matching session get `session_id`
    NaN/None -- never raises, matching the reference's documented ~96%
    (not 100%) mapping success rate.
    """
    data = _payload_frame(raw_df)
    if data.empty:
        return pd.DataFrame(columns=list(PLAYS_FIELD_MAP) + _PLAYS_EXTRA_COLS)

    out = _apply_field_map(data, PLAYS_FIELD_MAP)

    ts = _parse_timestamp(_col(data, "TS"))
    out["play_timestamp"] = ts

    out["player_id"] = _CONVERTERS["int"](_col(data, "UsId"))
    out["player_uuid"] = _CONVERTERS["str"](_col(data, "UsUuid"))
    out["player_name"] = None
    out["first_name"] = None
    out["last_name"] = None
    out["user_id"] = _CONVERTERS["int"](_col(data, "OId"))
    out["user_uuid"] = _CONVERTERS["str"](_col(data, "OUId"))

    out["source_file"] = raw_df["source_file"].reset_index(drop=True)
    if "ingested_at_utc" in raw_df.columns:
        out["ingested_at"] = raw_df["ingested_at_utc"].reset_index(drop=True)
    else:
        out["ingested_at"] = None

    # merge key only -- not a PRACTICE_PLAYS column, dropped after the merge
    out["session_date"] = ts.dt.date

    sessions = (
        sessions_with_ids[["session_id", "session_date", "player_id"]]
        .drop_duplicates(subset=["session_date", "player_id"], keep="first")
    )
    merged = out.merge(sessions, on=["session_date", "player_id"], how="left")
    merged = merged.drop(columns=["session_date"])

    return merged.reset_index(drop=True)


def _load_raw(engine, prefix: str) -> pd.DataFrame:
    """SELECT `source_file, ingested_at_utc, payload` from `RAW_PRACTICE_CSV`
    for every row whose `source_file` starts with `prefix` (e.g.
    'SessionExport' / 'PlaysExport'). DB-only (never called by the pure
    transforms/tests).
    """
    sql = text(
        "SELECT source_file, ingested_at_utc, payload FROM RAW_PRACTICE_CSV "
        "WHERE source_file LIKE :pattern"
    )
    with engine.connect() as conn:
        rows = conn.execute(sql, {"pattern": f"{prefix}%"}).mappings().all()
    return pd.DataFrame([dict(r) for r in rows], columns=["source_file", "ingested_at_utc", "payload"])


def _rows(df: pd.DataFrame) -> list[dict]:
    """DataFrame -> list of insert-ready dicts, with every NaN/NaT/None cell
    normalized to `None` (MySQL/pymysql params must never see NaN/NaT)."""
    if df.empty:
        return []
    clean = df.astype(object).where(df.notna(), None)
    return clean.to_dict(orient="records")


def _insert_rows(conn, table: str, rows: list[dict], chunksize: int = 500) -> None:
    """Parameterized chunked INSERT of `rows` into `table` using the given
    (already-open, already-in-a-transaction) `conn` -- never opens its own
    transaction, unlike `common.chunked_insert`, so it can participate in
    `transform()`'s single enclosing transaction.
    """
    if not rows:
        return
    cols = list(rows[0].keys())
    col_list = ", ".join(cols)
    placeholders = ", ".join(f":{c}" for c in cols)
    sql = text(f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})")
    for start in range(0, len(rows), chunksize):
        conn.execute(sql, rows[start:start + chunksize])


def transform(engine, *, dry_run: bool = True) -> dict:
    """Rebuild `PRACTICE_SESSIONS` and `PRACTICE_PLAYS` from `RAW_PRACTICE_CSV`.

    Reads every SessionExport/PlaysExport row currently in
    `RAW_PRACTICE_CSV`, builds the two clean tables with
    `transform_sessions`/`transform_plays`, and -- inside ONE transaction --
    `SET FOREIGN_KEY_CHECKS=0`, DELETEs all rows from both tables, loads
    sessions, re-queries `PRACTICE_SESSIONS` for its auto-generated
    `session_id`s, loads plays (with `session_id` attached via the merge),
    fills in each session's `total_plays` from its linked plays, then
    re-enables FK checks. This is the ONLY destructive operation this module
    performs --
    safe because the raw layer is immutable/append-only and complete, so a
    full rebuild is always reproducible.

    Deliberately `DELETE FROM`, not `TRUNCATE TABLE`: MySQL's `TRUNCATE` is
    DDL and causes an implicit commit, so it is NOT rollback-able -- if any
    later statement in this same block failed after a `TRUNCATE`, the tables
    would be left permanently empty while everything else rolled back,
    breaking the "atomic rebuild" guarantee this function exists to
    provide. `DELETE` is ordinary DML and rolls back cleanly with the rest
    of the transaction on any failure. These tables are small (~18k plays /
    ~2.2k sessions), so `DELETE`'s lack of `TRUNCATE`'s fast-path is a
    non-issue.

    `dry_run=True` (default) computes and returns the row counts WITHOUT
    writing anything: `session_id`s for the play-merge preview are simulated
    with a throwaway 0..n-1 index (the DB is never touched), so the returned
    counts are still an accurate preview of what a real run would produce.

    `SET FOREIGN_KEY_CHECKS` is a per-connection session variable, NOT
    transactional DML -- a `ROLLBACK` does not undo it. If any statement in
    the rebuild raises, this function still re-enables FK checks on the same
    (pooled) connection in a `finally` before re-raising, so a failed
    rebuild can never leave a connection checked back into the pool with FK
    checks permanently off for whatever unrelated query reuses it next.

    Returns ``{"sessions": n, "plays": n, "players": n}``.
    """
    raw_sessions = _load_raw(engine, "SessionExport")
    raw_plays = _load_raw(engine, "PlaysExport")

    sessions_df = transform_sessions(raw_sessions)

    if dry_run:
        preview_sessions = sessions_df.reset_index(drop=True).copy()
        preview_sessions["session_id"] = preview_sessions.index
        plays_df = transform_plays(
            raw_plays, preview_sessions[["session_id", "session_date", "player_id"]]
        )
        player_ids = set(sessions_df["player_id"].dropna()) | set(plays_df["player_id"].dropna())
        return {
            "sessions": len(sessions_df),
            "plays": len(plays_df),
            "players": len(player_ids),
        }

    # De-dupe against PRACTICE_SESSIONS' UNIQUE (session_date, player_id,
    # hittrax_session_id) key -- raw exports are cumulative, so the same
    # session can legitimately appear in more than one SessionExport file.
    sessions_df = sessions_df.drop_duplicates(
        subset=["session_date", "player_id", "hittrax_session_id"], keep="first"
    )

    conn = engine.connect()
    try:
        trans = conn.begin()
        try:
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            # DELETE, not TRUNCATE: TRUNCATE is DDL in MySQL and causes an
            # implicit commit (not rollback-able), which would defeat this
            # transaction's all-or-nothing guarantee -- a failure in a later
            # statement (e.g. the play insert, a dropped connection, a
            # deadlock) would leave these tables permanently
            # empty instead of rolling back to their pre-transform state.
            # DELETE is transactional DML in InnoDB, so the whole rebuild is
            # genuinely atomic. Child-first order kept for clarity even though
            # FK checks are off (order doesn't matter functionally here).
            conn.execute(text("DELETE FROM PRACTICE_PLAYS"))
            conn.execute(text("DELETE FROM PRACTICE_SESSIONS"))

            session_rows = _rows(sessions_df)
            _insert_rows(conn, "PRACTICE_SESSIONS", session_rows)

            sessions_with_ids = pd.read_sql(
                text("SELECT session_id, session_date, player_id FROM PRACTICE_SESSIONS"), conn
            )
            plays_df = transform_plays(raw_plays, sessions_with_ids)
            play_rows = _rows(plays_df)
            _insert_rows(conn, "PRACTICE_PLAYS", play_rows)

            # total_plays has no direct HitTrax source column -- computed here
            # from the just-linked plays.
            conn.execute(text(
                "UPDATE PRACTICE_SESSIONS ps "
                "LEFT JOIN ("
                "  SELECT session_id, COUNT(*) AS n FROM PRACTICE_PLAYS "
                "  WHERE session_id IS NOT NULL GROUP BY session_id"
                ") c ON c.session_id = ps.session_id "
                "SET ps.total_plays = COALESCE(c.n, 0)"
            ))

            conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))

            # Counted from what we just loaded, not from `player_stats_summary`.
            # That table belongs to the separate Streamlit practice-analytics app,
            # whose scheduled ETL drops and rebuilds it; PAW neither reads it
            # (app.data.practice.load_player_stats aggregates PRACTICE_SESSIONS +
            # PRACTICE_PLAYS directly) nor should write it. Mirrors the dry-run
            # branch's player count so both paths report the same thing.
            players = len(
                set(sessions_df["player_id"].dropna()) | set(plays_df["player_id"].dropna())
            )

            trans.commit()
        except Exception:
            trans.rollback()
            raise
    finally:
        # Belt-and-suspenders: re-enable FK checks on THIS connection no
        # matter what happened above. `SET FOREIGN_KEY_CHECKS` is a session
        # variable, not transactional DML, so `trans.rollback()` above does
        # NOT undo it -- without this, a rebuild that raises after the
        # `SET ... = 0` would check the connection back into the pool with
        # FK checks permanently off, silently poisoning whatever unrelated
        # query reuses it next.
        try:
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
        except Exception:
            pass
        conn.close()

    return {
        "sessions": len(session_rows),
        "plays": len(play_rows),
        "players": players,
    }
