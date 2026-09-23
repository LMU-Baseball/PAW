"""app.data.bullpen_video: bullpen_video_clips storage layer (live DB, safe
fake play_ids) -- video bytes stored as a DB BLOB, see the module's own
docstring for why."""
from app.data import bullpen_video as BV

TEST_PLAY_1 = "test-play-aaaa1111-0000-0000-0000-000000000001"
TEST_PLAY_2 = "test-play-aaaa1111-0000-0000-0000-000000000002"


def _cleanup(*play_ids):
    from app.db import get_engine
    from sqlalchemy import text
    with get_engine().begin() as c:
        for pid in play_ids:
            c.execute(text(f"DELETE FROM {BV.TABLE} WHERE play_id=:p"), {"p": pid})


def test_ensure_table_idempotent():
    BV.ensure_table()
    BV.ensure_table()  # second call is a no-op, not an error


def test_add_clip_then_get_clip_roundtrip():
    try:
        BV.add_clip(TEST_PLAY_1, "sess-1", b"fake-video-bytes", mimetype="video/mp4",
                   duration_sec=0.8, width=1280, height=1008, framerate=240)
        got = BV.get_clip(TEST_PLAY_1)
        assert got is not None
        assert got["session_id"] == "sess-1"
        assert got["data"] == b"fake-video-bytes"
        assert got["mimetype"] == "video/mp4"
        assert got["size_bytes"] == len(b"fake-video-bytes")
        assert float(got["duration_sec"]) == 0.8
        assert int(got["framerate"]) == 240
    finally:
        _cleanup(TEST_PLAY_1)


def test_add_clip_upserts_on_replay():
    try:
        BV.add_clip(TEST_PLAY_1, "sess-1", b"old-bytes")
        BV.add_clip(TEST_PLAY_1, "sess-1", b"new-bytes")  # same play_id -> update, not dup
        got = BV.get_clip(TEST_PLAY_1)
        assert got["data"] == b"new-bytes"
    finally:
        _cleanup(TEST_PLAY_1)


def test_get_clip_missing_returns_none():
    assert BV.get_clip("no-such-play-id-at-all") is None


def test_existing_play_ids_finds_only_downloaded_ones():
    try:
        BV.add_clip(TEST_PLAY_1, "sess-1", b"clip1-bytes")
        found = BV.existing_play_ids([TEST_PLAY_1, TEST_PLAY_2])
        assert found == {TEST_PLAY_1}
    finally:
        _cleanup(TEST_PLAY_1, TEST_PLAY_2)


def test_existing_play_ids_empty_input_no_query():
    assert BV.existing_play_ids([]) == set()


def test_clip_meta_excludes_data_but_keeps_other_fields():
    try:
        BV.add_clip(TEST_PLAY_1, "sess-1", b"some-bytes", mimetype="video/mp4",
                   duration_sec=0.8, width=1280, height=1008, framerate=240)
        meta = BV.clip_meta(TEST_PLAY_1)
        assert meta is not None
        assert "data" not in meta
        assert meta["size_bytes"] == len(b"some-bytes")
        assert meta["mimetype"] == "video/mp4"
    finally:
        _cleanup(TEST_PLAY_1)


def test_clip_meta_missing_returns_none():
    assert BV.clip_meta("no-such-play-id-at-all") is None


# A real, known BULLPEN row (Moreno, Matthew's 2026-09-17 session, pitch
# 81 -- see the 2026-09-22/23 Edgertronic video work) -- read-only, never
# written to, same "known real fixture" idiom as other live-DB tests in
# this repo (e.g. test_bullpen_data.py's "Geis").
_KNOWN_REAL_PLAY_ID = "a8fd0bf2-6830-4de0-af64-32a622f50c87"


def test_pitch_row_by_play_id_known_real_row():
    row = BV.pitch_row_by_play_id(_KNOWN_REAL_PLAY_ID)
    assert row is not None
    assert row["pitcher_id"] == 1000170776
    assert row["date"] == "2026-09-17"
    assert row["pitch_type"] == "Fastball"
    assert row["play_id"] == _KNOWN_REAL_PLAY_ID


def test_pitch_row_by_play_id_missing_returns_none():
    assert BV.pitch_row_by_play_id("no-such-play-id-at-all") is None
