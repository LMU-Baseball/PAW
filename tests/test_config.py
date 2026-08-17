"""Tests for app-DB URI resolution (config._resolve_app_db_uri)."""
import config


def test_resolve_app_db_uri_defaults_to_sqlite(monkeypatch):
    monkeypatch.delenv("APP_DATABASE_URL", raising=False)
    monkeypatch.delenv("APP_DB_NAME", raising=False)
    assert str(config._resolve_app_db_uri()).startswith("sqlite:///")


def test_resolve_app_db_uri_uses_app_db_name_on_rds(monkeypatch):
    monkeypatch.delenv("APP_DATABASE_URL", raising=False)
    monkeypatch.setenv("APP_DB_NAME", "paw_app")
    uri = config._resolve_app_db_uri()
    s = str(uri)
    assert s.startswith("mysql+pymysql://")
    assert s.endswith("/paw_app")  # analytics creds/host, app schema


def test_resolve_app_db_uri_explicit_url_wins(monkeypatch):
    monkeypatch.setenv("APP_DATABASE_URL", "sqlite:////tmp/explicit.db")
    monkeypatch.setenv("APP_DB_NAME", "paw_app")  # ignored when URL is explicit
    assert config._resolve_app_db_uri() == "sqlite:////tmp/explicit.db"
