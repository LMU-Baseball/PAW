"""HitTrax raw ELT: FTPS -> `raw_practice_csv` staging table, PLUS the
transform step from that raw layer into the clean analytics tables
(`practice_sessions` / `practice_plays` / `player_stats_summary`).

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
    """Convert every row of `df` into a `raw_practice_csv` insert-ready dict:
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


# ===========================================================================
# TRANSFORM: raw_practice_csv -> practice_sessions / practice_plays /
# player_stats_summary
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
    if name is None:
        return None, None
    parts = name.split(None, 1)
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], parts[1]


# ---------------------------------------------------------------------------
# practice_sessions
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
    HitTrax SessionExport row as a JSON string) -> `practice_sessions`
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
      (COUNT(*) of linked `practice_plays` rows per session_id).

    Never touches a DB; missing/blank source cells become `None` (never 0),
    per Task 1's `safe_numeric`/`mps_to_mph`/`meters_to_feet`.
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

    return out.reset_index(drop=True)


# ---------------------------------------------------------------------------
# practice_plays
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
    """PlaysExport raw rows -> `practice_plays` columns, with `session_id`
    attached via a left merge on `(session_date, player_id)`.

    Every column in `PLAYS_FIELD_MAP` follows its `transformed_schema.sql`
    source-code + unit-conversion comment exactly (e.g. `Velo` m/s -> mph,
    `Dist` meters -> feet). Columns with no HitTrax-source comment in the
    schema are filled via a documented PROVISIONAL inference:

    - ``player_id`` <- `UsId`, ``player_uuid`` <- `UsUuid` -- same "Us"
      (User/batter) field family as SessionExport's `UsId`/`UserUuid`, so
      this is the consistent join key against `practice_sessions.player_id`.
    - ``user_id`` <- `OId`, ``user_uuid`` <- `OUId` -- PlaysExport's other
      id pair ("Owner"?), kept distinct from player_id/player_uuid per the
      schema's separate `user_id`/`user_uuid` columns. In every sample row
      these are sentinel `-1`/`0` ("none"), consistent with the `-1=none`
      convention used elsewhere in this schema (e.g. `BatId`) -- stored as-is,
      not coerced to NULL, since the schema gives no override rule for them.
    - ``player_name``/``first_name``/``last_name`` have no PlaysExport field
      at all (only ids/uuids) and are left NULL; `player_stats_summary`
      later fills in name info from `practice_sessions`.
    - ``play_timestamp`` <- `TS` (parsed datetime); the play's `session_date`
      (for the merge key only, not a `practice_plays` column) is `TS`'s date
      part, per pipeline-architecture.md's "Session-to-Play Mapping Logic".

    `sessions_with_ids` must have `session_id`/`session_date`/`player_id`
    columns (as returned by re-querying `practice_sessions` after it's
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

    # merge key only -- not a practice_plays column, dropped after the merge
    out["session_date"] = ts.dt.date

    sessions = (
        sessions_with_ids[["session_id", "session_date", "player_id"]]
        .drop_duplicates(subset=["session_date", "player_id"], keep="first")
    )
    merged = out.merge(sessions, on=["session_date", "player_id"], how="left")
    merged = merged.drop(columns=["session_date"])

    return merged.reset_index(drop=True)


# ---------------------------------------------------------------------------
# player_stats_summary aggregation (transform()'s DB-only step)
# ---------------------------------------------------------------------------

# INSERT ... SELECT ... ON DUPLICATE KEY UPDATE per pipeline-architecture.md
# §2.3, extended to cover the full player_stats_summary schema (the
# reference's code sample is illustrative/truncated with "..."). Traditional
# batting totals (AB/hits/BA/SLG) come from practice_sessions (career
# per-session aggregates, per the schema's "career totals from sessions"
# comments); exit-velocity/distance/hit-type/swing-rate stats come from
# practice_plays. `NULLIF(..., 0)` denominators keep missing data as NULL
# rather than skewing rates to 0, per the "NULL Handling" data-quality rule.
_PLAYER_STATS_SQL = """
INSERT INTO player_stats_summary
    (player_id, player_name, player_uuid, first_name, last_name,
     total_plays, total_sessions, last_practice_date,
     avg_exit_velocity, max_exit_velocity,
     avg_distance, max_distance,
     avg_launch_angle,
     total_at_bats, total_hits, total_singles, total_doubles,
     total_triples, total_home_runs,
     career_batting_avg, career_slugging_pct,
     hard_hit_count, hard_hit_rate,
     fly_ball_rate, line_drive_rate,
     total_swings, swing_rate)
