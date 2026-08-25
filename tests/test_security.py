"""Security regression tests. MUST stay DB-free -- this file is the CI subset."""
import importlib
import pytest


def _reload_config(monkeypatch, **env):
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    import config
    return importlib.reload(config)


@pytest.fixture(scope="module", autouse=True)
def _restore_config_after_module():
    """importlib.reload() mutates the config module in place. When a reload
    raises partway through (e.g. the missing-SECRET_KEY-in-production test),
    names defined before the raise get rebound but later ones (like Config)
    keep their value from the previous successful reload, leaving `config`
    in a state that never actually existed. Nothing today reads config.*
    dynamically so that's safe by absence of coupling, not by design -- so
    reload once more after all tests in this module have run. By then every
    function-scoped monkeypatch has already torn down and restored the real
    environment, so this reload puts `config` back to matching reality for
    whatever test file runs next."""
    yield
    import config
    importlib.reload(config)


@pytest.fixture(autouse=True)
def _dummy_db_env(monkeypatch):
    for k in ("MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_HOST", "MYSQL_DB"):
        monkeypatch.setenv(k, "x")


def test_is_production_false_when_paw_env_unset(monkeypatch):
    cfg = _reload_config(monkeypatch, PAW_ENV=None, SECRET_KEY="x")
    assert cfg.is_production() is False


def test_is_production_true_only_for_exact_production_value(monkeypatch):
    cfg = _reload_config(monkeypatch, PAW_ENV="production", SECRET_KEY="x")
    assert cfg.is_production() is True


@pytest.mark.parametrize(
    "value, expected",
    [
        ("Production", True),   # normalization is intentional -- fails secure
        ("PRODUCTION", True),
        (" production ", True),
        ("prod", False),        # near-miss: must NOT count as production
        ("development", False),
        ("", False),
    ],
)
def test_is_production_boundary(monkeypatch, value, expected):
    cfg = _reload_config(monkeypatch, PAW_ENV=value, SECRET_KEY="x")
    assert cfg.is_production() is expected


def test_render_env_var_alone_does_not_mean_production(monkeypatch):
    """RENDER is already set on the live host; keying off it would activate
    the boot guard on merge and could take the site down."""
    cfg = _reload_config(monkeypatch, PAW_ENV=None, RENDER="true", SECRET_KEY="x")
    assert cfg.is_production() is False


def test_missing_secret_key_in_production_raises(monkeypatch):
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        _reload_config(monkeypatch, PAW_ENV="production", SECRET_KEY=None)


def test_missing_secret_key_outside_production_uses_dev_default(monkeypatch):
    cfg = _reload_config(monkeypatch, PAW_ENV=None, SECRET_KEY=None)
    assert cfg.Config.SECRET_KEY == "dev-only-change-me"


from datetime import timedelta


def test_session_cookie_is_httponly_and_lax(monkeypatch):
    cfg = _reload_config(monkeypatch, PAW_ENV=None, SECRET_KEY="x")
    assert cfg.Config.SESSION_COOKIE_HTTPONLY is True
    assert cfg.Config.SESSION_COOKIE_SAMESITE == "Lax"


def test_session_cookie_not_secure_outside_production(monkeypatch):
    """Secure cookies over plain HTTP are silently dropped by the browser,
    which would make local dev and a pre-certificate Lightsail box unloggable."""
    cfg = _reload_config(monkeypatch, PAW_ENV=None, SECRET_KEY="x")
    assert cfg.Config.SESSION_COOKIE_SECURE is False


def test_session_cookie_secure_in_production(monkeypatch):
    cfg = _reload_config(monkeypatch, PAW_ENV="production", SECRET_KEY="x")
    assert cfg.Config.SESSION_COOKIE_SECURE is True


def test_session_lifetime_is_thirty_days_sliding(monkeypatch):
    cfg = _reload_config(monkeypatch, PAW_ENV=None, SECRET_KEY="x")
    assert cfg.Config.PERMANENT_SESSION_LIFETIME == timedelta(days=30)
    assert cfg.Config.SESSION_REFRESH_EACH_REQUEST is True


