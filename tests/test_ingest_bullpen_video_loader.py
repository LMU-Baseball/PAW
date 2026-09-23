"""Tests for app.ingest.bullpen_video.load_bullpen_video: pure orchestration
logic, no live network and no real DB writes -- `BV.*`/`TV.*` are
monkeypatched as module attributes (same idiom as tests/
test_ingest_bullpen_loader.py monkeypatching `bullpen.existing_keys`/
`chunked_insert`)."""
import subprocess

import pytest

from app.ingest import bullpen_video as loader
from app.ingest.bullpen_video import RemuxError, load_bullpen_video, remux_to_mp4


class _FakeSession:
    """Stand-in for trackman_video.Session: canned discovery/metadata/token
    responses keyed by sessionId."""

    def __init__(self, sessions, metadata_by_session, tokens_by_session=None,
                error_sessions=frozenset()):
        self._sessions = sessions
        self._metadata = metadata_by_session
        self._tokens = tokens_by_session or {}
        self._error_sessions = error_sessions

    def discover_practice_sessions(self, date_from, date_to, *, session_type="All"):
        return self._sessions

    def practice_video_metadata(self, session_id):
        if session_id in self._error_sessions:
            from app.ingest.trackman_video import TrackmanAPIError
            raise TrackmanAPIError(f"practice video metadata fetch failed (404): {session_id}")
        return self._metadata.get(session_id, [])

    def practice_video_tokens(self, session_id):
        return self._tokens.get(session_id, [{"type": "EdgertronicVideos"}])


def _clip(play_id, cam="Edgertronic"):
    return {"playId": play_id, "cameraType": cam, "cameraName": "",
           "videoDurationInSeconds": 0.8, "width": 1280, "height": 1008, "framerate": 240}


def test_dry_run_does_not_download_or_write(monkeypatch):
    session = _FakeSession(
        sessions=[{"sessionId": "s1"}],
        metadata_by_session={"s1": [_clip("p1"), _clip("p2")]})
    monkeypatch.setattr(loader.BV, "existing_play_ids", lambda ids: set())
    monkeypatch.setattr(loader.TV, "edgertronic_token", lambda tokens: {"token": "x"})
    monkeypatch.setattr(loader.TV, "list_container_blobs", lambda ti: [
        "Plays/p1/Edgertronic/clip.mp4", "Plays/p2/Edgertronic/clip.mp4"])
    monkeypatch.setattr(loader.TV, "blob_for_play",
                        lambda blobs, pid: f"Plays/{pid}/Edgertronic/clip.mp4")

    downloads = []
    adds = []
    monkeypatch.setattr(loader.TV, "download_blob", lambda ti, b: downloads.append(b) or b"x")
    monkeypatch.setattr(loader.BV, "add_clip", lambda *a, **k: adds.append((a, k)))

    result = load_bullpen_video(session, "2026-09-15T00:00:00Z", "2026-09-16T00:00:00Z",
                                dry_run=True)

    assert downloads == []
    assert adds == []
    assert result.clips_found == 2
    assert result.clips_downloaded == 2   # counted even though nothing was written
    assert result.clips_skipped_existing == 0
    assert result.dry_run is True


def test_skips_already_downloaded_clips(monkeypatch):
    session = _FakeSession(
        sessions=[{"sessionId": "s1"}],
        metadata_by_session={"s1": [_clip("p1"), _clip("p2")]})
    monkeypatch.setattr(loader.BV, "existing_play_ids", lambda ids: {"p1"})
    monkeypatch.setattr(loader.TV, "edgertronic_token", lambda tokens: {"token": "x"})
    monkeypatch.setattr(loader.TV, "list_container_blobs",
                        lambda ti: ["Plays/p2/Edgertronic/clip.mp4"])
    monkeypatch.setattr(loader.TV, "blob_for_play",
                        lambda blobs, pid: f"Plays/{pid}/Edgertronic/clip.mp4")
    monkeypatch.setattr(loader.TV, "download_blob", lambda ti, b: b"bytes")
    monkeypatch.setattr(loader, "remux_to_mp4", lambda data: data)
    added = []
    monkeypatch.setattr(loader.BV, "add_clip", lambda *a, **k: added.append(a[0]))

    result = load_bullpen_video(session, "2026-09-15T00:00:00Z", "2026-09-16T00:00:00Z",
                                dry_run=False)

    assert added == ["p2"]   # p1 skipped, only p2 downloaded/indexed
    assert result.clips_found == 2
    assert result.clips_skipped_existing == 1
    assert result.clips_downloaded == 1


