"""prefetch() fan-out helper (pure, no DB)."""
import threading

from app.data import parallel


def test_prefetch_runs_all_thunks_concurrently():
    """A 3-party barrier only releases if all three thunks are in flight at
    once -- proving they run concurrently, not one after another."""
    order = []
    barrier = threading.Barrier(3, timeout=5)

    def make(i):
        def thunk():
            barrier.wait()          # blocks until all 3 arrive (concurrency proof)
            order.append(i)
        return thunk

    parallel.prefetch(make(0), make(1), make(2))
    assert sorted(order) == [0, 1, 2]


def test_prefetch_swallows_errors():
    ran = []
    parallel.prefetch(
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        lambda: ran.append(1),
    )
    assert ran == [1]               # sibling still ran; no raise propagated


def test_prefetch_handles_zero_one_and_none():
    parallel.prefetch()             # no thunks -> no raise
    got = []
    parallel.prefetch(lambda: got.append("a"))          # single thunk runs inline
    parallel.prefetch(None, lambda: got.append("b"), None)  # None thunks skipped
    assert got == ["a", "b"]
