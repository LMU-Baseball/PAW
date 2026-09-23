"""Trackman Data API client: OAuth2 auth + practice (bullpen) session/video
discovery for Edgertronic per-pitch video.

Separate from `connections.py`'s SFTP/FTPS wrappers -- this is a REST API
(not a file transfer), so it talks HTTP via `requests` instead of
paramiko/ftplib. Same philosophy as the rest of `app/ingest`: no live-network
tests here, just the pure request-building/response-parsing logic, exercised
against mocked HTTP in tests; correctness against the real API is verified by
whoever runs the loader (`flask ingest trackman-video-check` below is the
smoke test for that).

Auth (per TrackMan's "Quick Start Guide for Customers v3.1"): OAuth2
`client_credentials` grant -- the older `password` grant (username/password)
is explicitly marked deprecated in that doc. Only a Client ID + Client Secret
are needed (`TM_API_CLIENT_ID`/`TM_API_CLIENT_SECRET`, see
`app.ingest.config.trackman_api_cfg`) -- no separate TrackMan user login. A
token is valid for `expires_in` seconds (TrackMan's docs show 3600); `Session`
caches it in-process and transparently renews via the `refresh_token` grant
once it's within `_REFRESH_MARGIN` of expiring, falling back to a fresh
`client_credentials` request if the refresh itself fails (e.g. the refresh
token expired too).

Video delivery for PRACTICE sessions (unlike GAME sessions, which get
long-lived direct URLs via the newer "VideoURL approach") is SAS-token-based
only: `practice_video_tokens` returns a time-limited Azure Blob SAS token
scoped to the whole session's container, which a caller must use to list/
download the blobs promptly -- these tokens expire (see each result's
`expiresAtUtc`), so they must never be cached/stored long-term the way the
existing `video_clips` table stores permanent S3 URLs for game video. Actually
downloading + re-hosting the bytes is a separate, not-yet-built step (the
`PlayID` join against our own SFTP-loaded BULLPEN table needs verifying
against a real session first).
"""
from __future__ import annotations

import time

import requests

_TOKEN_URL = "https://login.trackman.com/connect/token"
_API_BASE = "https://dataapi.trackmanbaseball.com/api/v1"
_DISCOVERY_URL = f"{_API_BASE}/discovery/practice/sessions"
_VIDEO_METADATA_URL = f"{_API_BASE}/media/practice/videometadata/{{session_id}}"
_VIDEO_TOKENS_URL = f"{_API_BASE}/media/practice/videotokens/{{session_id}}"

_REQUEST_TIMEOUT = 30
# Renew the access token this many seconds before its actual expiry, so it
# never goes stale mid-call on a slow connection.
_REFRESH_MARGIN = 60

# TrackMan's discovery endpoint caps a query at 30 consecutive days.
MAX_DISCOVERY_SPAN_DAYS = 30

VALID_SESSION_TYPES = ("All", "Pitching", "Hitting")

# The `cameraType` value practice_video_metadata rows use for bullpen
# high-speed video (as opposed to "iPhone"). TrackMan's own Quick Start docs
# show both `cameraName` and `cameraType` set to this value in their example
# JSON -- verified live (2026-09-22, a real 95-clip LMU bullpen session)
# that only `cameraType` is actually populated; `cameraName` comes back "".
# `edgertronic_clips` checks both so it isn't silently broken again if a
# future account/session populates `cameraName` after all.
EDGERTRONIC_CAMERA = "Edgertronic"


class TrackmanAPIError(RuntimeError):
    """Raised for any non-2xx response from the Trackman Data API. The
    server's own `error`/`error_description` body (when present) is folded
    into the message so a failure is actionable from the exception text
    alone, without a caller needing to inspect the raw response."""


def _raise_for_status(resp: requests.Response, action: str) -> None:
    if resp.ok:
        return
    detail = resp.text
    try:
        body = resp.json()
        detail = body.get("error_description") or body.get("error") or detail
    except ValueError:
        pass
    raise TrackmanAPIError(f"{action} failed ({resp.status_code}): {detail}")


