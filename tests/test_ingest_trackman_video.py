"""Tests for app.ingest.trackman_video: OAuth2 token handling + practice
session/video discovery request-building. No live network -- `requests.post`/
`requests.get` are monkeypatched to fake response objects, matching this
repo's existing ingest-test convention of fake stand-ins over a real HTTP
mocking library (see tests/test_ingest_bullpen_loader.py's `_FakeSFTP`)."""
from __future__ import annotations

import pytest

from app.ingest import trackman_video as TV

CFG = {"client_id": "cid", "client_secret": "csecret"}


class _FakeResponse:
    def __init__(self, status_code=200, json_body=None, text="", content=b""):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._json = json_body
        self.text = text or (str(json_body) if json_body is not None else "")
        self.content = content

    def json(self):
        if self._json is None:
            raise ValueError("no json body")
        return self._json


def _token_body(access="tok-1", refresh="ref-1", expires_in=3600):
    return {"access_token": access, "refresh_token": refresh,
           "token_type": "Bearer", "expires_in": expires_in}


# ------------------------------- auth ---------------------------------------

def test_authenticate_posts_client_credentials_grant(monkeypatch):
    calls = []

    def fake_post(url, data=None, timeout=None):
        calls.append((url, data))
        return _FakeResponse(200, _token_body())
    monkeypatch.setattr(TV.requests, "post", fake_post)

    session = TV.Session(CFG)
    token = session.get_token()

    assert token == "tok-1"
    assert len(calls) == 1
    url, data = calls[0]
    assert url == TV._TOKEN_URL
    assert data == {"client_id": "cid", "client_secret": "csecret",
                    "grant_type": "client_credentials"}


def test_get_token_reuses_cached_token_without_reauthenticating(monkeypatch):
    calls = []
    monkeypatch.setattr(TV.requests, "post", lambda *a, **k: (
        calls.append(1), _FakeResponse(200, _token_body()))[1])

    session = TV.Session(CFG)
    first = session.get_token()
    second = session.get_token()

    assert first == second == "tok-1"
    assert len(calls) == 1   # only one real auth call


def test_get_token_refreshes_when_near_expiry(monkeypatch):
    requests_made = []

    def fake_post(url, data=None, timeout=None):
        requests_made.append(data["grant_type"])
        if data["grant_type"] == "client_credentials":
            return _FakeResponse(200, _token_body(access="tok-1", expires_in=3600))
        assert data["refresh_token"] == "ref-1"
        return _FakeResponse(200, _token_body(access="tok-2", refresh="ref-2"))
    monkeypatch.setattr(TV.requests, "post", fake_post)

    session = TV.Session(CFG)
    session.get_token()
    # Simulate the token being within the refresh margin of expiring.
    session._expires_at = TV.time.monotonic() + TV._REFRESH_MARGIN - 1
    token = session.get_token()

    assert token == "tok-2"
    assert requests_made == ["client_credentials", "refresh_token"]


def test_get_token_falls_back_to_fresh_auth_when_refresh_fails(monkeypatch):
    requests_made = []

    def fake_post(url, data=None, timeout=None):
        requests_made.append(data["grant_type"])
        if data["grant_type"] == "refresh_token":
            return _FakeResponse(400, {"error": "invalid_grant"})
        return _FakeResponse(200, _token_body(access="tok-new"))
    monkeypatch.setattr(TV.requests, "post", fake_post)

    session = TV.Session(CFG)
    session.get_token()
    session._expires_at = TV.time.monotonic() - 1   # already expired
    token = session.get_token()

    assert token == "tok-new"
    assert requests_made == ["client_credentials", "refresh_token", "client_credentials"]


def test_authenticate_failure_raises_with_server_error_detail(monkeypatch):
    monkeypatch.setattr(TV.requests, "post", lambda *a, **k: _FakeResponse(
        400, {"error": "invalid_grant", "error_description": "invalid_client"}))

    session = TV.Session(CFG)
    with pytest.raises(TV.TrackmanAPIError, match="invalid_client"):
        session.get_token()


# --------------------------- discovery ---------------------------------------

