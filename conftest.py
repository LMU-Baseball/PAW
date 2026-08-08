"""Ensures the project root is importable so tests can `import app.*`."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _isolate_cache():
    """Reset the in-process read cache + disable the cross-process version gate
    before each test, so caching never leaks state or fires a live version
    read across tests (create_app, called by many tests, otherwise installs a
    live reader globally). Tests that exercise the gate configure their own."""
    from app.data import cache
    cache.clear_all()
    cache.configure(version_reader=None)
    yield
    cache.clear_all()
    cache.configure(version_reader=None)
