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