def test_wsgi_app_is_wrapped_in_proxyfix(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x")
    from werkzeug.middleware.proxy_fix import ProxyFix
    from app import create_app
    from config import Config

    class T(Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = "sqlite://"

    server = create_app(T)
    assert isinstance(server.wsgi_app, ProxyFix)


# --------------------------------------------------------------------------
# Behavioral coverage: the tests above only assert Config constants, which
# would still pass even if the before_request hook that sets
# `session.permanent = True` silently stopped firing (the config values are
# source-code literals, not proof the running app applies them). These tests
# issue a real request through a test client, log a user in so a session
# cookie is actually written, and inspect the real Set-Cookie header.
# --------------------------------------------------------------------------

def _set_cookie_header(resp, name="session"):
    for h in resp.headers.getlist("Set-Cookie"):
        if h.startswith(f"{name}="):
            return h
    raise AssertionError(f"No Set-Cookie header found for cookie {name!r}")


def _make_login_app(monkeypatch, **env):
    """Build a real app (DB-free w.r.t. MySQL -- app DB is a throwaway sqlite
    file) and seed one user, mirroring tests/test_auth.py's `app` fixture, so
    a session cookie can be issued by actually POSTing to /login."""
    import os
    import tempfile

    cfg = _reload_config(monkeypatch, SECRET_KEY="test-secret", **env)
    from app import create_app
    from app.auth.models import User
    from app.extensions import db

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    class T(cfg.Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = "sqlite:///" + path.replace("\\", "/")

    application = create_app(T)
    with application.app_context():
        user = User(email="cookie@lmu.edu", name="Cookie Test", role="coach")
        user.set_password("pw")
        db.session.add(user)
        db.session.commit()
    return application, path


def _dispose_login_app(application, path):
    import os
    from app.extensions import db

    with application.app_context():
        db.session.remove()
        db.engine.dispose()
    try:
        os.remove(path)
    except PermissionError:
        pass  # Windows may still hold the handle briefly; temp file is harmless


def test_session_set_cookie_header_is_httponly_lax_and_permanent(monkeypatch):
    """Proves the before_request hook actually fires: a non-permanent session
    emits no Expires/Max-Age at all, so their presence here is the signal."""
    application, path = _make_login_app(monkeypatch, PAW_ENV=None)
    try:
        client = application.test_client()
        resp = client.post("/login", data={"email": "cookie@lmu.edu", "password": "pw"})
        cookie = _set_cookie_header(resp)
        assert "HttpOnly" in cookie
        assert "SameSite=Lax" in cookie
        assert ("Expires=" in cookie) or ("Max-Age=" in cookie)
        assert "Secure" not in cookie
    finally:
        _dispose_login_app(application, path)


def test_session_set_cookie_header_is_secure_in_production(monkeypatch):
    application, path = _make_login_app(monkeypatch, PAW_ENV="production")
    try:
        client = application.test_client()
        resp = client.post("/login", data={"email": "cookie@lmu.edu", "password": "pw"})
        cookie = _set_cookie_header(resp)
        assert "Secure" in cookie
    finally:
        _dispose_login_app(application, path)


# --------------------------------------------------------------------------
# Response security headers (app/security.py)
# --------------------------------------------------------------------------

def _client(monkeypatch, paw_env=None):
    if paw_env:
        monkeypatch.setenv("PAW_ENV", paw_env)
    else:
        monkeypatch.delenv("PAW_ENV", raising=False)
    monkeypatch.setenv("SECRET_KEY", "x")
    import config
    importlib.reload(config)
    import app as app_pkg
    importlib.reload(app_pkg)

    class T(config.Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = "sqlite://"

    return app_pkg.create_app(T).test_client()


def test_baseline_headers_present_on_login_page(monkeypatch):
    resp = _client(monkeypatch).get("/login")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "Permissions-Policy" in resp.headers


def test_csp_is_report_only_never_enforced(monkeypatch):
    """An enforced CSP breaks all seven Dash dashboards (inline scripts from
    dash_renderer, inline styles from Plotly)."""
    resp = _client(monkeypatch).get("/login")
    assert "Content-Security-Policy-Report-Only" in resp.headers
    assert "Content-Security-Policy" not in resp.headers


def test_hsts_absent_outside_production(monkeypatch):
    resp = _client(monkeypatch).get("/login")
    assert "Strict-Transport-Security" not in resp.headers


def test_hsts_present_in_production(monkeypatch):
    resp = _client(monkeypatch, paw_env="production").get("/login")
    assert "max-age=" in resp.headers["Strict-Transport-Security"]
