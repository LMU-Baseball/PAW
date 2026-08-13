"""Fan out independent, @cached DB reads concurrently to cut a page's
sequential round-trip latency (Speed Phase 2 / Layer 2).

serve_layout (and each dashboard's sidebar) fire several INDEPENDENT reads that
were written sequentially, so on a cold cache they pay one RDS round trip after
another (~230ms each). The reads are @cached and app.db's engine is a
thread-safe pool, so running them together in a small ThreadPoolExecutor warms
all their caches in ~one round trip; the normal sequential render path then
consumes the warmed values (cache hits, no extra round trips).

Prefetch is BEST-EFFORT: a thunk that raises is ignored -- the sequential code
re-runs the same read and surfaces any real error there -- so a prefetch can
never blank a page. Results are discarded; the point is the warmed cache, not
the return value.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

_MAX_WORKERS = 8


def prefetch(*thunks) -> None:
    """Run each zero-arg callable concurrently, discarding results and errors.

    Use to warm @cached reads in parallel just before the sequential render
    path reads them. With fewer than two thunks there's nothing to overlap, so
    they run inline. `None` thunks are skipped (convenient for conditional
    prefetch lists)."""
    live = [t for t in thunks if t is not None]
    if len(live) < 2:
        for t in live:
            try:
                t()
            except Exception:
                pass
        return
    with ThreadPoolExecutor(max_workers=min(len(live), _MAX_WORKERS)) as ex:
        for f in [ex.submit(t) for t in live]:
            try:
                f.result()
            except Exception:
                pass
