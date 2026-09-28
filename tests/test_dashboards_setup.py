"""app.dashboards._serialize_dash_setup: parallel first requests after a
restart must wait for Dash's one-time server setup instead of 500ing with
'"dash" is not a registered library' (2026-09-27, seen live on Lightsail)."""
import threading
import time

import pytest
from dash import Dash, html
from flask import Flask

from app import create_app
from app.dashboards import _run_once_under, _serialize_dash_setup
from config import Config

_SUITE = "/_dash-component-suites/dash/deps/react@18.3.1.min.js"


def _slow_setup_dash(serialize: bool):
    """A bare Dash app whose setup is slowed down, so a second request
    reliably lands in the window where Dash has already flagged setup as
    done but hasn't registered its libraries yet."""
    server = Flask(__name__)
    dash_app = Dash(__name__, server=server)
    dash_app.layout = html.Div("x")
    original = dash_app._generate_scripts_html

    def _slow():
        time.sleep(0.3)
        return original()

    dash_app._generate_scripts_html = _slow
    if serialize:
        _serialize_dash_setup(server)
    return server


def _first_page_load(server):
    """The index request (triggers setup) plus a component-suite request
    arriving mid-setup, like a browser's parallel script fetches."""
    statuses = {}

    def _get(key, path):
        statuses[key] = server.test_client().get(path).status_code

    index = threading.Thread(target=_get, args=("index", "/"))
    index.start()
    time.sleep(0.1)
    _get("suite", _SUITE)
    index.join()
    return statuses


def test_unserialized_dash_setup_race_reproduces_the_500():
    assert _first_page_load(_slow_setup_dash(serialize=False))["suite"] == 500


def test_serialized_dash_setup_makes_parallel_first_requests_wait():
    assert _first_page_load(_slow_setup_dash(serialize=True)) == {
        "index": 200, "suite": 200}


def test_run_once_under_calls_setup_exactly_once_across_threads():
    calls = []

    def _setup():
        calls.append(1)
        time.sleep(0.05)

    wrapped = _run_once_under(threading.Lock(), _setup)
    threads = [threading.Thread(target=wrapped) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert calls == [1]


@pytest.fixture
def server(tmp_path):
    class T(Config):
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 't.db'}"
    return create_app(T)


def test_every_paw_dashboard_setup_hook_is_serialized(server):
    setup_hooks = [f for f in server.before_request_funcs[None]
                   if getattr(f, "__name__", "") == "_setup_server"]
    assert len(setup_hooks) == 8
    assert all("_run_once_under" in f.__qualname__ for f in setup_hooks)