def test_not_dry_run_downloads_and_indexes_clip_bytes(monkeypatch):
    session = _FakeSession(
        sessions=[{"sessionId": "s1"}],
        metadata_by_session={"s1": [_clip("p1")]})
    monkeypatch.setattr(loader.BV, "existing_play_ids", lambda ids: set())
    monkeypatch.setattr(loader.TV, "edgertronic_token", lambda tokens: {"token": "x"})
    monkeypatch.setattr(loader.TV, "list_container_blobs",
                        lambda ti: ["Plays/p1/Edgertronic/clip.mp4"])
    monkeypatch.setattr(loader.TV, "blob_for_play",
                        lambda blobs, pid: f"Plays/{pid}/Edgertronic/clip.mp4")
    monkeypatch.setattr(loader.TV, "download_blob", lambda ti, b: b"real-bytes")
    monkeypatch.setattr(loader, "remux_to_mp4", lambda data: data.upper())

    added = []
    monkeypatch.setattr(loader.BV, "add_clip",
                        lambda play_id, session_id, data, **kw: added.append(
                            (play_id, session_id, data, kw)))

    result = load_bullpen_video(session, "2026-09-15T00:00:00Z", "2026-09-16T00:00:00Z",
                                dry_run=False)

    assert result.clips_downloaded == 1
    # data is the REMUXED bytes (b"real-bytes".upper()), not the raw download --
    # proves remux_to_mp4 runs before the clip is indexed, not after/never.
    assert added == [("p1", "s1", b"REAL-BYTES",
                      {"mimetype": "video/mp4", "duration_sec": 0.8, "width": 1280,
                       "height": 1008, "framerate": 240})]


def test_missing_blob_in_container_is_counted_not_skipped_silently(monkeypatch):
    session = _FakeSession(
        sessions=[{"sessionId": "s1"}],
        metadata_by_session={"s1": [_clip("p1")]})
    monkeypatch.setattr(loader.BV, "existing_play_ids", lambda ids: set())
    monkeypatch.setattr(loader.TV, "edgertronic_token", lambda tokens: {"token": "x"})
    monkeypatch.setattr(loader.TV, "list_container_blobs", lambda ti: [])  # p1 not in container
    monkeypatch.setattr(loader.TV, "blob_for_play", lambda blobs, pid: None)

    result = load_bullpen_video(session, "2026-09-15T00:00:00Z", "2026-09-16T00:00:00Z",
                                dry_run=True)

    assert result.clips_missing_blob == 1
    assert result.clips_downloaded == 0


def test_session_with_no_edgertronic_token_is_skipped(monkeypatch):
    session = _FakeSession(
        sessions=[{"sessionId": "s1"}],
        metadata_by_session={"s1": [_clip("p1")]})
    monkeypatch.setattr(loader.BV, "existing_play_ids", lambda ids: set())
    monkeypatch.setattr(loader.TV, "edgertronic_token", lambda tokens: None)
    called = []
    monkeypatch.setattr(loader.TV, "list_container_blobs", lambda ti: called.append(1))

    result = load_bullpen_video(session, "2026-09-15T00:00:00Z", "2026-09-16T00:00:00Z",
                                dry_run=True)

    assert called == []   # never even tries to list a container with no token
    assert result.clips_found == 1
    assert result.clips_downloaded == 0


def test_limit_caps_downloads_across_sessions(monkeypatch):
    session = _FakeSession(
        sessions=[{"sessionId": "s1"}, {"sessionId": "s2"}],
        metadata_by_session={
            "s1": [_clip("p1"), _clip("p2")],
            "s2": [_clip("p3"), _clip("p4")],
        })
    monkeypatch.setattr(loader.BV, "existing_play_ids", lambda ids: set())
    monkeypatch.setattr(loader.TV, "edgertronic_token", lambda tokens: {"token": "x"})
    monkeypatch.setattr(loader.TV, "list_container_blobs", lambda ti: [
        f"Plays/{p}/Edgertronic/clip.mp4" for p in ("p1", "p2", "p3", "p4")])
    monkeypatch.setattr(loader.TV, "blob_for_play",
                        lambda blobs, pid: f"Plays/{pid}/Edgertronic/clip.mp4")

    result = load_bullpen_video(session, "2026-09-15T00:00:00Z", "2026-09-16T00:00:00Z",
                                dry_run=True, limit=3)

    assert result.clips_downloaded == 3


