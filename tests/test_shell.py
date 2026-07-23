"""Structural regression tests for the branded shared shell (base.html).

These assert that branded markup and local assets are present and that no
Google Fonts CDN is referenced. Visual polish is verified live, not here.
The shell renders on the login page (extends base.html), so no auth needed.
"""
import pytest

from app import create_app
from app.extensions import db
from app.auth.models import User
from config import Config


def _app():
    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    return create_app(TestConfig)


@pytest.fixture
def logged_in_client(tmp_path):
    """A Flask test client logged in as a coach (pattern from tests/test_home.py)."""
    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 't.db'}"

    app = create_app(TestConfig)
    with app.app_context():
        u = User(email="c@lmu.edu", name="Coach C", role="coach")
        u.set_password("x")
        db.session.add(u)
        db.session.commit()

    client = app.test_client()
    client.post("/login", data={"email": "c@lmu.edu", "password": "x"},
                follow_redirects=True)
    return client


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


def test_shell_loads_alfa_slab_locally_not_cdn():
    body = _app().test_client().get("/login").get_data(as_text=True)
    assert "/static/brand/AlfaSlabOne-Regular.ttf" in body
    assert "fonts.googleapis.com" not in body
    assert "fonts.gstatic.com" not in body


def test_shell_uses_brand_colors():
    body = _app().test_client().get("/login").get_data(as_text=True)
    assert "#9A0021" in body   # crimson (darker; coaches preferred it over #AB0C2F)
    assert "#0076A5" in body   # official LMU Blue


def test_shell_index_string_has_brand():
    from app.dashboards import shell
    s = shell.index_string()
    assert "#f5f5f5" in s
    assert "palms-grey.png" in s
    assert "/static/reports/lion.png" in s
    assert "Teko-Regular.ttf" in s


def test_shell_constants():
    from app.dashboards import shell
    assert shell.CRIMSON == "#9A0021"
    assert shell.BANNER == "rgba(154,0,33,0.82)"


def test_section_hubs_render_and_link(logged_in_client):
    # Home cards now point at the hubs.
    home = logged_in_client.get("/")
    assert home.status_code == 200
    assert b'href="/pitching"' in home.data
    assert b'href="/hitting"' in home.data

    # Pitching hub lists its two actions.
    ph = logged_in_client.get("/pitching")
    assert ph.status_code == 200
    assert b"/dash/pitching/" in ph.data           # Stats Dashboard
    assert b"/reports/pitching" in ph.data          # Postgame Reports

    # Hitting hub: Stats Dashboard live, HitTrax practice "Coming soon".
    hh = logged_in_client.get("/hitting")
    assert hh.status_code == 200
    assert b"/dash/hitting/" in hh.data
    assert b"Coming soon" in hh.data

    # Catching hub: Stats Dashboard live.
    ch = logged_in_client.get("/catching")
    assert ch.status_code == 200
    assert b"/dash/catching/" in ch.data
    assert b"Coming soon" not in ch.data
