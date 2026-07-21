"""Tests for the Dash hitting dashboard (shell, selectors, tabs)."""
import pandas as pd
import pytest

from app import create_app
from config import Config


@pytest.fixture
def server(tmp_path):
    class TestConfig(Config):
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 't.db'}"

    return create_app(TestConfig)


def test_build_hitting_dash_mounts():
    from flask import Flask
    from app.dashboards.hitting import build_hitting_dash, INDEX_STRING
    # Fresh bare server so we don't double-mount the one create_app() already added.
    dash_app = build_hitting_dash(Flask(__name__))
    assert dash_app.config.url_base_pathname == "/dash/hitting/"
    assert "palms-grey.png" in INDEX_STRING
    assert "/static/reports/lion.png" in INDEX_STRING
