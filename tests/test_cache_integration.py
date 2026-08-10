"""Phase 5 caching applied to the caps read layer (live DB)."""
import pandas as pd

from app.data import hitting_caps as HC, cache

WADAS = 806253


def _query_spy(monkeypatch, module):
    """Count query_df calls on `module`, delegating to the real implementation."""
    calls = []
    real = module.query_df

    def spy(sql, params=None):
        calls.append(1)
        return real(sql, params)

    monkeypatch.setattr(module, "query_df", spy)
    return calls


def test_sibling_ids_memoized(monkeypatch):
    cache.clear_all()
    calls = _query_spy(monkeypatch, HC)
    a = HC._sibling_ids(WADAS)
    n1 = len(calls)
    b = HC._sibling_ids(WADAS)
    assert a == b and len(calls) == n1        # 2nd call: served from cache
    cache.clear_all()
    HC._sibling_ids(WADAS)
    assert len(calls) > n1                     # clear_all re-arms


def test_season_pitches_cached_and_copied(monkeypatch):
    cache.clear_all()
    calls = _query_spy(monkeypatch, HC)
    a = HC.season_pitches(WADAS)
    n1 = len(calls)
    assert n1 > 0 and not a.empty
    b = HC.season_pitches(WADAS)
    assert len(calls) == n1                    # 2nd call: no new queries
    assert a.equals(b)
    # copy-on-hit: mutating a returned frame can't corrupt the cached value
    a.loc[a.index[0], "PitchNo"] = -999
    c = HC.season_pitches(WADAS)
    assert (c["PitchNo"] != -999).all()
    cache.clear_all()
    HC.season_pitches(WADAS)
    assert len(calls) > n1                      # re-queried after clear


def test_bip_points_list_arg_cache_key(monkeypatch):
    cache.clear_all()
    games = HC.games_for_batter(WADAS)
    gids = [int(g) for g in games["game_id"][:2]]
    calls = _query_spy(monkeypatch, HC)
    HC.bip_points(WADAS, gids)
    n1 = len(calls)
    HC.bip_points(WADAS, list(gids))            # same list value -> cache hit
    assert len(calls) == n1
    HC.bip_points(WADAS, gids[:1])              # different list -> miss
    assert len(calls) > n1


def test_rebuild_clears_read_cache(monkeypatch):
    """rebuild_hitting invalidates the in-process read cache (no real rebuild:
    stub the expensive bits, just prove clear_all is invoked)."""
    from app.data import precalc, hitting_caps
    cleared = []
    monkeypatch.setattr(cache, "clear_all", lambda: cleared.append(1))
    monkeypatch.setattr(hitting_caps, "lmu_hitters",
                        lambda season=None: pd.DataFrame({"BatterId": []}))
    monkeypatch.setattr(precalc, "ensure_tables", lambda engine=None: None)
    monkeypatch.setattr(precalc, "_replace_rows", lambda e, t, r: len(r))
    precalc.rebuild_hitting(engine=object())
    assert cleared                              # clear_all was called
