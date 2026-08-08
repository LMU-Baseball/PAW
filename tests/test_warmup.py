"""Startup cache warm-up."""
from app import warmup
from app.data import hitting_caps as H, cache


def test_warm_caches_populates_roster_cache(monkeypatch):
    """After warm_caches(), the roster read is a cache hit (no new query)."""
    cache.clear_all()
    calls = []
    real = H.query_df
    monkeypatch.setattr(H, "query_df", lambda sql, params=None: (calls.append(1), real(sql, params))[1])
    warmup.warm_caches()
    n = len(calls)
    H.lmu_hitters()                 # warmed -> served from cache
    assert len(calls) == n


def test_warm_caches_never_raises(monkeypatch):
    """A warm failure must not propagate (startup must not crash)."""
    monkeypatch.setattr(H, "lmu_hitters", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    warmup.warm_caches()            # swallowed by _safe -> no raise


def test_create_app_warms_only_with_flag(monkeypatch):
    from app import create_app
    called = {"n": 0}
    monkeypatch.setattr("app.warmup.start_warm_thread",
                        lambda: called.__setitem__("n", called["n"] + 1))
    monkeypatch.delenv("PAW_WARM_CACHE", raising=False)
    create_app()
    assert called["n"] == 0         # no flag -> no warm thread
    monkeypatch.setenv("PAW_WARM_CACHE", "1")
    create_app()
    assert called["n"] == 1         # flag set -> warm thread started
