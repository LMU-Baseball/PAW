"""Background cache warm-up at server startup.

Every dashboard open runs serve_layout, which queries the roster dropdown, the
default player's games, the video markers, and the sidebar. Those are @cached,
so re-opens are instant -- but the FIRST open per server-uptime otherwise pays
~3.8s to warm them. This pre-loads those caches in a background daemon thread at
startup so even the first open is fast.

Guarded: create_app only starts the thread when PAW_WARM_CACHE is set (run.py
sets it; tests/CLI don't, so they never spawn a thread or hit the DB here).
Every call is wrapped so a warm failure (e.g. DB briefly down) never crashes
startup -- the functions just stay cold and warm lazily on first use.
"""
from __future__ import annotations

import threading


def _safe(fn):
    try:
        return fn()
    except Exception:
        return None


def warm_caches() -> None:
    """Populate the @cached roster/games/video/sidebar reads for each dashboard's
    default view. Mirrors what serve_layout queries for the default player IN THE
    CURRENT SEASON (the dropdown's default), so the warmed cache keys match the
    scoped reads serve_layout actually makes. Also warms the Season dropdown's
    own queries (available_seasons/current_season)."""
    from datetime import date
    from app.data import hitting_caps as H, pitching_caps as P
    from app.data import catching_caps as C, video, seasons, precalc
    from app.data import called_strike, xba

    _safe(seasons.available_seasons)          # Season dropdown options
    # Hitting/Pitching/Catching now default (serve_layout) to TODAY's real
    # calendar season, not seasons.current_season() -- see
    # docs/superpowers/specs/2026-08-25-post-slaa-fixes-design.md §4 and the
    # 2026-08-26 season-default fix. Warm that same value so these cache keys
    # actually match what serve_layout requests.
    season = _safe(lambda: seasons.season_label_for(date.today().isoformat()))
    if not season:
        return
    s_b, e_b = seasons.season_bounds(season)

    hitters = _safe(lambda: H.lmu_hitters(season))
    # The default open scopes the roster to the season-default DATE RANGE, so
    # warm that range-scoped variant too (it's a distinct cache key that was
    # otherwise paid on every open).
    _safe(lambda: H.lmu_hitters(season, s_b, e_b))
    if hitters is not None and not hitters.empty:
        bid = int(hitters.iloc[0]["BatterId"])
        g = _safe(lambda: H.games_for_batter(bid, s_b, e_b))
        _safe(lambda: H.sidebar_stats(bid, season))
        _safe(lambda: H.player_profile(bid))
        _safe(lambda: precalc.read_hitting_season(bid, season))  # always-uncached read
        if g is not None and not g.empty:
            _safe(lambda: video.video_game_ids(g, batter_id=bid))
            gid = str(g.iloc[0]["game_id"])  # default (most-recent) game; opaque id
            _safe(lambda: H.game_pitches(gid, bid))  # default tab's game-data
            _safe(lambda: H.scoreboard(gid))         # hitting scoreboard (now cached)

    pitchers = _safe(lambda: P.lmu_pitchers(season))
    _safe(lambda: P.lmu_pitchers(season, s_b, e_b))
    if pitchers is not None and not pitchers.empty:
        pid = int(pitchers.iloc[0]["PitcherId"])
        g = _safe(lambda: P.games_for_pitcher(pid, s_b, e_b))
        _safe(lambda: P.pitcher_profile(pid))
        _safe(lambda: P.range_summary(pid, s_b, e_b))  # season-bounds sidebar read
        _safe(lambda: precalc.read_pitching_season(pid, season))  # always-uncached read
        if g is not None and not g.empty:
            _safe(lambda: video.video_game_ids(g, pitcher_id=pid))
            gid = str(g.iloc[0]["game_id"])
            _safe(lambda: P.game_pitches_for(gid, pid))
            _safe(lambda: P.game_context(gid))       # pitching scoreboard context (now cached)

    catchers = _safe(lambda: C.lmu_catchers(season))
    _safe(lambda: C.lmu_catchers(season, s_b, e_b))
    # called_strike._get_lookup() (a ~56,537-row GAMES scan) and
    # xba._get_lookup() are process-wide singletons that used to get built here
    # for free as a side effect of slaa_season_tiles's live compute path. Now
    # that slaa_season_tiles (and hitting_caps.sidebar_stats) read precalc
    # FIRST, that live path -- and this warm -- is only reached if the precalc
    # row is somehow absent, which after a startup rebuild it never is. So warm
    # both lookups directly and unconditionally (NOT nested under "does the
    # CURRENT season have a catcher yet" -- a fresh season with zero rows so
    # far must not skip warming a lookup spanning ALL of GAMES history) instead
    # of relying on that side effect, or the first coach to hit a cold precalc
    # row after a restart pays the full scan inline.
    _safe(called_strike._get_lookup)
    _safe(xba._get_lookup)
    if catchers is not None and not catchers.empty:
        cid = int(catchers.iloc[0]["CatcherId"])
        g = _safe(lambda: C.games_for_catcher(cid, s_b, e_b))
        _safe(lambda: C.catcher_profile(cid))
        _safe(lambda: C.framing_season_tiles(cid, season))
        _safe(lambda: C.slaa_season_tiles(cid, season))
        _safe(lambda: precalc.read_catching_season(cid, season))  # always-uncached read
        if g is not None and not g.empty:
            _safe(lambda: video.video_game_ids(g, catcher_id=cid))
            gid = str(g.iloc[0]["game_id"])
            _safe(lambda: C.game_pitches_for(gid, cid))
            _safe(lambda: P.game_context(gid))       # catching scoreboard shares game_context

    # Velo Board + Competitive Cauldron. These two boards were added after the
    # original warm set and carry the SAME first-open cost the others do: a
    # per-rostered-pitcher fan of Trackman round-trips (velo leaderboard) and a
    # per-pitcher/day compute (cauldron grid), each ~0.5s to RDS. Warming them
    # here is what makes them open instantly instead of cold-loading. The exact
    # (season, week, cycle, play_date) keys mirror what serve_layout defaults to
    # so the warmed @cached entries actually hit.
    #
    # Velo Board/Cauldron's OWN default season (serve_layout in both
    # dashboards' layout.py) is today's real calendar season -- same value as
    # `season` above now that hitting/pitching/catching also default there.
    # Kept as a separate name for readability of the block below.
    from app.data import velo_board, cauldron

    today = date.today().isoformat()
    board_season = season

    _safe(lambda: velo_board.leaderboard(board_season))  # player-facing heat board
    # Default week = the layout's _default_week(board_season): today's week
    # while the season is live, else its final week (offseason). Kept in sync
    # with velo_board/layout.py::_default_week.
    board_s_b, board_e_b = seasons.season_bounds(board_season)
    anchor = min(today, board_e_b)
    if anchor < board_s_b:
        anchor = board_s_b
    week = _safe(lambda: velo_board.week_start_for(anchor))
    if week:
        _safe(lambda: velo_board.board_rows(board_season, week))  # unified board rows

    cycle = f"{board_season}-c1"
    _safe(cauldron.read_scoring)
    _safe(lambda: cauldron.read_teams(cycle))
    _safe(cauldron.read_daily)
    # cauldron/grid.py::coach_grid() resolves its own roster as
    # pitching_caps.lmu_pitchers(season) using the SAME board_season layout.py
    # now passes in -- warm that exact roster key, not the current_season()-
    # scoped `pitchers` fetched above for the pitching dashboard's own warming.
    board_pitchers = _safe(lambda: P.lmu_pitchers(board_season))
    if board_pitchers is not None and not board_pitchers.empty:
        from app.dashboards.cauldron import grid as cauldron_grid
        _safe(lambda: cauldron_grid._grid_rows(
            board_pitchers, cauldron.read_scoring(), cauldron.read_teams(cycle),
            cauldron.read_daily(today), today))            # coach grid prefill


def start_warm_thread() -> threading.Thread:
    """Run warm_caches() in a daemon thread so it never blocks startup."""
    t = threading.Thread(target=warm_caches, name="cache-warmup", daemon=True)
    t.start()
    return t
