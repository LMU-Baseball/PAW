"""Tests for app.ingest.bullpen (pure BULLPEN CSV parser + dedup key)."""
import math
from pathlib import Path

import pandas as pd
import pytest

from app.ingest import bullpen
from app.ingest.bullpen import BULLPEN_COLS, parse_bullpen_csv, dedup_key

FIXTURE = Path(__file__).parent / "fixtures" / "ingest" / "bullpen_sample.csv"

# Representative subset of the 79-name BULLPEN DB table column set (brief
# §Task 2). The parser's output columns must all be members of this larger
# set -- NOT equal to it, since BULLPEN also has 11 derived columns absent
# from the CSV.
BULLPEN_TABLE_COLS_SUBSET = {
    "PitchNo", "Date", "Time", "Pitcher", "PitcherId", "PitcherTeam",
    "TaggedPitchType", "PitchSession", "RelSpeed", "SpinRate",
    "InducedVertBreak", "HorzBreak", "PlateLocHeight", "PlateLocSide",
    "PlayID", "PracticeType", "SpinAxis3dSpinEfficiency", "Tilt",
}


def test_bullpen_cols_is_68_names():
    assert len(BULLPEN_COLS) == 68


def test_bullpen_cols_are_all_in_the_bullpen_table_subset_where_checkable():
    # every name in our known subset must appear in BULLPEN_COLS (sanity that
    # the hard-coded list wasn't mistyped for at least these well-known cols)
    assert BULLPEN_TABLE_COLS_SUBSET.issubset(set(BULLPEN_COLS))


def test_parse_bullpen_csv_returns_18_rows():
    df = pd.read_csv(FIXTURE)
    out = parse_bullpen_csv(df, source_file="bullpen_sample.csv")
    assert len(out) == 18


def test_parse_bullpen_csv_columns_are_subset_of_bullpen_cols():
    df = pd.read_csv(FIXTURE)
    out = parse_bullpen_csv(df, source_file="bullpen_sample.csv")
    assert set(out.columns).issubset(set(BULLPEN_COLS))
    # and, per the brief's known-subset check, every returned column that
    # happens to be in our representative subset really is a BULLPEN col
    for c in out.columns:
        if c in BULLPEN_TABLE_COLS_SUBSET:
            assert c in BULLPEN_TABLE_COLS_SUBSET


def test_parse_bullpen_csv_drops_columns_not_in_bullpen_cols():
    df = pd.read_csv(FIXTURE)
    df["NotARealBullpenColumn"] = "x"
    out = parse_bullpen_csv(df, source_file="bullpen_sample.csv")
    assert "NotARealBullpenColumn" not in out.columns


def test_dedup_key_uses_playid_when_present():
    df = pd.read_csv(FIXTURE)
    row = df.iloc[0].to_dict()
    assert row["PlayID"]
    assert dedup_key(row) == str(row["PlayID"])


def test_dedup_key_composite_when_playid_empty_string():
    row = {
        "PlayID": "",
        "PitcherId": "823008",
        "Date": "2026-05-13",
        "Time": "19:31:55.77",
        "PitchNo": "1",
    }
    assert dedup_key(row) == "823008|2026-05-13|19:31:55.77|1"


def test_dedup_key_composite_when_playid_nan():
    row = {
        "PlayID": math.nan,
        "PitcherId": "823008",
        "Date": "2026-05-13",
        "Time": "19:31:55.77",
        "PitchNo": "1",
    }
    assert dedup_key(row) == "823008|2026-05-13|19:31:55.77|1"


def test_dedup_key_composite_when_playid_missing_key():
    row = {
        "PitcherId": "823008",
        "Date": "2026-05-13",
        "Time": "19:31:55.77",
        "PitchNo": "1",
    }
    assert dedup_key(row) == "823008|2026-05-13|19:31:55.77|1"