def test_no_edgertronic_clips_in_a_session_is_a_cheap_noop(monkeypatch):
    """A session whose metadata has zero Edgertronic clips (e.g. iPhone-only
    or a hitting session) never fetches a token or lists a container."""
    session = _FakeSession(
        sessions=[{"sessionId": "s1"}],
        metadata_by_session={"s1": [_clip("p1", cam="iPhone")]})
    monkeypatch.setattr(loader.BV, "existing_play_ids", lambda ids: set())
    called = []
    monkeypatch.setattr(loader.TV, "edgertronic_token", lambda tokens: called.append(1))

    result = load_bullpen_video(session, "2026-09-15T00:00:00Z", "2026-09-16T00:00:00Z",
                                dry_run=True)

    assert called == []
    assert result.clips_found == 0


def test_mimetype_is_always_mp4_after_remux_regardless_of_blob_extension(monkeypatch):
    """Every clip goes through remux_to_mp4 before it's indexed (see that
    function's docstring for why -- Edgertronic's raw .mov container hangs
    forever in Chrome), so the stored mimetype is always "video/mp4", even
    for a source blob with a different extension (.mkv here)."""
    session = _FakeSession(
        sessions=[{"sessionId": "s1"}],
        metadata_by_session={"s1": [_clip("p1")]})
    monkeypatch.setattr(loader.BV, "existing_play_ids", lambda ids: set())
    monkeypatch.setattr(loader.TV, "edgertronic_token", lambda tokens: {"token": "x"})
    monkeypatch.setattr(loader.TV, "list_container_blobs",
                        lambda ti: ["Plays/p1/Edgertronic/clip.mkv"])
    monkeypatch.setattr(loader.TV, "blob_for_play",
                        lambda blobs, pid: f"Plays/{pid}/Edgertronic/clip.mkv")
    monkeypatch.setattr(loader.TV, "download_blob", lambda ti, b: b"bytes")
    monkeypatch.setattr(loader, "remux_to_mp4", lambda data: data)

    added = []
    monkeypatch.setattr(loader.BV, "add_clip",
                        lambda play_id, session_id, data, **kw: added.append(kw["mimetype"]))

    load_bullpen_video(session, "2026-09-15T00:00:00Z", "2026-09-16T00:00:00Z", dry_run=False)

    assert added == ["video/mp4"]


def test_remux_to_mp4_writes_input_runs_ffmpeg_and_returns_output_bytes(monkeypatch):
    """Doesn't invoke a real ffmpeg -- mocks subprocess.run and has the fake
    process write to the destination path ffmpeg was told to write to,
    proving remux_to_mp4 reads that same file back rather than, say,
    capturing stdout."""
    def _fake_run(args, check, capture_output):
        assert args[0] == "ffmpeg"
        dst = args[-1]
        with open(dst, "wb") as f:
            f.write(b"remuxed-mp4-bytes")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(loader.subprocess, "run", _fake_run)
    assert remux_to_mp4(b"raw-mov-bytes") == b"remuxed-mp4-bytes"


def test_remux_to_mp4_raises_remux_error_when_ffmpeg_missing(monkeypatch):
    def _raise(*a, **k):
        raise FileNotFoundError()

    monkeypatch.setattr(loader.subprocess, "run", _raise)
    with pytest.raises(RemuxError, match="ffmpeg not found"):
        remux_to_mp4(b"raw-mov-bytes")


def test_remux_to_mp4_raises_remux_error_on_ffmpeg_failure(monkeypatch):
    def _raise(*a, **k):
        raise subprocess.CalledProcessError(1, ["ffmpeg"], stderr=b"invalid data found")

    monkeypatch.setattr(loader.subprocess, "run", _raise)
    with pytest.raises(RemuxError, match="invalid data found"):
        remux_to_mp4(b"raw-mov-bytes")


