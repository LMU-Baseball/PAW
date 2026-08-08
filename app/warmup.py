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
    default view. Mirrors what serve_layout queries for the default player."""
    from app.data import hitting_caps as H, pitching_caps as P
    from app.data import catching_caps as C, video

    hitters = _safe(H.lmu_hitters)
    if hitters is not None and not hitters.empty:
        bid = int(hitters.iloc[0]["BatterId"])
        g = _safe(lambda: H.games_for_batter(bid))
        _safe(lambda: H.sidebar_stats(bid))
        _safe(lambda: H.player_profile(bid))
        if g is not None and not g.empty:
            _safe(lambda: video.video_game_ids(g, batter_id=bid))

    pitchers = _safe(P.lmu_pitchers)
    if pitchers is not None and not pitchers.empty:
        pid = int(pitchers.iloc[0]["PitcherId"])
        g = _safe(lambda: P.games_for_pitcher(pid))
        _safe(lambda: P.pitcher_profile(pid))
        if g is not None and not g.empty:
            _safe(lambda: video.video_game_ids(g, pitcher_id=pid))

    catchers = _safe(C.lmu_catchers)
    if catchers is not None and not catchers.empty:
        cid = int(catchers.iloc[0]["CatcherId"])
        g = _safe(lambda: C.games_for_catcher(cid))
        _safe(lambda: C.catcher_profile(cid))
        if g is not None and not g.empty:
            _safe(lambda: video.video_game_ids(g, catcher_id=cid))


def start_warm_thread() -> threading.Thread:
    """Run warm_caches() in a daemon thread so it never blocks startup."""
    t = threading.Thread(target=warm_caches, name="cache-warmup", daemon=True)
    t.start()
    return t
