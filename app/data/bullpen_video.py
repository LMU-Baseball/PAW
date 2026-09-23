"""Bullpen (practice) per-pitch Edgertronic video: DB-BLOB-backed index.

Mirrors `app.data.video`'s `video_clips` role (one row per pitch pointing at
a playable clip) but keyed on `BULLPEN.PlayID` instead of `GAMES.PitchUID`,
and storing the video BYTES directly in the row (`data LONGBLOB`) -- same
idiom as `app.data.splash_report`'s `splash_videos` table.

Why a DB BLOB and not local disk or S3 (2026-09-22, Brad): this loader is
meant to run on the same GitHub Actions `pipeline-cron` schedule as the
existing games/bullpen/HitTrax loaders -- a fresh, disk-less runner VM every
run. Local disk would vanish the moment that job finishes, and S3 needs a
new AWS bucket + IAM credentials Brad hasn't set up. The database, by
contrast, is reachable from anywhere (a GitHub Actions runner or the
Lightsail server, no difference) and already has credentials wired into that
exact workflow (`MYSQL_*` secrets) -- so a BLOB column sidesteps needing any
new infrastructure today. Trade-off to watch: this grows storage inside RDS
rather than a separate disk; revisit (S3, most likely) if clip volume over a
season turns out to be a real size/cost concern -- same "for now" framing
`splash_videos` already carries for the same reason.

Served through a login-gated Flask route (`/bullpen-video/<play_id>`, see
app/main/routes.py), same access-control idiom as `/splash-video/<id>` --
not under `/static/`, which is fetchable without login.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import text

from app.data import bullpen as B
from app.db import get_engine, query_df

TABLE = "bullpen_video_clips"

_DDL = f"""
    CREATE TABLE IF NOT EXISTS {TABLE} (
        play_id       VARCHAR(64) NOT NULL,
        session_id    VARCHAR(64) NOT NULL,
        mimetype      VARCHAR(64),
        size_bytes    INT,
        data          LONGBLOB,
        duration_sec  FLOAT,
        width         INT,
        height        INT,
        framerate     INT,
        downloaded_at DATETIME,
        PRIMARY KEY (play_id)
    )"""


def ensure_table(engine=None) -> None:
    """Idempotently create bullpen_video_clips."""
    engine = engine or get_engine()
    with engine.begin() as conn:
        conn.execute(text(_DDL))


def existing_play_ids(play_ids: list[str]) -> set[str]:
    """Which of `play_ids` already have a downloaded clip -- the loader's
    dedup check, mirroring `app.ingest.common.existing_keys`'s role for the
    CSV loaders (kept separate rather than reused directly since this reads
    by an explicit id LIST, not every row in the table -- a season's worth
    of clips shouldn't all be pulled into memory just to check one session)."""
    ensure_table()
    if not play_ids:
        return set()
    # Explicit :p0, :p1, ... placeholders (not a single tuple-valued bind
    # param) -- matches app.data.pitching_caps._in_clause's idiom; plain
    # SQLAlchemy `text()` doesn't auto-expand a tuple into an IN list.
    placeholders = ", ".join(f":p{i}" for i in range(len(play_ids)))
    params = {f"p{i}": pid for i, pid in enumerate(play_ids)}
    df = query_df(
        f"SELECT play_id FROM {TABLE} WHERE play_id IN ({placeholders})", params)
    return set(df["play_id"]) if not df.empty else set()


def add_clip(play_id: str, session_id: str, data: bytes, *, mimetype: str = "video/mp4",
            duration_sec=None, width=None, height=None, framerate=None) -> None:
    """Insert one downloaded clip's bytes + index row. `ON DUPLICATE KEY
    UPDATE` (not INSERT IGNORE) so re-running the loader for a play whose
    clip changed (rare, but TrackMan does expose `updatedAt` on these
    records) overwrites it, not just silently no-ops."""
    ensure_table()
    sql = text(f"""
        INSERT INTO {TABLE}
            (play_id, session_id, mimetype, size_bytes, data, duration_sec,
             width, height, framerate, downloaded_at)
        VALUES
            (:play_id, :session_id, :mimetype, :size_bytes, :data, :duration_sec,
             :width, :height, :framerate, :downloaded_at)
        ON DUPLICATE KEY UPDATE session_id = VALUES(session_id),
            mimetype = VALUES(mimetype), size_bytes = VALUES(size_bytes),
            data = VALUES(data), duration_sec = VALUES(duration_sec),
            width = VALUES(width), height = VALUES(height),
            framerate = VALUES(framerate), downloaded_at = VALUES(downloaded_at)
    """)
    with get_engine().begin() as conn:
        conn.execute(sql, {
            "play_id": play_id, "session_id": session_id, "mimetype": mimetype,
            "size_bytes": len(data), "data": data, "duration_sec": duration_sec,
            "width": width, "height": height, "framerate": framerate,
            "downloaded_at": datetime.now(timezone.utc),
        })


def get_clip(play_id: str) -> dict | None:
    """{"data" (raw bytes), "mimetype", ...} for one play's clip, or None if
    it hasn't been downloaded (or doesn't have Edgertronic video). Used by
    the streaming route and by the (future) video-tab data layer."""
    ensure_table()
    df = query_df(f"SELECT * FROM {TABLE} WHERE play_id = :p", {"p": play_id})
    return None if df.empty else df.iloc[0].to_dict()


def clip_meta(play_id: str) -> dict | None:
    """Same as `get_clip` but never selects `data` -- for listing/UI use
    where pulling every clip's full bytes just to show a table row would be
    wasteful (mirrors `app.data.splash_report.list_videos`'s reasoning)."""
    ensure_table()
    df = query_df(
        f"SELECT play_id, session_id, mimetype, size_bytes, duration_sec, "
        f"width, height, framerate, downloaded_at FROM {TABLE} WHERE play_id = :p",
        {"p": play_id})
    return None if df.empty else df.iloc[0].to_dict()


def session_pitch_video_df(pitcher_id: int, date) -> pd.DataFrame:
    """One row per pitch in a bullpen session for the Video tab: pitch #,
    type, velo, ball/strike (same zone + edge-buffer test as
    `app.data.bullpen.strike_pct`, applied per pitch instead of aggregated),
    9-pocket zone location, horizontal/vertical break, plus `play_id`/
    `has_video` so the table can flag which rows have a downloaded
    Edgertronic clip to play. Queried directly from BULLPEN (not
    `bullpen.session_pitches`, whose `_COLMAP` doesn't expose PlayID)."""
    df = query_df(
        """
        SELECT PitchNo AS pitch_no, PlayID AS play_id,
               TaggedPitchType AS pitch_type, RelSpeed AS velo,
               PlateLocSide AS plate_loc_side, PlateLocHeight AS plate_loc_height,
               HorzBreak AS horz_break, VertBreak AS vert_break
          FROM BULLPEN
         WHERE PitcherId = :pid AND `Date` = :d
         ORDER BY PitchNo
        """,
        {"pid": int(pitcher_id), "d": str(date)},
    )
    if df.empty:
        return df

    inx = df["plate_loc_side"].between(B._SZ["x0"] - B._EDGE, B._SZ["x1"] + B._EDGE)
    iny = df["plate_loc_height"].between(B._SZ["y0"] - B._EDGE, B._SZ["y1"] + B._EDGE)
    df["result"] = (inx & iny).map({True: "Strike", False: "Ball"})
    unlocated = df["plate_loc_side"].isna() | df["plate_loc_height"].isna()
    df.loc[unlocated, "result"] = "—"
    df["pocket"] = df.apply(
        lambda r: B.pocket_label(r["plate_loc_side"], r["plate_loc_height"]) or "—", axis=1)

    found = existing_play_ids([p for p in df["play_id"] if pd.notna(p)])
    df["has_video"] = df["play_id"].isin(found)
    return df


def pitch_row_by_play_id(play_id: str) -> dict | None:
    """One pitch's PitcherId/Date/PitchNo/type/velo/break/location for a
    known PlayID -- the download route's entry point (2026-09-23, Brad:
    players want to download their best pitches with a pitch-data overlay
    to share with recruiters): it only has `play_id` from the URL, so this
    is how it finds which session (pitcher + date) that play belongs to,
    to then pull the rest of that session via `session_pitch_video_df` for
    the overlay's movement chart. None if PlayID isn't in BULLPEN at all."""
    df = query_df(
        """
        SELECT PitcherId AS pitcher_id, `Date` AS date, PitchNo AS pitch_no,
               TaggedPitchType AS pitch_type, RelSpeed AS velo,
               PlateLocSide AS plate_loc_side, PlateLocHeight AS plate_loc_height,
               HorzBreak AS horz_break, VertBreak AS vert_break
          FROM BULLPEN WHERE PlayID = :p
        """,
        {"p": play_id})
    if df.empty:
        return None
    row = df.iloc[0].to_dict()
    row["date"] = str(row["date"])
    row["pitcher_id"] = int(row["pitcher_id"])
    row["play_id"] = play_id
    return row
