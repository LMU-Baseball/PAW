"""Phase 4 precalc: season-rollup table, rebuild, and reader (live DB).

Rebuild is expensive (a full season load per LMU hitter), so a module-scoped
fixture rebuilds ONCE and the read tests share it; only the idempotency test
pays a second rebuild.
"""
import pytest

from app.data import precalc, hitting_caps
from app.db import get_engine

WADAS = 806253


@pytest.fixture(scope="module")
def rebuilt():
    return precalc.rebuild_hitting(get_engine())


def test_rebuild_populates_every_lmu_hitter(rebuilt):
    hitters = hitting_caps.lmu_hitters()
    assert rebuilt == len(hitters)
    for bid in hitters["BatterId"]:
        assert precalc.read_hitting_season(int(bid)) is not None


def test_rebuild_is_idempotent(rebuilt):
    assert precalc.rebuild_hitting(get_engine()) == rebuilt


def test_read_matches_compute_for_sample(rebuilt):
    row = precalc.read_hitting_season(WADAS)
    comp = hitting_caps._compute_season_rollup(WADAS)
    for k in ("qab_pct", "ba", "obp", "slg", "pa", "ab", "h",
              "doubles", "triples", "hr", "bb", "so"):
        assert row[k] == comp[k], k


def test_read_missing_returns_none(rebuilt):
    assert precalc.read_hitting_season(-1) is None
