"""Tests for app.ingest.bullpen loader: iter_practice_pitching_files + load_bullpen.

No network, no live DB: `iter_practice_pitching_files` is tested against a
fake in-memory sftp tree, and `load_bullpen` is tested by monkeypatching the
file-discovery + CSV-read seams plus `existing_keys`/`chunked_insert` (so no
real SFTP connection or SQL engine is ever touched).
"""
import stat
from pathlib import Path

import pandas as pd
import pytest

from app.ingest import bullpen
from app.ingest.bullpen import iter_practice_pitching_files, load_bullpen

FIXTURE = Path(__file__).parent / "fixtures" / "ingest" / "bullpen_sample.csv"


# ---- iter_practice_pitching_files: fake sftp recursive walk ---------------

class _FakeAttr:
    def __init__(self, filename, is_dir):
        self.filename = filename
        self.st_mode = stat.S_IFDIR if is_dir else stat.S_IFREG


class _FakeSFTP:
    """Minimal stand-in for paramiko.SFTPClient: `listdir_attr` only."""

    def __init__(self, tree: dict):
        self.tree = tree  # path -> list[_FakeAttr]

    def listdir_attr(self, path):
        return self.tree.get(path, [])


def test_iter_practice_pitching_files_walks_nested_date_tree():
    tree = {
        "/practice": [_FakeAttr("2026", is_dir=True)],
        "/practice/2026": [_FakeAttr("05", is_dir=True)],
        "/practice/2026/05": [_FakeAttr("14", is_dir=True)],
        "/practice/2026/05/14": [
            _FakeAttr("Pitching_sample.csv", is_dir=False),
            _FakeAttr("HitTrax_other.csv", is_dir=False),
            _FakeAttr("notes.txt", is_dir=False),
        ],
    }
    files = iter_practice_pitching_files(_FakeSFTP(tree))
    assert files == ["/practice/2026/05/14/Pitching_sample.csv"]


def test_iter_practice_pitching_files_finds_multiple_across_dirs():
    tree = {
        "/practice": [_FakeAttr("2026", is_dir=True)],
        "/practice/2026": [
            _FakeAttr("05", is_dir=True),
            _FakeAttr("06", is_dir=True),
        ],
        "/practice/2026/05": [_FakeAttr("Pitching_a.csv", is_dir=False)],
        "/practice/2026/06": [_FakeAttr("Pitching_b.csv", is_dir=False)],
    }
    files = iter_practice_pitching_files(_FakeSFTP(tree))
    assert files == [
        "/practice/2026/05/Pitching_a.csv",
        "/practice/2026/06/Pitching_b.csv",
    ]


def test_iter_practice_pitching_files_empty_tree_returns_empty_list():
    assert iter_practice_pitching_files(_FakeSFTP({})) == []


# ---- load_bullpen -----------------------------------------------------

@pytest.fixture
def fixture_df():
    return pd.read_csv(FIXTURE)


@pytest.fixture(autouse=True)
def patch_file_discovery(monkeypatch, fixture_df):
    """Skip real SFTP walking/reading: one fake file, backed by the fixture."""
    monkeypatch.setattr(
        bullpen,
        "iter_practice_pitching_files",
        lambda sftp, root="/practice": ["/practice/2026/05/13/Pitching_sample.csv"],
    )
    monkeypatch.setattr(
        bullpen,
        "_read_csv_from_sftp",
        lambda sftp, path: fixture_df.copy(),
    )


def test_load_bullpen_dry_run_does_not_call_chunked_insert(monkeypatch):
    monkeypatch.setattr(bullpen, "existing_keys", lambda engine, table, col: set())
    monkeypatch.setattr(
        bullpen, "chunked_insert",
        lambda *a, **k: pytest.fail("chunked_insert must not be called when dry_run=True"),
    )

    result = load_bullpen(engine=object(), sftp=object(), dry_run=True)

    assert result.inserted == 18
    assert result.skipped == 0
    assert result.files == 1
    assert result.dry_run is True
    assert result.date_min == "2026-05-13"
    assert result.date_max == "2026-05-13"


def test_load_bullpen_skips_rows_whose_playid_already_exists(monkeypatch, fixture_df):
    all_play_ids = set(fixture_df["PlayID"].astype(str))
    monkeypatch.setattr(bullpen, "existing_keys", lambda engine, table, col: all_play_ids)
    monkeypatch.setattr(
        bullpen, "chunked_insert",
        lambda *a, **k: pytest.fail("chunked_insert must not be called with nothing new to insert"),
    )

    result = load_bullpen(engine=object(), sftp=object(), dry_run=True)

    assert result.inserted == 0
    assert result.skipped == 18


def test_load_bullpen_not_dry_run_calls_chunked_insert_with_all_new_rows(monkeypatch):
    inserted_rows = []
    monkeypatch.setattr(bullpen, "existing_keys", lambda engine, table, col: set())

    def fake_chunked_insert(engine, table, rows, chunksize=500):
        assert table == "BULLPEN"
        inserted_rows.extend(rows)
        return len(rows)

    monkeypatch.setattr(bullpen, "chunked_insert", fake_chunked_insert)

    result = load_bullpen(engine=object(), sftp=object(), dry_run=False)

    assert len(inserted_rows) == 18
    assert result.inserted == 18
    assert result.dry_run is False


def test_load_bullpen_within_run_duplicate_playid_is_skipped_not_inserted_twice(monkeypatch, fixture_df):
    # Two "files" that both resolve to the same fixture data -- the second
    # pass's rows should all be seen-this-run duplicates.
    monkeypatch.setattr(
        bullpen,
        "iter_practice_pitching_files",
        lambda sftp, root="/practice": [
            "/practice/2026/05/13/Pitching_sample.csv",
            "/practice/2026/05/13/Pitching_sample_dup.csv",
        ],
    )
    monkeypatch.setattr(bullpen, "existing_keys", lambda engine, table, col: set())
    monkeypatch.setattr(
        bullpen, "chunked_insert",
        lambda *a, **k: pytest.fail("chunked_insert must not be called under dry_run"),
    )

    result = load_bullpen(engine=object(), sftp=object(), dry_run=True)

    assert result.files == 2
    assert result.inserted == 18
    assert result.skipped == 18


def test_load_bullpen_limit_caps_files_processed(monkeypatch):
    monkeypatch.setattr(bullpen, "existing_keys", lambda engine, table, col: set())
    monkeypatch.setattr(
        bullpen, "chunked_insert",
        lambda *a, **k: pytest.fail("chunked_insert must not be called under dry_run"),
    )

    result = load_bullpen(engine=object(), sftp=object(), dry_run=True, limit=0)

    assert result.files == 0
    assert result.inserted == 0
    assert result.skipped == 0
