"""Tests for app.ingest.config and app.ingest.common (pure helpers + config)."""
import pytest
from sqlalchemy import create_engine, text

from app.ingest import common
from app.ingest.common import LoadResult, mps_to_mph, meters_to_feet, safe_numeric
from app.ingest import config as ingest_config


# ---- common: unit conversions -------------------------------------------

def test_mps_to_mph_converts():
    # round(28.61 * 2.23694, 2) == 64.0 (the brief's example value of 64.01
    # does not match its own stated formula; see task-1-report.md concerns).
    assert mps_to_mph(28.61) == 64.0


def test_mps_to_mph_none_is_none():
    assert mps_to_mph(None) is None


def test_mps_to_mph_blank_string_is_none():
    assert mps_to_mph("") is None


def test_meters_to_feet_converts():
    assert meters_to_feet(1) == 3.28


def test_meters_to_feet_none_is_none():
    assert meters_to_feet(None) is None


def test_safe_numeric_blank_is_none():
    assert safe_numeric("") is None


def test_safe_numeric_none_is_none():
    assert safe_numeric(None) is None


def test_safe_numeric_parses_string_number():
    assert safe_numeric("12.5") == 12.5


# ---- common: LoadResult dataclass ----------------------------------------

def test_load_result_field_defaults():
    r = LoadResult(inserted=0, skipped=0, files=0, date_min=None, date_max=None, dry_run=False)
    assert r.inserted == 0
    assert r.skipped == 0
    assert r.files == 0
    assert r.date_min is None
    assert r.date_max is None
    assert r.dry_run is False


# ---- common: DB helpers (in-memory sqlite as a real fake engine) --------

@pytest.fixture
def sqlite_engine():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE widgets (session_key TEXT, val INTEGER)"))
        conn.execute(
            text("INSERT INTO widgets (session_key, val) VALUES (:k, :v)"),
            [{"k": "a", "v": 1}, {"k": "b", "v": 2}, {"k": None, "v": 3}],
        )
    return engine


def test_existing_keys_returns_distinct_str_values_dropping_none(sqlite_engine):
    keys = common.existing_keys(sqlite_engine, "widgets", "session_key")
    assert keys == {"a", "b"}


def test_chunked_insert_inserts_rows_and_returns_count(sqlite_engine):
    rows = [{"session_key": "c", "val": 10}, {"session_key": "d", "val": 20}]
    count = common.chunked_insert(sqlite_engine, "widgets", rows, chunksize=1)
    assert count == 2
    keys = common.existing_keys(sqlite_engine, "widgets", "session_key")
    assert keys == {"a", "b", "c", "d"}


def test_chunked_insert_empty_rows_returns_zero(sqlite_engine):
    assert common.chunked_insert(sqlite_engine, "widgets", [], chunksize=500) == 0


# ---- config: env-driven cfg dicts ----------------------------------------

def test_trackman_cfg_reads_env(monkeypatch):
    monkeypatch.setenv("TM_SFTP_HOST", "tm.example.com")
    monkeypatch.setenv("TM_SFTP_PORT", "22")
    monkeypatch.setenv("TM_SFTP_USER", "tmuser")
    monkeypatch.setenv("TM_SFTP_PASS", "tmpass")
    cfg = ingest_config.trackman_cfg()
    assert cfg["host"] == "tm.example.com"
    assert cfg["port"] == 22
    assert cfg["user"] == "tmuser"
    assert cfg["password"] == "tmpass"


def test_trackman_cfg_missing_var_raises_named_runtime_error(monkeypatch):
    monkeypatch.delenv("TM_SFTP_HOST", raising=False)
    monkeypatch.setenv("TM_SFTP_PORT", "22")
    monkeypatch.setenv("TM_SFTP_USER", "tmuser")
    monkeypatch.setenv("TM_SFTP_PASS", "tmpass")
    with pytest.raises(RuntimeError, match="TM_SFTP_HOST not set"):
        ingest_config.trackman_cfg()


def test_hittrax_cfg_reads_env(monkeypatch):
    monkeypatch.setenv("HT_FTPS_HOST", "ht.example.com")
    monkeypatch.setenv("HT_FTPS_PORT", "21")
    monkeypatch.setenv("HT_FTPS_USER", "htuser")
    monkeypatch.setenv("HT_FTPS_PASSWORD", "htpass")
    monkeypatch.setenv("HT_FTPS_REMOTE_DIR", "/incoming")
    cfg = ingest_config.hittrax_cfg()
    assert cfg["host"] == "ht.example.com"
    assert cfg["port"] == 21
    assert cfg["user"] == "htuser"
    assert cfg["password"] == "htpass"
    assert cfg["remote_dir"] == "/incoming"


def test_hittrax_cfg_missing_var_raises_named_runtime_error(monkeypatch):
    monkeypatch.delenv("HT_FTPS_HOST", raising=False)
    monkeypatch.setenv("HT_FTPS_PORT", "21")
    monkeypatch.setenv("HT_FTPS_USER", "htuser")
    monkeypatch.setenv("HT_FTPS_PASSWORD", "htpass")
    monkeypatch.setenv("HT_FTPS_REMOTE_DIR", "/incoming")
    with pytest.raises(RuntimeError, match="HT_FTPS_HOST not set"):
        ingest_config.hittrax_cfg()
