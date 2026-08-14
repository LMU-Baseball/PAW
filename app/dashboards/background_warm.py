"""Fire-and-forget background warming of a just-selected player's heavier reads
(Speed Phase 2 / Layer 3).

When a coach picks a new player from a dashboard's dropdown, the reactive
callbacks load only the DEFAULT game's data. That player's OTHER-tab and
all-in-range reads are @cached but not on the default render path, so they stay
cold until the coach clicks into them. This warms them in a daemon thread the
instant the player is selected, so that 2nd interaction is an instant cache hit.

Best-effort: each thunk's errors are swallowed and it NEVER blocks the callback
(a callback that spawns this returns immediately). The reads are @cached and the
engine is a thread-safe pool, so a warm racing the eventual foreground read at
worst recomputes once -- never a correctness issue."""
from __future__ import annotations

import threading


def warm_async(*thunks) -> None:
    """Run each zero-arg thunk in a background daemon thread, ignoring results
    and errors. Returns immediately (non-blocking). No-op with no thunks."""
    live = [t for t in thunks if t is not None]
    if not live:
        return

    def _run():
        for t in live:
            try:
                t()
            except Exception:
                pass

    threading.Thread(target=_run, name="bg-warm-player", daemon=True).start()
