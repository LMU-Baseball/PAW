"""A broken PDF renderer must report itself, not vanish into a bare 500.

`pitcher_pdf` / `bullpen_pdf` caught only `ReportDataError` (-> 404); every
Playwright/Chromium failure propagated unhandled, so Flask returned "Internal
Server Error" with the real cause lost. That is the exact symptom seen on a host
that can't run headless Chromium -- too little RAM, or `playwright install`
without `--with-deps` leaving the browser's shared libraries missing.

`html_to_pdf` now logs the underlying failure and raises `ReportEngineError`,
and the routes turn that into a 503 that says so.
"""
import logging

import pytest

from app import create_app
from app.auth.models import User
from app.extensions import db
from app.reports.pdf import ReportEngineError
from config import Config


@pytest.fixture
def server(tmp_path):
    class T(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 't.db'}"
    app = create_app(T)
    with app.app_context():
        coach = User(email="rep@lmu.edu", name="Coach", role="coach")
        coach.set_password("x")
        db.session.add(coach)
        db.session.commit()
    return app


@pytest.fixture
def client(server):
    c = server.test_client()
    c.post("/login", data={"email": "rep@lmu.edu", "password": "x"})
    return c


# --- html_to_pdf translates engine failures -------------------------------

def test_html_to_pdf_raises_engine_error_and_logs(monkeypatch, caplog):
    """A Chromium launch failure must become ReportEngineError AND be logged --
    the log line is the only place the real cause is visible on the host."""
    from app.reports import pdf as P

    boom = RuntimeError("libnss3.so: cannot open shared object file")

    def _explode(html, base_url=None):
        raise boom

    # Simulate the render thread handing back a failure.
    monkeypatch.setattr(P, "_ensure_render_thread", lambda: None)

    class _Fut:
        def result(self, timeout=None):
            raise boom

    monkeypatch.setattr(P, "Future", _Fut)
    monkeypatch.setattr(P._JOBS, "put", lambda job: None)

    with caplog.at_level(logging.ERROR, logger="app.reports.pdf"):
        with pytest.raises(ReportEngineError) as ei:
            P.html_to_pdf("<html><body>x</body></html>")

    assert "libnss3" in str(ei.value)
    assert any("libnss3" in r.getMessage() or "libnss3" in str(r.exc_info)
               for r in caplog.records), "real cause never reached the log"


def test_html_to_pdf_timeout_becomes_engine_error(monkeypatch):
    """A wedged Chromium must not read as a generic 500 either."""
    from concurrent.futures import TimeoutError as FuturesTimeout
    from app.reports import pdf as P

    monkeypatch.setattr(P, "_ensure_render_thread", lambda: None)

    class _Fut:
        def result(self, timeout=None):
            raise FuturesTimeout()

    monkeypatch.setattr(P, "Future", _Fut)
    monkeypatch.setattr(P._JOBS, "put", lambda job: None)

    with pytest.raises(ReportEngineError) as ei:
        P.html_to_pdf("<html></html>")
    assert "timed out" in str(ei.value).lower()


# --- routes turn it into a 503, not a 500 ---------------------------------

def test_pitcher_pdf_returns_503_not_500(client, monkeypatch):
    from app.reports import routes as R
    monkeypatch.setattr(R, "build_pitcher_postgame", lambda g, p: (_ for _ in ()).throw(
        ReportEngineError("libgbm.so.1: cannot open shared object file")))
    monkeypatch.setattr(R, "can_view_pitcher_report", lambda u, p: True)
    rv = client.get("/reports/pitcher/1/2.pdf")
    assert rv.status_code == 503
    body = rv.get_data(as_text=True)
    assert "report engine is unavailable" in body.lower()
    assert "libgbm" in body


def test_bullpen_pdf_returns_503_not_500(client, monkeypatch):
    from app.reports import routes as R
    monkeypatch.setattr(R, "build_bullpen_report", lambda p, d: (_ for _ in ()).throw(
        ReportEngineError("Out of memory")))
    monkeypatch.setattr(R, "can_view_bullpen", lambda u, p: True)
    rv = client.get("/reports/bullpen/5/2026-03-02.pdf")
    assert rv.status_code == 503
    assert "Out of memory" in rv.get_data(as_text=True)


def test_data_error_still_404(client, monkeypatch):
    """The engine change must not swallow the genuine no-data 404."""
    from app.reports import routes as R
    from app.reports.pitcher_postgame import ReportDataError
    monkeypatch.setattr(R, "build_pitcher_postgame", lambda g, p: (_ for _ in ()).throw(
        ReportDataError("no pitches")))
    monkeypatch.setattr(R, "can_view_pitcher_report", lambda u, p: True)
    assert client.get("/reports/pitcher/1/2.pdf").status_code == 404