SELECT
    ap.player_id,
    ps.player_name,
    COALESCE(ps.player_uuid, pp.player_uuid) AS player_uuid,
    ps.first_name,
    ps.last_name,
    COALESCE(pp.total_plays, 0) AS total_plays,
    COALESCE(ps.total_sessions, 0) AS total_sessions,
    ps.last_practice_date,
    pp.avg_exit_velocity,
    pp.max_exit_velocity,
    pp.avg_distance,
    pp.max_distance,
    pp.avg_launch_angle,
    COALESCE(ps.total_at_bats, 0) AS total_at_bats,
    COALESCE(ps.total_hits, 0) AS total_hits,
    COALESCE(ps.total_singles, 0) AS total_singles,
    COALESCE(ps.total_doubles, 0) AS total_doubles,
    COALESCE(ps.total_triples, 0) AS total_triples,
    COALESCE(ps.total_home_runs, 0) AS total_home_runs,
    CASE WHEN ps.total_at_bats > 0 THEN ps.total_hits / ps.total_at_bats ELSE NULL END AS career_batting_avg,
    CASE WHEN ps.total_at_bats > 0
        THEN (ps.total_singles + 2 * ps.total_doubles + 3 * ps.total_triples + 4 * ps.total_home_runs) / ps.total_at_bats
        ELSE NULL END AS career_slugging_pct,
    COALESCE(ps.hard_hit_count, 0) AS hard_hit_count,
    pp.hard_hit_rate,
    pp.fly_ball_rate,
    pp.line_drive_rate,
    COALESCE(pp.total_swings, 0) AS total_swings,
    pp.swing_rate
FROM (
    SELECT player_id FROM practice_sessions WHERE player_id IS NOT NULL
    UNION
    SELECT player_id FROM practice_plays WHERE player_id IS NOT NULL
) ap
LEFT JOIN (
    SELECT
        player_id,
        MAX(user_name) AS player_name,
        MAX(player_uuid) AS player_uuid,
        MAX(first_name) AS first_name,
        MAX(last_name) AS last_name,
        COUNT(*) AS total_sessions,
        MAX(session_date) AS last_practice_date,
        SUM(at_bats) AS total_at_bats,
        SUM(singles) AS total_singles,
        SUM(doubles) AS total_doubles,
        SUM(triples) AS total_triples,
        SUM(home_runs) AS total_home_runs,
        SUM(COALESCE(singles, 0) + COALESCE(doubles, 0) + COALESCE(triples, 0) + COALESCE(home_runs, 0)) AS total_hits,
        SUM(hard_hit_count) AS hard_hit_count
    FROM practice_sessions
    WHERE player_id IS NOT NULL
    GROUP BY player_id
) ps ON ps.player_id = ap.player_id
LEFT JOIN (
    SELECT
        player_id,
        MAX(player_uuid) AS player_uuid,
        COUNT(*) AS total_plays,
        AVG(exit_velocity) AS avg_exit_velocity,
        MAX(exit_velocity) AS max_exit_velocity,
        AVG(distance_feet) AS avg_distance,
        MAX(distance_feet) AS max_distance,
        AVG(CASE WHEN launch_angle BETWEEN -10 AND 50 THEN launch_angle END) AS avg_launch_angle,
        SUM(CASE WHEN exit_velocity >= 95 THEN 1 ELSE 0 END) * 100.0
            / NULLIF(COUNT(exit_velocity), 0) AS hard_hit_rate,
        SUM(CASE WHEN hit_type = 3 THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(*), 0) AS fly_ball_rate,
        SUM(CASE WHEN hit_type = 2 THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(*), 0) AS line_drive_rate,
        SUM(CASE WHEN result IN (-5, -3, -8, -1, 0, 1, 2, 3, 4) THEN 1 ELSE 0 END) AS total_swings,
        SUM(CASE WHEN result IN (-5, -3, -8, -1, 0, 1, 2, 3, 4) THEN 1 ELSE 0 END) * 100.0
            / NULLIF(COUNT(*), 0) AS swing_rate
    FROM practice_plays
    WHERE player_id IS NOT NULL
    GROUP BY player_id
) pp ON pp.player_id = ap.player_id
ON DUPLICATE KEY UPDATE
    player_name = VALUES(player_name),
    player_uuid = VALUES(player_uuid),
    first_name = VALUES(first_name),
    last_name = VALUES(last_name),
    total_plays = VALUES(total_plays),
    total_sessions = VALUES(total_sessions),
    last_practice_date = VALUES(last_practice_date),
    avg_exit_velocity = VALUES(avg_exit_velocity),
    max_exit_velocity = VALUES(max_exit_velocity),
    avg_distance = VALUES(avg_distance),
    max_distance = VALUES(max_distance),
    avg_launch_angle = VALUES(avg_launch_angle),
    total_at_bats = VALUES(total_at_bats),
    total_hits = VALUES(total_hits),
    total_singles = VALUES(total_singles),
    total_doubles = VALUES(total_doubles),
    total_triples = VALUES(total_triples),
    total_home_runs = VALUES(total_home_runs),
    career_batting_avg = VALUES(career_batting_avg),
    career_slugging_pct = VALUES(career_slugging_pct),
    hard_hit_count = VALUES(hard_hit_count),
    hard_hit_rate = VALUES(hard_hit_rate),
    fly_ball_rate = VALUES(fly_ball_rate),
    line_drive_rate = VALUES(line_drive_rate),
    total_swings = VALUES(total_swings),
    swing_rate = VALUES(swing_rate)