class Session:
    """One OAuth2 session against the Trackman Data API: owns the token
    cache. One instance per ingest run (not a module-level singleton) -- keep
    it around across multiple API calls within a run to avoid re-authenticating
    every request, but never share it across runs/processes."""

    def __init__(self, cfg: dict):
        self._cfg = cfg
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._expires_at: float = 0.0

    def _store(self, body: dict) -> None:
        self._access_token = body["access_token"]
        self._refresh_token = body.get("refresh_token")
        self._expires_at = time.monotonic() + float(body["expires_in"])

    def _authenticate(self) -> None:
        resp = requests.post(_TOKEN_URL, data={
            "client_id": self._cfg["client_id"],
            "client_secret": self._cfg["client_secret"],
            "grant_type": "client_credentials",
        }, timeout=_REQUEST_TIMEOUT)
        _raise_for_status(resp, "Trackman authentication")
        self._store(resp.json())

    def _refresh(self) -> None:
        resp = requests.post(_TOKEN_URL, data={
            "client_id": self._cfg["client_id"],
            "client_secret": self._cfg["client_secret"],
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
        }, timeout=_REQUEST_TIMEOUT)
        if not resp.ok:
            # The refresh token itself may have expired/been revoked -- fall
            # back to a fresh client_credentials login rather than treating
            # that as fatal.
            self._authenticate()
            return
        self._store(resp.json())

    def get_token(self) -> str:
        """A currently-valid access token, authenticating or refreshing
        first if needed."""
        if self._access_token is None:
            self._authenticate()
        elif time.monotonic() >= self._expires_at - _REFRESH_MARGIN:
            self._refresh() if self._refresh_token else self._authenticate()
        return self._access_token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.get_token()}"}

    def discover_practice_sessions(self, date_from: str, date_to: str, *,
                                   session_type: str = "All") -> list[dict]:
        """Practice (bullpen/hitting) sessions in [date_from, date_to] (ISO
        8601 UTC timestamps, e.g. "2026-09-22T00:00:00Z"). TrackMan caps this
        span at `MAX_DISCOVERY_SPAN_DAYS` -- this raises rather than silently
        truncating a wider request, so a caller's date math bug fails loudly.
        Each returned dict includes `sessionId` (the key for every later
        query) and `sessionType` ("Pitching"/"Hitting")."""
        if session_type not in VALID_SESSION_TYPES:
            raise ValueError(
                f"session_type must be one of {VALID_SESSION_TYPES}, got {session_type!r}")
        span = _parse_utc(date_to) - _parse_utc(date_from)
        if span.days > MAX_DISCOVERY_SPAN_DAYS:
            raise ValueError(
                f"date span is {span.days} days, over TrackMan's "
                f"{MAX_DISCOVERY_SPAN_DAYS}-day discovery limit")
        resp = requests.post(_DISCOVERY_URL, headers=self._headers(),
                             json={"sessionType": session_type, "utcDateFrom": date_from,
                                  "utcDateTo": date_to}, timeout=_REQUEST_TIMEOUT)
        _raise_for_status(resp, "practice session discovery")
        return resp.json()

    def practice_video_metadata(self, session_id: str) -> list[dict]:
        """One dict per video clip in `session_id` (`playId`, `cameraName`
        ["Edgertronic"/"iPhone"], `videoDurationInSeconds`, dimensions, etc.)
        -- filter to `cameraName == EDGERTRONIC_CAMERA` for bullpen video."""
        resp = requests.get(_VIDEO_METADATA_URL.format(session_id=session_id),
                            headers=self._headers(), timeout=_REQUEST_TIMEOUT)
        _raise_for_status(resp, "practice video metadata fetch")
        return resp.json()

    def practice_video_tokens(self, session_id: str) -> list[dict]:
        """The Azure Blob SAS tokens needed to list/download `session_id`'s
        video container (one dict per video type, e.g. EdgertronicVideos) --
        see this module's docstring: these expire, fetch immediately before
        downloading, never cache long-term."""
        resp = requests.get(_VIDEO_TOKENS_URL.format(session_id=session_id),
                            headers=self._headers(), timeout=_REQUEST_TIMEOUT)
        _raise_for_status(resp, "practice video token fetch")
        return resp.json()


