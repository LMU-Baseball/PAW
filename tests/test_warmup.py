"""Startup cache warm-up."""
from app import warmup
from app.data import hitting_caps as H, cache, seasons


def test_warm_caches_populates_roster_cache(monkeypatch):
    """After warm_caches(), the roster read is a cache hit (no new query).
    warm_caches scopes to the current season, so the hit is on the same
    season-keyed call."""
    cache.clear_all()
    calls = []
    real = H.query_df
    monkeypatch.setattr(H, "query_df", lambda sql, params=None: (calls.append(1), real(sql, params))[1])
    warmup.warm_caches()
    n = len(calls)
    H.lmu_hitters(seasons.current_season())   # warmed -> served from cache
    assert len(calls) == n


def test_warm_caches_warms_range_scoped_roster_and_new_reads(monkeypatch):
    """Layer-1: warm_caches also populates the range-scoped roster variant and
    the newly-cached always-uncached reads (scoreboard / read_hitting_season)
    for the default view, so a cold open pays ~1 uncached round trip, not 3-4."""
    cache.clear_all()
    warmup.warm_caches()

    season = seasons.current_season()
    s_b, e_b = seasons.season_bounds(season)

    calls = []
    real = H.query_df
    monkeypatch.setattr(H, "query_df",
                        lambda sql, params=None: (calls.append(1), real(sql, params))[1])

    # the season-default DATE-RANGE-scoped roster (a distinct key from the
    # unscoped one) is warmed -> no new query.
    H.lmu_hitters(season, s_b, e_b)
    assert len(calls) == 0

    # scoreboard + precalc read for the default (batter, game) are warmed too.
    hitters = H.lmu_hitters(season)
    if hitters is not None and not hitters.empty:
        bid = int(hitters.iloc[0]["BatterId"])
        from app.data import precalc
        pcalls = []
        realp = precalc.query_df
        monkeypatch.setattr(precalc, "query_df",
                            lambda sql, params=None: (pcalls.append(1), realp(sql, params))[1])
        precalc.read_hitting_season(bid, season)
        assert len(pcalls) == 0                 # season rollup read warmed

        g = H.games_for_batter(bid, s_b, e_b)
        if g is not None and not g.empty:
            gid = str(g.iloc[0]["game_id"])
            calls.clear()
            H.scoreboard(gid)
            assert len(calls) == 0              # scoreboard warmed


def test_warm_caches_warms_game_context(monkeypatch):
    """game_context (pitching scoreboard context, shared by catching) is warmed
    for the default pitching game."""
    from app.data import pitching_caps as P
    cache.clear_all()
    warmup.warm_caches()

    season = seasons.current_season()
    s_b, e_b = seasons.season_bounds(season)
    pitchers = P.lmu_pitchers(season)
    if pitchers is None or pitchers.empty:
        return
    pid = int(pitchers.iloc[0]["PitcherId"])
    g = P.games_for_pitcher(pid, s_b, e_b)
    if g is None or g.empty:
        return
    gid = str(g.iloc[0]["game_id"])

    calls = []
    real = P.query_df
    monkeypatch.setattr(P, "query_df",
                        lambda sql, params=None: (calls.append(1), real(sql, params))[1])
    P.game_context(gid)
    assert len(calls) == 0                       # game_context warmed


def test_warm_caches_warms_called_strike_and_xba_lookups(monkeypatch):
    """warm_caches must build called_strike._get_lookup()/xba._get_lookup()
    directly and unconditionally -- these are process-wide singletons that
    used to get built for free as a side effect of slaa_season_tiles's live
    compute path, but now that slaa_season_tiles/sidebar_stats read precalc
    first, that live path (and the warm) is only reached if the precalc row
    is absent, which after a startup rebuild it never is."""
    from app.data import called_strike, xba

    cache.clear_all()
    warmup.warm_caches()

    calls = []
    real_taken = called_strike._raw_taken_pitches
    real_batted = xba._raw_batted_balls
    monkeypatch.setattr(called_strike, "_raw_taken_pitches",
                        lambda: (calls.append("called_strike"), real_taken())[1])
    monkeypatch.setattr(xba, "_raw_batted_balls",
                        lambda: (calls.append("xba"), real_batted())[1])

    called_strike._get_lookup()
    xba._get_lookup()
    assert calls == [], f"expected both lookups already warmed, but re-built: {calls}"


def test_warm_caches_warms_catching_precalc_read(monkeypatch):
    """Symmetry with the hitting/pitching precalc warms: warm_caches also
    warms precalc.read_catching_season for the default catcher/season."""
    from app.data import catching_caps as C, precalc

    cache.clear_all()
    warmup.warm_caches()

    season = seasons.current_season()
    catchers = C.lmu_catchers(season)
    if catchers is None or catchers.empty:
        return
    cid = int(catchers.iloc[0]["CatcherId"])

    pcalls = []
    real = precalc.query_df
    monkeypatch.setattr(precalc, "query_df",
                        lambda sql, params=None: (pcalls.append(1), real(sql, params))[1])
    precalc.read_catching_season(cid, season)
    assert len(pcalls) == 0            # catching season rollup read warmed


def test_warm_caches_never_raises(monkeypatch):
    """A warm failure must not propagate (startup must not crash)."""
    monkeypatch.setattr(H, "lmu_hitters",
                        lambda season=None: (_ for _ in ()).throw(RuntimeError("boom")))
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
