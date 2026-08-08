"""Process-lifetime memo cache for expensive CAPS reads (Phase 5).

The heavy caps read functions each cost ~1.2s (mostly RDS round-trip), and the
sibling-id resolvers are re-run by nearly every one of them. Memoizing per
process collapses a tab load's redundant round-trips and makes repeat selections
instant.

Per-process only; cleared by precalc.rebuild_* via clear_all() so an in-process
rebuild refreshes the cache. Cross-process (multi-worker / cron) invalidation is
deferred with the cron build -- offseason data is static (no new games until
Fall 2026).
"""
from __future__ import annotations

import functools
import time

import pandas as pd

_STORES: list[dict] = []

# Cross-process invalidation gate (Phase-6 / cron): a separate-process rebuild
# bumps a DB version stamp; web workers poll it (at most once per _ttl) and
# clear when it changes. No-op until configured (tests/scripts).
_version_reader = None
_ttl = 60.0
_seen_version = None
_last_check: float | None = None


def configure(version_reader=None, ttl: float = 60.0) -> None:
    """Install (or clear) the data-version reader used by maybe_invalidate.
    Called at app startup with precalc.read_data_version; version_reader=None
    disables the gate (the default, e.g. in tests/CLI scripts)."""
    global _version_reader, _ttl, _seen_version, _last_check
    _version_reader = version_reader
    _ttl = ttl
    _seen_version = None
    _last_check = None


def maybe_invalidate(now: float | None = None) -> None:
    """If the data version changed since last seen, clear_all(). Polls the
    version at most once per _ttl seconds (≈1 cheap round-trip/worker/minute).
    No-op when no reader is configured."""
    global _seen_version, _last_check
    if _version_reader is None:
        return
    if now is None:
        now = time.monotonic()
    if _last_check is not None and (now - _last_check) < _ttl:
        return
    _last_check = now
    version = _version_reader()
    if _seen_version is not None and version != _seen_version:
        clear_all()
    _seen_version = version


def _norm(v):
    """Normalize an arg to a hashable form (lists/tuples -> tuples, recursively)."""
    if isinstance(v, (list, tuple)):
        return tuple(_norm(x) for x in v)
    return v


def cached(fn):
    """Memoize `fn` by its (normalized) args+kwargs. DataFrame results are copied
    on every hit so a caller mutating the frame can't corrupt the cached value.
    Every decorated fn's store is registered for clear_all()."""
    store: dict = {}
    _STORES.append(store)

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        maybe_invalidate()  # cross-process version gate (no-op unless configured)
        key = (tuple(_norm(a) for a in args),
               tuple(sorted((k, _norm(v)) for k, v in kwargs.items())))
        if key not in store:
            store[key] = fn(*args, **kwargs)
        val = store[key]
        return val.copy() if isinstance(val, pd.DataFrame) else val

    wrapper.cache_clear = store.clear  # per-fn clear (handy in tests)
    return wrapper


def clear_all() -> None:
    """Empty every registered cache (called after a precalc rebuild)."""
    for s in _STORES:
        s.clear()
