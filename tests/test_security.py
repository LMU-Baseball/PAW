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
