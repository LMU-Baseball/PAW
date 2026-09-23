"""Tests for app.ingest.config.trackman_api_cfg (the Trackman Data API
OAuth2 client credentials) -- no test file existed for this module before;
kept scoped to just the new surface, not the pre-existing trackman_cfg/
hittrax_cfg functions."""
from app.ingest import config


def test_trackman_api_cfg_reads_client_id_and_secret(monkeypatch):
    monkeypatch.setenv("TM_API_CLIENT_ID", "cid-123")
    monkeypatch.setenv("TM_API_CLIENT_SECRET", "secret-456")
    cfg = config.trackman_api_cfg()
    assert cfg == {"client_id": "cid-123", "client_secret": "secret-456"}


def test_trackman_api_cfg_raises_when_client_id_missing(monkeypatch):
    monkeypatch.delenv("TM_API_CLIENT_ID", raising=False)
    monkeypatch.setenv("TM_API_CLIENT_SECRET", "secret-456")
    try:
        config.trackman_api_cfg()
        raise AssertionError("expected RuntimeError")
    except RuntimeError as e:
        assert "TM_API_CLIENT_ID" in str(e)


def test_trackman_api_cfg_raises_when_secret_missing(monkeypatch):
    monkeypatch.setenv("TM_API_CLIENT_ID", "cid-123")
    monkeypatch.delenv("TM_API_CLIENT_SECRET", raising=False)
    try:
        config.trackman_api_cfg()
        raise AssertionError("expected RuntimeError")
    except RuntimeError as e:
        assert "TM_API_CLIENT_SECRET" in str(e)
