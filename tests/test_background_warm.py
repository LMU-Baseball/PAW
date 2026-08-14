"""Layer 3 fire-and-forget player warm helper + dashboard wiring."""
import inspect
import threading

from app.dashboards import background_warm


def test_warm_async_runs_thunks_in_background():
    done = threading.Event()
    ran = []

    def thunk():
        ran.append(1)
        done.set()

    background_warm.warm_async(thunk)
    assert done.wait(timeout=5)      # ran in the daemon thread
    assert ran == [1]


def test_warm_async_swallows_errors_and_runs_siblings():
    ev = threading.Event()
    ran = []
    background_warm.warm_async(
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        lambda: (ran.append(1), ev.set()),
    )
    assert ev.wait(timeout=5)        # the sibling still ran despite the raise
    assert ran == [1]


def test_warm_async_noop_without_thunks():
    background_warm.warm_async()     # must not raise


def test_all_game_dashboards_warm_selected_player_on_range():
    """Each game dashboard's _on_range spawns a background player warm."""
    from app.dashboards.hitting import callbacks as hc
    from app.dashboards.pitching import callbacks as pc
    from app.dashboards.catching import callbacks as cc
    for mod in (hc, pc, cc):
        src = inspect.getsource(mod.register_callbacks)
        assert "background_warm.warm_async" in src