def test_one_sessions_api_error_does_not_sink_the_rest_of_the_batch(monkeypatch):
    """Confirmed live (2026-09-22): a multi-day pull hit a 404 on one
    session's video metadata and the whole run aborted, losing every OTHER
    session's clips too. s1 errors, s2 and s3 must still be processed."""
    session = _FakeSession(
        sessions=[{"sessionId": "s1"}, {"sessionId": "s2"}, {"sessionId": "s3"}],
        metadata_by_session={"s2": [_clip("p2")], "s3": [_clip("p3")]},
        error_sessions={"s1"})
    monkeypatch.setattr(loader.BV, "existing_play_ids", lambda ids: set())
    monkeypatch.setattr(loader.TV, "edgertronic_token", lambda tokens: {"token": "x"})
    monkeypatch.setattr(loader.TV, "list_container_blobs",
                        lambda ti: ["Plays/p2/Edgertronic/clip.mp4", "Plays/p3/Edgertronic/clip.mp4"])
    monkeypatch.setattr(loader.TV, "blob_for_play",
                        lambda blobs, pid: f"Plays/{pid}/Edgertronic/clip.mp4")

    result = load_bullpen_video(session, "2026-09-15T00:00:00Z", "2026-09-16T00:00:00Z",
                                dry_run=True)

    assert result.sessions_errored == 1
    assert result.clips_found == 2   # s2's p2 + s3's p3, despite s1 blowing up first
    assert result.clips_downloaded == 2


def test_one_sessions_connection_error_does_not_sink_the_rest_of_the_batch(monkeypatch):
    """Confirmed live (2026-09-22): a multi-day pull hit a raw connection
    reset mid-run (`requests.exceptions.ConnectionError`, not an HTTP error
    response, so NOT a TrackmanAPIError) and the whole run aborted."""
    import requests

    class _FlakySession(_FakeSession):
        def practice_video_metadata(self, session_id):
            if session_id == "s1":
                raise requests.exceptions.ConnectionError("connection reset")
            return super().practice_video_metadata(session_id)

    session = _FlakySession(
        sessions=[{"sessionId": "s1"}, {"sessionId": "s2"}],
        metadata_by_session={"s2": [_clip("p2")]})
    monkeypatch.setattr(loader.BV, "existing_play_ids", lambda ids: set())
    monkeypatch.setattr(loader.TV, "edgertronic_token", lambda tokens: {"token": "x"})
    monkeypatch.setattr(loader.TV, "list_container_blobs",
                        lambda ti: ["Plays/p2/Edgertronic/clip.mp4"])
    monkeypatch.setattr(loader.TV, "blob_for_play",
                        lambda blobs, pid: f"Plays/{pid}/Edgertronic/clip.mp4")

    result = load_bullpen_video(session, "2026-09-15T00:00:00Z", "2026-09-16T00:00:00Z",
                                dry_run=True)

    assert result.sessions_errored == 1
    assert result.clips_found == 1   # s2's p2, despite s1's connection error
    assert result.clips_downloaded == 1


def test_one_clips_download_error_does_not_sink_the_rest_of_the_session(monkeypatch):
    session = _FakeSession(
        sessions=[{"sessionId": "s1"}],
        metadata_by_session={"s1": [_clip("p1"), _clip("p2")]})
    monkeypatch.setattr(loader.BV, "existing_play_ids", lambda ids: set())
    monkeypatch.setattr(loader.TV, "edgertronic_token", lambda tokens: {"token": "x"})
    monkeypatch.setattr(loader.TV, "list_container_blobs", lambda ti: [
        "Plays/p1/Edgertronic/clip.mp4", "Plays/p2/Edgertronic/clip.mp4"])
    monkeypatch.setattr(loader.TV, "blob_for_play",
                        lambda blobs, pid: f"Plays/{pid}/Edgertronic/clip.mp4")

    def _download(ti, blob_name):
        if "p1" in blob_name:
            from app.ingest.trackman_video import TrackmanAPIError
            raise TrackmanAPIError("blob download failed (500)")
        return b"bytes"

    monkeypatch.setattr(loader.TV, "download_blob", _download)
    monkeypatch.setattr(loader, "remux_to_mp4", lambda data: data)
    added = []
    monkeypatch.setattr(loader.BV, "add_clip", lambda *a, **k: added.append(a[0]))

    result = load_bullpen_video(session, "2026-09-15T00:00:00Z", "2026-09-16T00:00:00Z",
                                dry_run=False)

    assert result.clips_errored == 1
    assert added == ["p2"]   # p1's download failed, p2 still got downloaded/indexed
    assert result.clips_downloaded == 1
