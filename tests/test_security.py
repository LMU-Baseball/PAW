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
