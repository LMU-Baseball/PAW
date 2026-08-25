"""Called-strike probability model. DB-free: every test injects a lookup."""
import numpy as np
import pandas as pd

from app.data import called_strike as cs


def _frame(rows):
    """rows = [(side, height, pitch_call), ...] -> a taken-pitch frame."""
    return pd.DataFrame(rows, columns=["plate_loc_side", "plate_loc_height", "pitch_call"])


def _uniform_lookup():
    """A lookup where every populated cell has the same rate."""
    df = _frame([(0.0, 2.5, "StrikeCalled"), (0.0, 2.5, "BallCalled")])
    lk = cs._build_lookup_from_df(df)
    return lk


def test_single_observation_cell_is_never_exactly_zero_or_one():
    """An n=1 all-strike cell must not read as a literal 100%."""
    lk = cs._build_lookup_from_df(_frame([
        (0.0, 2.5, "StrikeCalled"),
        (1.9, 0.2, "BallCalled"),
    ]))
    p = cs.p_called_strike(0.0, 2.5, lookup=lk)
    assert 0.0 < p < 1.0


def test_far_outside_pitch_gets_near_zero_not_global_rate():
    """REGRESSION GUARD for the clipping decision.

    xba.py falls back to the GLOBAL rate for out-of-range inputs. Doing that
    here would hand a catcher ~32% expected strike probability on a pitch in
    the dirt. Clipping must map it to the edge bin instead, whose empirical
    rate is near zero.
    """
    rows = [(0.0, 2.5, "StrikeCalled")] * 50          # heart of the zone
    rows += [(-1.95, 0.05, "BallCalled")] * 50        # extreme edge, all balls
    lk = cs._build_lookup_from_df(_frame(rows))
    p_far = cs.p_called_strike(-8.0, -4.0, lookup=lk)   # way outside, clipped to edge
    assert p_far < 0.10, f"far-outside pitch got {p_far}, expected near zero"
    assert p_far < lk.fallback


def test_clipping_maps_out_of_window_to_the_same_cell_as_the_edge():
    """Assert on the key directly, not on p_called_strike's output: if both
    sides fell through to the same unobserved-cell fallback, the two
    p_called_strike calls would still be equal even with broken clipping
    (they'd both just be the same fallback value), making that comparison
    vacuous."""
    assert cs._cell_key(50.0, 99.0) == cs._cell_key(cs.SIDE_MAX, cs.HEIGHT_MAX)


def test_empty_frame_builds_a_lookup_and_does_not_raise():
    lk = cs._build_lookup_from_df(_frame([]))
    assert 0.0 < cs.p_called_strike(0.0, 2.5, lookup=lk) < 1.0


def test_missing_location_falls_back_without_raising():
    lk = _uniform_lookup()
    assert 0.0 <= cs.p_called_strike(np.nan, 2.5, lookup=lk) <= 1.0
    assert 0.0 <= cs.p_called_strike(0.0, None, lookup=lk) <= 1.0


def test_cell_keys_are_tuples_so_a_dimension_can_be_added_later():
    lk = cs._build_lookup_from_df(_frame([(0.0, 2.5, "StrikeCalled")]))
    assert all(isinstance(k, tuple) and len(k) == 2 for k in lk.cell_rates)


def test_expected_called_strikes_is_indexed_like_the_input():
    lk = _uniform_lookup()
    df = _frame([(0.0, 2.5, "StrikeCalled"), (0.5, 2.0, "BallCalled")])
    df.index = [7, 9]
    out = cs.expected_called_strikes(df, lookup=lk)
    assert list(out.index) == [7, 9]
    assert ((out >= 0.0) & (out <= 1.0)).all()


def test_expected_called_strikes_on_empty_frame_is_empty():
    out = cs.expected_called_strikes(_frame([]), lookup=_uniform_lookup())
    assert out.empty


def test_is_taken_and_is_called_strike():
    df = _frame([(0, 2, "StrikeCalled"), (0, 2, "BallCalled"), (0, 2, "InPlay")])
    assert list(cs.is_taken(df)) == [True, True, False]
    assert list(cs.is_called_strike(df)) == [True, False, False]


def test_heart_of_zone_scores_higher_than_the_edge():
    rows = [(0.0, 2.5, "StrikeCalled")] * 80
    rows += [(1.8, 0.3, "BallCalled")] * 80
    lk = cs._build_lookup_from_df(_frame(rows))
    assert cs.p_called_strike(0.0, 2.5, lookup=lk) > cs.p_called_strike(1.8, 0.3, lookup=lk)
