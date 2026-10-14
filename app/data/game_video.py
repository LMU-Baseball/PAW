"""Hand-cut SD-card game/scrimmage clips, stored as DB BLOBs keyed on
GAMES.PitchUID + angle.

The game Video tab's original source is `video_clips` (public S3 URLs from
last season's out-of-repo uploader). There are still no AWS credentials for
that bucket, so new clips use the same DB-BLOB idiom as
`app.data.bullpen_video.ANGLE_TABLE` and are streamed through the
login-gated `/game-video/<pitch_uid>` route. `app.data.video` merges both
sources, so a pitch can have angles from either one.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import text

from app.db import get_engine, query_df

TABLE = "game_video_angles"

_DDL = f"""
    CREATE TABLE IF NOT EXISTS {TABLE} (
        pitch_uid     VARCHAR(64) NOT NULL,
        angle         VARCHAR(32) NOT NULL,
        mimetype      VARCHAR(64),
        size_bytes    INT,
        data          LONGBLOB,
        duration_sec  FLOAT,
        width         INT,
        height        INT,
        source_file   VARCHAR(255),
        uploaded_at   DATETIME,
        PRIMARY KEY (pitch_uid, angle)
    )"""


def ensure_table(engine=None) -> None:
    engine = engine or get_engine()
    with engine.begin() as conn:
        conn.execute(text(_DDL))


def _angle_keys() -> set[str]:
    from app.data.video import ANGLES
    return {k for k, _ in ANGLES}


def clip_url(pitch_uid: str, angle: str) -> str:
    return f"/game-video/{pitch_uid}?angle={angle}"


def add_clip(pitch_uid: str, angle: str, data: bytes, *, mimetype: str = "video/mp4",
             duration_sec=None, width=None, height=None, source_file=None) -> None:
    """Insert (or replace) one angle's clip for a pitch."""
    if angle not in _angle_keys():
        raise ValueError(f"unknown angle {angle!r}")
    ensure_table()
    sql = text(f"""
        INSERT INTO {TABLE}
            (pitch_uid, angle, mimetype, size_bytes, data, duration_sec, width, height,
             source_file, uploaded_at)
        VALUES
            (:pitch_uid, :angle, :mimetype, :size_bytes, :data, :duration_sec, :width, :height,
             :source_file, :uploaded_at)
        ON DUPLICATE KEY UPDATE mimetype = VALUES(mimetype),
            size_bytes = VALUES(size_bytes), data = VALUES(data),
            duration_sec = VALUES(duration_sec), width = VALUES(width),
            height = VALUES(height), source_file = VALUES(source_file),
            uploaded_at = VALUES(uploaded_at)
    """)
    with get_engine().begin() as conn:
        conn.execute(sql, {
            "pitch_uid": pitch_uid, "angle": angle, "mimetype": mimetype,
            "size_bytes": len(data), "data": data, "duration_sec": duration_sec,
            "width": width, "height": height, "source_file": source_file,
            "uploaded_at": datetime.now(timezone.utc),
        })


def get_clip(pitch_uid: str, angle: str) -> dict | None:
    ensure_table()
    df = query_df(f"SELECT * FROM {TABLE} WHERE pitch_uid = :p AND angle = :a",
                  {"p": pitch_uid, "a": angle})
    return None if df.empty else df.iloc[0].to_dict()


def sizes_by_pitch_uid(pitch_uids: list[str]) -> dict[tuple[str, str], int]:
    """{(pitch_uid, angle): size_bytes} for clips already uploaded, never
    selecting the bytes -- the upload script's skip/verify check."""
    ensure_table()
    if not pitch_uids:
        return {}
    ph = ", ".join(f":p{i}" for i in range(len(pitch_uids)))
    df = query_df(f"SELECT pitch_uid, angle, size_bytes FROM {TABLE} WHERE pitch_uid IN ({ph})",
                  {f"p{i}": u for i, u in enumerate(pitch_uids)})
    return {(u, a): int(s) for u, a, s in df.itertuples(index=False)}
