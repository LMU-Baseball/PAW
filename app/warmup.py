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
    from app.data import hitting_caps as H, pitching_caps as P
    from app.data import catching_caps as C, video, seasons

    _safe(seasons.available_seasons)          # Season dropdown options
    season = _safe(seasons.current_season)    # dropdown default
    if not season:
        return
    s_b, e_b = seasons.season_bounds(season)

    hitters = _safe(lambda: H.lmu_hitters(season))
    if hitters is not None and not hitters.empty:
        bid = int(hitters.iloc[0]["BatterId"])
        g = _safe(lambda: H.games_for_batter(bid, s_b, e_b))
        _safe(lambda: H.sidebar_stats(bid, season))
        _safe(lambda: H.player_profile(bid))
        if g is not None and not g.empty:
            _safe(lambda: video.video_game_ids(g, batter_id=bid))
            gid = str(g.iloc[0]["game_id"])  # default (most-recent) game; opaque id
            _safe(lambda: H.game_pitches(gid, bid))  # default tab's game-data

    pitchers = _safe(lambda: P.lmu_pitchers(season))
    if pitchers is not None and not pitchers.empty:
        pid = int(pitchers.iloc[0]["PitcherId"])
        g = _safe(lambda: P.games_for_pitcher(pid, s_b, e_b))
        _safe(lambda: P.pitcher_profile(pid))
        _safe(lambda: P.range_summary(pid, s_b, e_b))  # season-bounds sidebar read
        if g is not None and not g.empty:
            _safe(lambda: video.video_game_ids(g, pitcher_id=pid))
            gid = str(g.iloc[0]["game_id"])
            _safe(lambda: P.game_pitches_for(gid, pid))

    catchers = _safe(lambda: C.lmu_catchers(season))
    if catchers is not None and not catchers.empty:
        cid = int(catchers.iloc[0]["CatcherId"])
        g = _safe(lambda: C.games_for_catcher(cid, s_b, e_b))
        _safe(lambda: C.catcher_profile(cid))
        _safe(lambda: C.framing_season_tiles(cid, season))
        if g is not None and not g.empty:
            _safe(lambda: video.video_game_ids(g, catcher_id=cid))
            gid = str(g.iloc[0]["game_id"])
            _safe(lambda: C.game_pitches_for(gid, cid))

    # Velo Board + Competitive Cauldron. These two boards were added after the
    # original warm set and carry the SAME first-open cost the others do: a
    # per-rostered-pitcher fan of Trackman round-trips (velo leaderboard) and a
    # per-pitcher/day compute (cauldron grid), each ~0.5s to RDS. Warming them
    # here is what makes them open instantly instead of cold-loading. The exact
    # (season, week, cycle, play_date) keys mirror what serve_layout defaults to
    # so the warmed @cached entries actually hit.
    from datetime import date
    from app.data import velo_board, cauldron

    _safe(lambda: velo_board.leaderboard(season))     # player-facing heat board
    # Default week = the layout's _default_week(season): today's week while the
    # season is live, else its final week (offseason). Kept in sync with
    # velo_board/layout.py::_default_week.
    today = date.today().isoformat()
    anchor = min(today, e_b)
    if anchor < s_b:
        anchor = s_b
    week = _safe(lambda: velo_board.week_start_for(anchor))
    if week:
        _safe(lambda: velo_board.grid_rows(season, week))  # coach grid prefill

    cycle = f"{season}-c1"
    _safe(cauldron.read_scoring)
    _safe(lambda: cauldron.read_teams(cycle))
    _safe(cauldron.read_daily)
    if pitchers is not None and not pitchers.empty:
        from app.dashboards.cauldron import grid as cauldron_grid
        _safe(lambda: cauldron_grid._grid_rows(
            pitchers, cauldron.read_scoring(), cauldron.read_teams(cycle),
            cauldron.read_daily(today), today))            # coach grid prefill


def start_warm_thread() -> threading.Thread:
    """Run warm_caches() in a daemon thread so it never blocks startup."""
    t = threading.Thread(target=warm_caches, name="cache-warmup", daemon=True)
    t.start()
    return t
