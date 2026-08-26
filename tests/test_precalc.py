"""Phase 4 precalc: season-rollup table, rebuild, and reader (live DB).

Rebuild is expensive (a full season load per LMU hitter), so a module-scoped
fixture rebuilds ONCE and the read tests share it; only the idempotency test
pays a second rebuild.
"""
import pytest

from app.data import precalc, hitting_caps, pitching_caps
from app.db import get_engine

WADAS = 806253


@pytest.fixture(scope="module")
def rebuilt():
    return precalc.rebuild_hitting(get_engine())


def test_rebuild_populates_every_lmu_hitter(rebuilt):
    from app.data import seasons
    # per-season precalc: one row per DISTINCT (batter, season) across every season.
    expected = sum(hitting_caps.lmu_hitters(s)["BatterId"].nunique()
                   for s in seasons.available_seasons())
    assert rebuilt == expected
    for bid in hitting_caps.lmu_hitters()["BatterId"]:  # current-season rows present
        assert precalc.read_hitting_season(int(bid)) is not None


def test_rebuild_covers_past_seasons(rebuilt):
    from app.data import seasons
    past = [s for s in seasons.available_seasons() if s < seasons.current_season()]
    assert past, "expected more than one season of data"
    lbl = past[0]
    roster = hitting_caps.lmu_hitters(lbl)
    assert not roster.empty
    bid = int(roster.iloc[0]["BatterId"])
    row = precalc.read_hitting_season(bid, lbl)
    assert row is not None and row["season_label"] == lbl
    comp = hitting_caps._compute_season_rollup(bid, lbl)  # matches a past-season compute
    for k in ("qab_pct", "ba", "obp", "slg", "pa", "ab", "h",
              "doubles", "triples", "hr", "bb", "so",
              "hard_hit_pct", "popup_pct", "xba"):
        assert row[k] == comp[k], k


def test_rebuild_is_idempotent(rebuilt):
    assert precalc.rebuild_hitting(get_engine()) == rebuilt


def test_read_matches_compute_for_sample(rebuilt):
    row = precalc.read_hitting_season(WADAS)
    comp = hitting_caps._compute_season_rollup(WADAS)
    for k in ("qab_pct", "ba", "obp", "slg", "pa", "ab", "h",
              "doubles", "triples", "hr", "bb", "so",
              "hard_hit_pct", "popup_pct", "xba"):
        assert row[k] == comp[k], k


def test_read_missing_returns_none(rebuilt):
    assert precalc.read_hitting_season(-1) is None


# ---- pitching --------------------------------------------------------------

@pytest.fixture(scope="module")
def rebuilt_pitching():
    return precalc.rebuild_pitching(get_engine())


def test_pitching_rebuild_populates_every_lmu_pitcher(rebuilt_pitching):
    from app.data import seasons
    expected = sum(pitching_caps.lmu_pitchers(s)["PitcherId"].nunique()
                   for s in seasons.available_seasons())
    assert rebuilt_pitching == expected
    for pid in pitching_caps.lmu_pitchers()["PitcherId"]:
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


def test_data_version_bumps():
    """The data-version stamp increments so a separate-process cron rebuild
    can signal web workers to invalidate their caches."""
    e = get_engine()
    precalc.ensure_tables(e)
    v0 = precalc.read_data_version(e)
    precalc._bump_version(e)
    assert precalc.read_data_version(e) == v0 + 1
