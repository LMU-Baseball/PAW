"""Live-DB calibration check for the called-strike model.

Unlike tests/test_called_strike.py (deliberately DB-free), this test hits the
live database -- same convention as tests/test_hitting.py (a plain module
that queries the live DB directly, no lookup= injection).

It exists because fix round 1's predecessor shipped with a real bias: the
level-1 smoothing anchor was an entire height band's marginal rate, and a
height band is not a local neighbourhood (side runs the full window within
one band while the true rate runs ~0.99 -> ~0.00). That dragged well-sampled
off-plate cells up and made summed expected called strikes run +2.15% (+395)
above the actual count over the training population -- concentrated almost
entirely beyond 1.2 ft off the plate. This test guards against that
regressing, using the actual training population rather than a synthetic
fixture, since the bug only shows up in aggregate over the real cell-count
distribution.
"""
from __future__ import annotations

import pytest

from app.data import called_strike as cs


@pytest.fixture(scope="module")
def training_df():
    return cs._raw_taken_pitches()


@pytest.fixture(scope="module")
def taken_df(training_df):
    """Same filtering `_build_lookup_from_df` applies before binning."""
    d = training_df[
        training_df["plate_loc_side"].notna() & training_df["plate_loc_height"].notna()
    ]
    return d[cs.is_taken(d)]


@pytest.fixture(scope="module")
def lookup(training_df):
    return cs._build_lookup_from_df(training_df)


def test_expected_called_strikes_calibrated_to_actual(taken_df, lookup):
    """Sum of expected called strikes over the full training population must
    track the actual observed count within 0.5% relative bias.

    A model trained and evaluated on the SAME population is expected to be
    very nearly self-consistent -- smoothing trades a little bias for
    variance reduction, but it must not systematically inflate or deflate
    the total. A model that gives away or takes back nearly half a percent
    of a season's called strikes because of *how it smooths*, rather than
    real receiving skill, would corrupt the SLAA it's meant to measure.
    """
    assert not taken_df.empty
    actual = int(cs.is_called_strike(taken_df).sum())
    expected = float(cs.expected_called_strikes(taken_df, lookup=lookup).sum())
    rel_bias = abs(expected - actual) / actual
    assert rel_bias < 0.005, (
        f"actual={actual} expected={expected:.1f} "
        f"bias={expected - actual:+.1f} rel_bias={rel_bias:.4f}"
    )


def test_far_off_plate_cells_are_not_systematically_inflated(taken_df, lookup):
    """Narrower guard on the exact failure mode from fix round 1: pitches
    1.2+ ft off the plate (rare called strikes in reality) must not be
    assigned a wildly higher expected rate than they actually earned."""
    d = taken_df.copy()
    far = d[d["plate_loc_side"].abs() >= 1.2]
    assert not far.empty
    actual = int(cs.is_called_strike(far).sum())
    expected = float(cs.expected_called_strikes(far, lookup=lookup).sum())
    # The predecessor model expected ~1,924 against an actual 700 here
    # (+632 +214 bias slices combined) -- a >2.5x overshoot. Require the
    # fixed model stay within a much tighter band of the real total.
    assert expected < actual * 1.5, (
        f"far-off-plate: actual={actual} expected={expected:.1f} -- "
        "smoothing is inflating off-plate cells again"
    )
