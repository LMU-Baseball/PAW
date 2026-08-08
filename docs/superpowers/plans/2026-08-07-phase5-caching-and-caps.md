# Phase 5 — Caching + round-trip reduction + PA crash-guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (inline, full-suite gate at the end). Steps use checkbox (`- [ ]`) syntax.

**Goal:** Cut RDS round-trips (memoize sibling lookups + cache heavy CAPS reads, cleared on rebuild) so cold tab loads fire ~1 sibling round-trip instead of ~5 and repeat selections are instant; and make `all_pas_figure` incapable of crashing on an oversized df.

**Architecture:** A new `app/data/cache.py` provides a `@cached` decorator (hashable-normalized arg key, DataFrame copy-on-hit) with a global registry and `clear_all()`. Apply it to the sibling-id resolvers and the heavy read functions in the three `_caps` modules. `precalc.rebuild_*` calls `clear_all()`. `all_pas_figure` caps to the most-recent N PAs internally.

**Tech Stack:** Python, functools, pandas, pytest.

## Global Constraints

- **Return shapes unchanged**; callers untouched.
- **Correctness independent of cache:** a cache miss recomputes identically; `clear_all()` fully re-arms.
- **Copy-on-hit for DataFrames** so a caller mutating a returned frame cannot corrupt the cached value.
- **Invalidation:** `precalc.rebuild_*` → `cache.clear_all()`. Per-process only; multi-worker/cron cross-process invalidation is explicitly deferred (offseason, static data).
- `_MAX_PA_SUBPLOTS = 12` (matches the tab's existing cap).
- Keep the full suite green (611 as of `841b9f5`).

---

### Task 1: `app/data/cache.py` — the `@cached` decorator

**Files:** Create `app/data/cache.py`; Test `tests/test_cache.py`.

**Interfaces:** `cache.cached(fn)` → memoized wrapper (keys on normalized args+kwargs; copies DataFrame results on return). `cache.clear_all()` empties every registered store.

- [ ] **Step 1: failing tests** (`tests/test_cache.py`):

```python
import pandas as pd
from app.data import cache

def test_cached_memoizes_by_args_and_clear_rearms():
    calls = []
    @cache.cached
    def f(x):
        calls.append(x); return x * 2
    assert f(3) == 6 and f(3) == 6
    assert calls == [3]              # second call served from cache
    assert f(4) == 8 and calls == [3, 4]
    cache.clear_all()
    assert f(3) == 6 and calls == [3, 4, 3]   # re-armed

def test_cached_normalizes_list_args():
    calls = []
    @cache.cached
    def g(bid, games):
        calls.append((bid, tuple(games))); return len(games)
    assert g(1, [10, 11]) == 2 and g(1, [10, 11]) == 2
    assert len(calls) == 1           # list normalized to a hashable key
    assert g(1, [10]) == 1 and len(calls) == 2

def test_cached_dataframe_is_copied_on_hit():
    @cache.cached
    def h(x):
        return pd.DataFrame({"a": [1, 2]})
    d1 = h(1); d1.loc[0, "a"] = 999   # mutate the returned frame
    d2 = h(1)
    assert d2.loc[0, "a"] == 1        # cache value untouched
```

- [ ] **Step 2:** Run → FAIL (module absent).
- [ ] **Step 3:** Implement:

```python
"""Process-lifetime memo cache for expensive CAPS reads (Phase 5).

Per-process only; cleared by precalc.rebuild_* via clear_all(). Cross-process
(multi-worker/cron) invalidation is deferred with the cron build -- offseason
data is static.
"""
from __future__ import annotations
import functools
import pandas as pd

_STORES: list[dict] = []

def _norm(v):
    if isinstance(v, (list, tuple)):
        return tuple(_norm(x) for x in v)
    return v

def cached(fn):
    store: dict = {}
    _STORES.append(store)
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        key = (tuple(_norm(a) for a in args),
               tuple(sorted((k, _norm(v)) for k, v in kwargs.items())))
        if key not in store:
            store[key] = fn(*args, **kwargs)
        val = store[key]
        return val.copy() if isinstance(val, pd.DataFrame) else val
    wrapper.cache_clear = store.clear   # per-fn clear, handy in tests
    return wrapper

def clear_all() -> None:
    for s in _STORES:
        s.clear()
```

- [ ] **Step 4:** Run → PASS. **Step 5:** Commit `feat(cache): process-lifetime @cached decorator + clear_all`.

### Task 2: Memoize the sibling-id resolvers

**Files:** `app/data/hitting_caps.py` (`_sibling_ids`), `app/data/pitching_caps.py` (`_sibling_pitcher_ids`), `app/data/catching_caps.py` (`_sibling_catcher_ids`); Test `tests/test_cache_integration.py`.

- [ ] **Step 1: failing test** — patch `query_df` in `hitting_caps` to count calls; two `_sibling_ids(WADAS)` calls issue **one** query; `cache.clear_all()` re-arms.

```python
def test_sibling_ids_memoized(monkeypatch):
    from app.data import hitting_caps as HC, cache
    cache.clear_all()
    real = HC.query_df; calls = []
    def spy(sql, params=None):
        calls.append(1); return real(sql, params)
    monkeypatch.setattr(HC, "query_df", spy)
    a = HC._sibling_ids(806253); n1 = len(calls)
    b = HC._sibling_ids(806253)
    assert a == b and len(calls) == n1     # 2nd call: no new query
    cache.clear_all()
    HC._sibling_ids(806253); assert len(calls) > n1
```

- [ ] **Step 2:** Run → FAIL (not memoized). **Step 3:** Add `from app.data.cache import cached` and decorate each resolver with `@cached`. **Step 4:** Run → PASS. **Step 5:** Commit `feat(cache): memoize sibling-id resolvers (kills redundant per-call round-trips)`.

### Task 3: Cache the heavy CAPS read functions

**Files:** `hitting_caps.py` (`game_pitches`, `season_pitches`, `range_pitches`, `games_for_batter`, `bip_points`, `last_n_pas`), `pitching_caps.py` (`range_pitches_for`, `games_for_pitcher`, `game_pitches_for`, `recent_outings`, `velo_trend`), `catching_caps.py` (`game_pitches_for`, `range_pitches_for`, `games_for_catcher`); Test `tests/test_cache_integration.py`.

- [ ] **Step 1: failing test** — two `season_pitches(WADAS)` calls issue one query (query-count spy), results equal, and mutating the first returned frame doesn't change the second; `clear_all()` re-queries.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Decorate each listed function with `@cached`. (They already return fresh frames; copy-on-hit guards callers.) Leave precalc readers + scalar helpers uncached. **Step 4:** Run → PASS. **Step 5:** Commit `feat(cache): cache heavy CAPS reads (instant repeat selections)`.

### Task 4: Invalidate on rebuild

**Files:** `app/data/precalc.py`; Test `tests/test_precalc.py`.

- [ ] **Step 1: failing test** — prime the cache (`hitting_caps.season_pitches(WADAS)`), then `precalc.rebuild_hitting(get_engine())`, then assert a subsequent `season_pitches` call re-queries (query-count spy) — i.e. rebuild emptied the read cache.
- [ ] **Step 2:** Run → FAIL. **Step 3:** In `precalc._replace_rows` (or at the end of each `rebuild_*`), call `from app.data import cache; cache.clear_all()` after the write commits. **Step 4:** Run → PASS. **Step 5:** Commit `feat(cache): rebuild-precalc clears the in-process read cache`.

### Task 5: Crash-guard `all_pas_figure`

**Files:** `app/dashboards/hitting/charts.py`; Test `tests/test_hitting_charts.py` (or the existing charts test).

- [ ] **Step 1: failing test** — build a synthetic df with, say, 30 distinct `(GameID, Inning, PAofInning)` PAs; `all_pas_figure(df)` returns a Figure (does not raise) and renders exactly `_MAX_PA_SUBPLOTS` PAs.

```python
def test_all_pas_figure_caps_and_never_crashes():
    import pandas as pd
    from app.dashboards.hitting import charts
    rows = []
    for g in range(30):  # 30 PAs across fake games -> would be 10-row subplots+
        rows.append({"GameID": g, "Inning": 1, "PAofInning": 1, "PitchofPA": 1,
                     "TaggedPitchType": "Fastball", "PlateLocSide": 0.0,
                     "PlateLocHeight": 2.5, "PitchCall": "StrikeCalled",
                     "PlayResult": "Undefined"})
    fig = charts.all_pas_figure(pd.DataFrame(rows))
    assert fig is not None
    # exactly _MAX_PA_SUBPLOTS PA subplots (annotations = subplot titles)
    assert len([a for a in fig.layout.annotations]) == charts._MAX_PA_SUBPLOTS
```

(Confirm the title/annotation count assertion against how `make_subplots` names titles; adjust to a robust check — e.g. count distinct xaxes — if annotations include extras.)

- [ ] **Step 2:** Run → FAIL (raises `ValueError` on too many rows). **Step 3:** Add `_MAX_PA_SUBPLOTS = 12`; in `all_pas_figure`, after computing `pa_keys`, if `len(pa_keys) > _MAX_PA_SUBPLOTS` keep `pa_keys[-_MAX_PA_SUBPLOTS:]` (most recent) before building. **Step 4:** Run → PASS; existing charts tests green. **Step 5:** Commit `fix(charts): cap all_pas_figure to _MAX_PA_SUBPLOTS PAs (defense-in-depth, no crash)`.

---

## Post-plan verification

- [ ] `pytest -q` green (611 + new cache/charts tests).
- [ ] Re-run the Phase 5 profiler: a cold hitting tab's read functions issue ~1 sibling round-trip total; a warm repeat of the same selection is ~0 ms (cache hit). Capture before/after.
- [ ] Live: restart dev server; navigate hitting games/tabs — visibly snappier on repeat selection; no crash when a large range is selected.
- [ ] `test_no_warehouse_refs` + `flask rebuild-precalc` still green/working.

## Self-review notes

- **Spec coverage:** lever 1 = Task 2, lever 2 = Tasks 1+3+4, lever 3 = Task 5.
- **Placeholders:** the Task 5 annotation-count assertion carries an explicit "confirm/adjust" note — the executor verifies the robust check against real `make_subplots` output.
- **Risk:** copy-on-hit prevents aliasing; `clear_all` on rebuild prevents cross-epoch staleness in-process; the deferred cross-process invalidation is documented, not silently ignored.