def test_discover_practice_sessions_builds_correct_request(monkeypatch):
    monkeypatch.setattr(TV.requests, "post", lambda *a, **k: _FakeResponse(200, _token_body()))
    session = TV.Session(CFG)
    session.get_token()

    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append((url, headers, json))
        return _FakeResponse(200, [{"sessionId": "s1", "sessionType": "Pitching"}])
    monkeypatch.setattr(TV.requests, "post", fake_post)

    result = session.discover_practice_sessions(
        "2026-09-01T00:00:00Z", "2026-09-07T23:59:59Z", session_type="Pitching")

    assert result == [{"sessionId": "s1", "sessionType": "Pitching"}]
    url, headers, body = calls[0]
    assert url == TV._DISCOVERY_URL
    assert headers == {"Authorization": "Bearer tok-1"}
    assert body == {"sessionType": "Pitching", "utcDateFrom": "2026-09-01T00:00:00Z",
                    "utcDateTo": "2026-09-07T23:59:59Z"}


def test_discover_practice_sessions_rejects_bad_session_type(monkeypatch):
    session = TV.Session(CFG)
    with pytest.raises(ValueError, match="session_type"):
        session.discover_practice_sessions("2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z",
                                           session_type="Bogus")


def test_discover_practice_sessions_rejects_span_over_30_days(monkeypatch):
    session = TV.Session(CFG)
    with pytest.raises(ValueError, match="30-day"):
        session.discover_practice_sessions("2026-01-01T00:00:00Z", "2026-03-01T00:00:00Z")


# ----------------------------- video media ------------------------------------

def test_practice_video_metadata_builds_correct_request(monkeypatch):
    monkeypatch.setattr(TV.requests, "post", lambda *a, **k: _FakeResponse(200, _token_body()))
    session = TV.Session(CFG)
    session.get_token()

    calls = []

    def fake_get(url, headers=None, timeout=None):
        calls.append((url, headers))
        return _FakeResponse(200, [
            {"playId": "p1", "cameraType": "Edgertronic", "cameraName": ""},
            {"playId": "p2", "cameraType": "iPhone", "cameraName": ""},
        ])
    monkeypatch.setattr(TV.requests, "get", fake_get)

    result = session.practice_video_metadata("sess-1")

    assert len(result) == 2
    url, headers = calls[0]
    assert url == "https://dataapi.trackmanbaseball.com/api/v1/media/practice/videometadata/sess-1"
    assert headers == {"Authorization": "Bearer tok-1"}


def test_edgertronic_clips_filters_by_camera_type():
    """LMU's real account (verified 2026-09-22 against a live 95-clip
    session) populates `cameraType`, leaving `cameraName` blank -- despite
    TrackMan's own docs showing both set the same way in their example JSON."""
    metadata = [
        {"playId": "p1", "cameraType": "Edgertronic", "cameraName": ""},
        {"playId": "p2", "cameraType": "iPhone", "cameraName": ""},
        {"playId": "p3", "cameraType": "Edgertronic", "cameraName": ""},
    ]
    clips = TV.edgertronic_clips(metadata)
    assert [c["playId"] for c in clips] == ["p1", "p3"]


def test_edgertronic_clips_also_matches_camera_name_per_the_docs():
    """Defensive: if some session ever DOES populate `cameraName` the way
    TrackMan's docs show, that must still be recognized."""
    metadata = [{"playId": "p1", "cameraName": "Edgertronic", "cameraType": ""}]
    clips = TV.edgertronic_clips(metadata)
    assert [c["playId"] for c in clips] == ["p1"]


def test_practice_video_tokens_builds_correct_request(monkeypatch):
    monkeypatch.setattr(TV.requests, "post", lambda *a, **k: _FakeResponse(200, _token_body()))
    session = TV.Session(CFG)
    session.get_token()

    calls = []

    def fake_get(url, headers=None, timeout=None):
        calls.append(url)
        return _FakeResponse(200, [{"type": "EdgertronicVideos", "token": "?sig=abc"}])
    monkeypatch.setattr(TV.requests, "get", fake_get)

    result = session.practice_video_tokens("sess-1")

    assert result == [{"type": "EdgertronicVideos", "token": "?sig=abc"}]
    assert calls[0] == "https://dataapi.trackmanbaseball.com/api/v1/media/practice/videotokens/sess-1"


def test_video_fetch_failure_raises_trackman_api_error(monkeypatch):
    monkeypatch.setattr(TV.requests, "post", lambda *a, **k: _FakeResponse(200, _token_body()))
    session = TV.Session(CFG)
    session.get_token()
    monkeypatch.setattr(TV.requests, "get", lambda *a, **k: _FakeResponse(
        404, text="session not found"))

    with pytest.raises(TV.TrackmanAPIError, match="session not found"):
        session.practice_video_metadata("missing-session")


# ------------------------- azure blob download --------------------------------

