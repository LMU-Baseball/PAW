"""Phase 5 @cached decorator (pure, no DB)."""
import pandas as pd

from app.data import cache


def test_cached_memoizes_by_args_and_clear_rearms():
    calls = []

    @cache.cached
    def f(x):
        calls.append(x)
        return x * 2

    assert f(3) == 6 and f(3) == 6
    assert calls == [3]                     # second call served from cache
    assert f(4) == 8 and calls == [3, 4]
    cache.clear_all()
    assert f(3) == 6 and calls == [3, 4, 3]  # re-armed after clear_all


def test_cached_normalizes_list_args():
    calls = []

    @cache.cached
    def g(bid, games):
        calls.append((bid, tuple(games)))
        return len(games)

    assert g(1, [10, 11]) == 2 and g(1, [10, 11]) == 2
    assert len(calls) == 1                  # list normalized to a hashable key
    assert g(1, [10]) == 1 and len(calls) == 2


def test_cached_dataframe_is_copied_on_hit():
    @cache.cached
    def h(x):
        return pd.DataFrame({"a": [1, 2]})

    d1 = h(1)
    d1.loc[0, "a"] = 999                    # mutate the returned frame
    d2 = h(1)
    assert d2.loc[0, "a"] == 1              # cached value untouched


def test_maybe_invalidate_version_gate(monkeypatch):
    calls = {"clear": 0, "reads": 0}
    monkeypatch.setattr(cache, "clear_all",
                        lambda: calls.__setitem__("clear", calls["clear"] + 1))
    seq = iter([1, 2])                       # baseline 1, then a bump to 2

    def reader():
        calls["reads"] += 1
        return next(seq)

    cache.configure(version_reader=reader, ttl=10.0)
    cache.maybe_invalidate(now=100.0)        # first read -> v=1 baseline, no clear
    assert calls == {"clear": 0, "reads": 1}
    cache.maybe_invalidate(now=105.0)        # within ttl -> reader NOT called
    assert calls == {"clear": 0, "reads": 1}
    cache.maybe_invalidate(now=120.0)        # ttl elapsed, v=2 != 1 -> clear
    assert calls == {"clear": 1, "reads": 2}
    cache.configure(version_reader=None)     # reset (autouse also resets)


def test_maybe_invalidate_noop_without_reader():
    cache.configure(version_reader=None)
    cache.maybe_invalidate(now=0.0)          # must not raise / do anything


def test_precalc_season_reads_are_memoized(monkeypatch):
    """precalc.read_hitting_season / read_pitching_season are @cached: a repeat
    (id, season) read serves from cache with no second DB round trip. These
    were previously always-uncached single-row reads paid on every open."""
    from app.data import precalc
    cache.clear_all()
    hcalls, pcalls = [], []

    def fake_query(sql, params=None):
        (hcalls if "batter_id" in sql else pcalls).append(1)
        return pd.DataFrame([{
            "batter_id": 1, "pitcher_id": 1, "season_label": "2025/2026",
            "qab_pct": 0.42, "ba": ".300", "slg": ".500", "obp": ".400",
        }])

    monkeypatch.setattr(precalc, "query_df", fake_query)
    precalc.read_hitting_season(1, "2025/2026")
    precalc.read_hitting_season(1, "2025/2026")
    assert len(hcalls) == 1                   # hitting read memoized
    precalc.read_pitching_season(1, "2025/2026")
    precalc.read_pitching_season(1, "2025/2026")
    assert len(pcalls) == 1                   # pitching read memoized
