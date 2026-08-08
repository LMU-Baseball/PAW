"""Phase 4 precalc: season-rollup table, rebuild, and reader (live DB).

Rebuild is expensive (a full season load per LMU hitter), so a module-scoped
fixture rebuilds ONCE and the read tests share it; only the idempotency test
pays a second rebuild.
"""
import pytest

from app.data import precalc, hitting_caps, pitching_caps, catching_caps
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


# ---- pitching --------------------------------------------------------------

@pytest.fixture(scope="module")
def rebuilt_pitching():
    return precalc.rebuild_pitching(get_engine())


def test_pitching_rebuild_populates_every_lmu_pitcher(rebuilt_pitching):
    pit = pitching_caps.lmu_pitchers()
    assert rebuilt_pitching == len(pit)
    for pid in pit["PitcherId"]:
        assert precalc.read_pitching_season(int(pid)) is not None


def test_pitching_read_matches_compute(rebuilt_pitching):
    pid = int(pitching_caps.lmu_pitchers().iloc[0]["PitcherId"])
    row = precalc.read_pitching_season(pid)
    comp = pitching_caps._compute_season_rollup(pid)
    for k in ("appearances", "ip", "k_pct", "bb_pct", "barrel_pct",
              "min_date", "max_date"):
        assert row[k] == comp[k], k


def test_pitching_covering_range_uses_rollup(rebuilt_pitching):
    """range_summary over the pitcher's whole span == the rollup tiles."""
    pid = int(pitching_caps.lmu_pitchers().iloc[0]["PitcherId"])
    row = precalc.read_pitching_season(pid)
    tiles = pitching_caps.range_summary(pid, row["min_date"], row["max_date"])
    assert tiles == {k: row[k] for k in
                     ("appearances", "ip", "k_pct", "bb_pct", "barrel_pct")}


# ---- catching --------------------------------------------------------------

@pytest.fixture(scope="module")
def rebuilt_catching():
    return precalc.rebuild_catching(get_engine())


def test_catching_rebuild_populates_every_lmu_catcher(rebuilt_catching):
    cat = catching_caps.lmu_catchers()
    assert rebuilt_catching == len(cat)
    for cid in cat["CatcherId"]:
        assert precalc.read_catching_season(int(cid)) is not None


def test_catching_read_matches_compute(rebuilt_catching):
    cid = int(catching_caps.lmu_catchers().iloc[0]["CatcherId"])
    row = precalc.read_catching_season(cid)
    comp = catching_caps._compute_season_rollup(cid)
    for k in ("games", "pitches", "net_strikes", "steal_pct"):
        assert row[k] == comp[k], k