TOKEN_INFO = {"type": "EdgertronicVideos", "entityPath": "tmbbdataapiedvideosprod",
             "endpoint": "container-guid-123", "token": "?sv=2018-03-28&sig=abc"}

_LIST_BLOBS_XML = """<?xml version="1.0" encoding="utf-8"?>
<EnumerationResults ServiceEndpoint="https://tmbbdataapiedvideosprod.blob.core.windows.net/"
                    ContainerName="container-guid-123">
  <Blobs>
    <Blob>
      <Name>Plays/aa50a320-1fe9-4eb1-981f-a73a0fdc3bc1/Edgertronic/clip.mp4</Name>
      <Properties><Content-Length>123456</Content-Length></Properties>
    </Blob>
    <Blob>
      <Name>Plays/aa50a320-1fe9-4eb1-981f-a73a0fdc3bc1/Edgertronic/Imperial/clip_overlay.mp4</Name>
      <Properties><Content-Length>150000</Content-Length></Properties>
    </Blob>
    <Blob>
      <Name>Plays/other-play-id/Edgertronic/clip.mp4</Name>
      <Properties><Content-Length>90000</Content-Length></Properties>
    </Blob>
  </Blobs>
  <NextMarker />
</EnumerationResults>"""


def test_edgertronic_token_finds_the_right_entry():
    tokens = [{"type": "iPhoneVideos"}, TOKEN_INFO, {"type": "PlayVideos"}]
    assert TV.edgertronic_token(tokens) == TOKEN_INFO


def test_edgertronic_token_none_when_session_has_no_edgertronic_video():
    assert TV.edgertronic_token([{"type": "iPhoneVideos"}]) is None


def test_list_container_blobs_parses_xml_and_builds_correct_url(monkeypatch):
    calls = []

    def fake_get(url, timeout=None):
        calls.append(url)
        return _FakeResponse(200, text=_LIST_BLOBS_XML)
    monkeypatch.setattr(TV.requests, "get", fake_get)

    blobs = TV.list_container_blobs(TOKEN_INFO)

    assert blobs == [
        "Plays/aa50a320-1fe9-4eb1-981f-a73a0fdc3bc1/Edgertronic/clip.mp4",
        "Plays/aa50a320-1fe9-4eb1-981f-a73a0fdc3bc1/Edgertronic/Imperial/clip_overlay.mp4",
        "Plays/other-play-id/Edgertronic/clip.mp4",
    ]
    assert calls[0] == ("https://tmbbdataapiedvideosprod.blob.core.windows.net/container-guid-123"
                        "?sv=2018-03-28&sig=abc&comp=list&restype=container")


def test_blob_for_play_prefers_shortest_plain_clip_over_overlay_variant():
    blobs = [
        "Plays/aa50a320-1fe9-4eb1-981f-a73a0fdc3bc1/Edgertronic/Imperial/clip_overlay.mp4",
        "Plays/aa50a320-1fe9-4eb1-981f-a73a0fdc3bc1/Edgertronic/clip.mp4",
    ]
    assert TV.blob_for_play(blobs, "aa50a320-1fe9-4eb1-981f-a73a0fdc3bc1") == \
        "Plays/aa50a320-1fe9-4eb1-981f-a73a0fdc3bc1/Edgertronic/clip.mp4"


def test_blob_for_play_none_when_play_not_in_container():
    blobs = ["Plays/other-play-id/Edgertronic/clip.mp4"]
    assert TV.blob_for_play(blobs, "aa50a320-1fe9-4eb1-981f-a73a0fdc3bc1") is None


def test_download_blob_builds_correct_url_and_returns_bytes(monkeypatch):
    calls = []

    def fake_get(url, timeout=None):
        calls.append(url)
        return _FakeResponse(200, content=b"fake-video-bytes")
    monkeypatch.setattr(TV.requests, "get", fake_get)

    data = TV.download_blob(TOKEN_INFO, "Plays/aa50a320-.../Edgertronic/clip.mp4")

    assert data == b"fake-video-bytes"
    assert calls[0] == ("https://tmbbdataapiedvideosprod.blob.core.windows.net/container-guid-123"
                        "/Plays/aa50a320-.../Edgertronic/clip.mp4?sv=2018-03-28&sig=abc")


def test_download_blob_failure_raises_trackman_api_error(monkeypatch):
    monkeypatch.setattr(TV.requests, "get", lambda *a, **k: _FakeResponse(403, text="forbidden"))
    with pytest.raises(TV.TrackmanAPIError, match="forbidden"):
        TV.download_blob(TOKEN_INFO, "Plays/x/Edgertronic/clip.mp4")