def _parse_utc(iso_ts: str):
    from datetime import datetime
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))


def edgertronic_clips(metadata: list[dict]) -> list[dict]:
    """`practice_video_metadata`'s rows narrowed to Edgertronic clips only,
    keyed by `playId` -- the join point against BULLPEN.PlayID once that
    match is verified against a real session (see module docstring). Checks
    `cameraType` (what LMU's real account actually populates) OR
    `cameraName` (what TrackMan's docs' example JSON shows) -- see
    EDGERTRONIC_CAMERA's docstring."""
    return [row for row in metadata
           if EDGERTRONIC_CAMERA in (row.get("cameraType"), row.get("cameraName"))]


# ========================= AZURE BLOB DOWNLOAD ===============================
#
# `practice_video_tokens` hands back one dict per video type (e.g.
# "EdgertronicVideos") with `entityPath`/`endpoint`/`token` -- an Azure Blob
# Storage container (named `endpoint`, a GUID) plus a time-limited SAS query
# string (`token`, already starts with "?"). Per section 10 of TrackMan's
# Quick Start Guide, a clip's blob lives at `Plays/{PlayId}/{VideoType}/
# {UnitSystem}` (UnitSystem only present for a data-overlay variant) --
# `blob_for_play` picks the shortest matching path, i.e. the plain clip over
# an overlay variant, when more than one blob matches a play.


def edgertronic_token(tokens: list[dict]) -> dict | None:
    """The `practice_video_tokens` entry for Edgertronic clips specifically
    (`type == "EdgertronicVideos"`), or None if this session has none."""
    for t in tokens:
        if t.get("type") == "EdgertronicVideos":
            return t
    return None


def _container_url(token_info: dict) -> str:
    return f"https://{token_info['entityPath']}.blob.core.windows.net/{token_info['endpoint']}"


def list_container_blobs(token_info: dict) -> list[str]:
    """Blob names (full paths, e.g. "Plays/{playId}/Edgertronic/clip.mp4")
    in the Azure container described by one `practice_video_tokens` entry
    -- the standard Azure Blob "List Blobs" REST call, XML response."""
    import xml.etree.ElementTree as ET

    url = f"{_container_url(token_info)}{token_info['token']}&comp=list&restype=container"
    resp = requests.get(url, timeout=_REQUEST_TIMEOUT)
    _raise_for_status(resp, "Azure blob container listing")
    root = ET.fromstring(resp.text)
    return [name for name in (b.findtext("Name") for b in root.iter("Blob")) if name]


def blob_for_play(blob_names: list[str], play_id: str) -> str | None:
    """The blob path for one play's clip out of an already-listed container,
    or None if this play has no blob in it. Prefers the SHORTEST matching
    path when more than one exists -- a data-overlay variant sits one
    subfolder deeper (.../Edgertronic/Imperial/...), so the plain clip
    (no UnitSystem segment) is always the shortest match."""
    matches = [b for b in blob_names if f"/{play_id}/" in b]
    return min(matches, key=len) if matches else None


def download_blob(token_info: dict, blob_name: str) -> bytes:
    """Raw bytes of one blob from the container described by `token_info`
    -- call this immediately after listing; the SAS token expires (see this
    module's docstring), so don't hold a blob name around indefinitely
    before downloading it."""
    url = f"{_container_url(token_info)}/{blob_name}{token_info['token']}"
    resp = requests.get(url, timeout=_REQUEST_TIMEOUT)
    _raise_for_status(resp, f"Azure blob download ({blob_name})")
    return resp.content
