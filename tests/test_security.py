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