"""


def _load_raw(engine, prefix: str) -> pd.DataFrame:
    """SELECT `source_file, ingested_at_utc, payload` from `raw_practice_csv`
    for every row whose `source_file` starts with `prefix` (e.g.
    'SessionExport' / 'PlaysExport'). DB-only (never called by the pure
    transforms/tests).
    """
    sql = text(
        "SELECT source_file, ingested_at_utc, payload FROM raw_practice_csv "
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
    """Rebuild `practice_sessions`, `practice_plays`, and
    `player_stats_summary` from `raw_practice_csv`.

    Reads every SessionExport/PlaysExport row currently in
    `raw_practice_csv`, builds the three clean tables with
    `transform_sessions`/`transform_plays`, and -- inside ONE transaction --
    `SET FOREIGN_KEY_CHECKS=0`, TRUNCATEs all three tables, loads sessions,
    re-queries `practice_sessions` for its auto-generated `session_id`s,
    loads plays (with `session_id` attached via the merge), fills in each
    session's `total_plays` from its linked plays, aggregates
    `player_stats_summary` via `_PLAYER_STATS_SQL`, then re-enables FK
    checks. This is the ONLY destructive operation this module performs --
    safe because the raw layer is immutable/append-only and complete, so a
    full rebuild is always reproducible.

    `dry_run=True` (default) computes and returns the row counts WITHOUT
    writing anything: `session_id`s for the play-merge preview are simulated
    with a throwaway 0..n-1 index (the DB is never touched), so the returned
    counts are still an accurate preview of what a real run would produce.

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

    # De-dupe against practice_sessions' UNIQUE (session_date, player_id,
    # hittrax_session_id) key -- raw exports are cumulative, so the same
    # session can legitimately appear in more than one SessionExport file.
    sessions_df = sessions_df.drop_duplicates(
        subset=["session_date", "player_id", "hittrax_session_id"], keep="first"
    )

    with engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        conn.execute(text("TRUNCATE TABLE practice_plays"))
        conn.execute(text("TRUNCATE TABLE practice_sessions"))
        conn.execute(text("TRUNCATE TABLE player_stats_summary"))

        session_rows = _rows(sessions_df)
        _insert_rows(conn, "practice_sessions", session_rows)

        sessions_with_ids = pd.read_sql(
            text("SELECT session_id, session_date, player_id FROM practice_sessions"), conn
        )
        plays_df = transform_plays(raw_plays, sessions_with_ids)
        play_rows = _rows(plays_df)
        _insert_rows(conn, "practice_plays", play_rows)

        # total_plays has no direct HitTrax source column -- computed here
        # from the just-linked plays.
        conn.execute(text(
            "UPDATE practice_sessions ps "
            "LEFT JOIN ("
            "  SELECT session_id, COUNT(*) AS n FROM practice_plays "
            "  WHERE session_id IS NOT NULL GROUP BY session_id"
            ") c ON c.session_id = ps.session_id "
            "SET ps.total_plays = COALESCE(c.n, 0)"
        ))

        conn.execute(text(_PLAYER_STATS_SQL))

        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))

        players = conn.execute(text("SELECT COUNT(*) FROM player_stats_summary")).scalar()

    return {
        "sessions": len(session_rows),
        "plays": len(play_rows),
        "players": players,
    }
