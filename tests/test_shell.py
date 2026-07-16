"""Structural regression tests for the branded shared shell (base.html).

These assert that branded markup and local assets are present and that no
Google Fonts CDN is referenced. Visual polish is verified live, not here.
The shell renders on the login page (extends base.html), so no auth needed.
"""
from app import create_app
from config import Config


def _app():
    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    return create_app(TestConfig)


def test_shell_loads_teko_locally_not_cdn():
    resp = _app().test_client().get("/login")
    body = resp.get_data(as_text=True)
    assert "@font-face" in body
    assert "/static/reports/Teko-Regular.ttf" in body
    assert "fonts.googleapis.com" not in body
    assert "fonts.gstatic.com" not in body


def test_shell_header_shows_logo_linking_home():
    resp = _app().test_client().get("/login")
    body = resp.get_data(as_text=True)
    assert "/static/reports/lmu.png" in body
    assert 'href="/"' in body


def test_shell_defines_design_tokens():
    resp = _app().test_client().get("/login")
    body = resp.get_data(as_text=True)
    assert "--crimson" in body
    assert "--font-display" in body
