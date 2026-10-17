"""Tests for app.ingest.games loader: iter_game_files + load_games.

No network, no live DB: `iter_game_files` is tested against a fake
in-memory sftp tree, and `load_games` is tested by monkeypatching the
file-discovery + CSV-read seams plus `existing_keys`/`chunked_insert` (so no
real SFTP connection or SQL engine is ever touched).
"""
import stat
from pathlib import Path

import pandas as pd
import pytest

from app.ingest import games
from app.ingest.games import iter_game_files, load_games

FIXTURE = Path(__file__).parent / "fixtures" / "ingest" / "game_sample.csv"


# ---- iter_game_files: fake sftp recursive walk -----------------------

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


def test_iter_game_files_walks_nested_tree_finds_file_under_csv_leaf():
    tree = {
        "/v3": [_FakeAttr("2026", is_dir=True)],
        "/v3/2026": [_FakeAttr("04", is_dir=True)],
        "/v3/2026/04": [_FakeAttr("16", is_dir=True)],
        "/v3/2026/04/16": [_FakeAttr("CSV", is_dir=True)],
        "/v3/2026/04/16/CSV": [
            _FakeAttr("20260416-CypressCollege-1.csv", is_dir=False),
            _FakeAttr("notes.txt", is_dir=False),
            _FakeAttr("not-a-game.csv", is_dir=False),
        ],
    }
    files = iter_game_files(_FakeSFTP(tree))
    assert files == ["/v3/2026/04/16/CSV/20260416-CypressCollege-1.csv"]


def test_iter_game_files_ignores_matching_filename_outside_csv_dir():
    tree = {
        "/v3": [_FakeAttr("2026", is_dir=True)],
        "/v3/2026": [_FakeAttr("04", is_dir=True)],
        "/v3/2026/04": [_FakeAttr("16", is_dir=True)],
        "/v3/2026/04/16": [
            _FakeAttr("CSV", is_dir=True),
            _FakeAttr("OTHER", is_dir=True),
        ],
        "/v3/2026/04/16/CSV": [
            _FakeAttr("20260416-CypressCollege-1.csv", is_dir=False),
        ],
        "/v3/2026/04/16/OTHER": [
            _FakeAttr("20260416-x.csv", is_dir=False),
        ],
    }
    files = iter_game_files(_FakeSFTP(tree))
    assert files == ["/v3/2026/04/16/CSV/20260416-CypressCollege-1.csv"]


def test_iter_game_files_finds_multiple_across_dirs():
    tree = {
        "/v3": [_FakeAttr("2026", is_dir=True)],
        "/v3/2026": [
            _FakeAttr("04", is_dir=True),
            _FakeAttr("05", is_dir=True),
        ],
        "/v3/2026/04": [_FakeAttr("CSV", is_dir=True)],
        "/v3/2026/04/CSV": [_FakeAttr("20260416-a.csv", is_dir=False)],
        "/v3/2026/05": [_FakeAttr("CSV", is_dir=True)],
        "/v3/2026/05/CSV": [_FakeAttr("20260501-b.csv", is_dir=False)],
    }
    files = iter_game_files(_FakeSFTP(tree))
    assert files == [
        "/v3/2026/04/CSV/20260416-a.csv",
        "/v3/2026/05/CSV/20260501-b.csv",
    ]


def test_iter_game_files_empty_tree_returns_empty_list():
    assert iter_game_files(_FakeSFTP({})) == []


# ---- dedup_key -----------------------------------------------------------

def test_dedup_key_uses_pitchuid_when_present():
    row = {"PitchUID": "abc-123", "GameUID": "g1", "GameID": "gid1", "PitchNo": 5}
    assert games.dedup_key(row) == "abc-123"


def test_dedup_key_falls_back_to_composite_when_pitchuid_is_nan():
    row = {"PitchUID": float("nan"), "GameUID": "g1", "PitchNo": 5}
    assert games.dedup_key(row) == "g1|5"


def test_dedup_key_falls_back_to_composite_when_pitchuid_is_none():
    row = {"PitchUID": None, "GameUID": "g1", "PitchNo": 7}
    assert games.dedup_key(row) == "g1|7"


def test_dedup_key_falls_back_to_composite_when_pitchuid_is_empty_string():
    row = {"PitchUID": "", "GameUID": "g1", "PitchNo": 9}
    assert games.dedup_key(row) == "g1|9"


def test_dedup_key_uses_gameid_when_gameuid_missing():
    row = {"PitchUID": None, "GameUID": None, "GameID": "game42", "PitchNo": 3}
    assert games.dedup_key(row) == "game42|3"


def test_dedup_key_distinct_composite_keys_for_distinct_pitchno_not_collapsed():
    row_a = {"PitchUID": float("nan"), "GameUID": "g1", "PitchNo": 1}
    row_b = {"PitchUID": float("nan"), "GameUID": "g1", "PitchNo": 2}
    assert games.dedup_key(row_a) != games.dedup_key(row_b)


# ---- load_games ---------------------------------------------------------

@pytest.fixture
def fixture_df():
    return pd.read_csv(FIXTURE)


@pytest.fixture(autouse=True)
def patch_file_discovery(monkeypatch, fixture_df):
    """Skip real SFTP walking/reading: one fake file, backed by the fixture."""
    monkeypatch.setattr(
        games,
        "iter_game_files",
        lambda sftp, root="/v3": ["/v3/2026/04/16/20260416-sample.csv"],
    )
    monkeypatch.setattr(
        games,
        "_read_csv_from_sftp",
        lambda sftp, path: fixture_df.copy(),
    )


def test_load_games_dry_run_does_not_call_chunked_insert(monkeypatch):
    monkeypatch.setattr(games, "existing_keys", lambda engine, table, col: set())
    monkeypatch.setattr(
        games, "chunked_insert",
        lambda *a, **k: pytest.fail("chunked_insert must not be called when dry_run=True"),
    )

    result = load_games(engine=object(), sftp=object(), dry_run=True)

    assert result.inserted == 30
    assert result.skipped == 0
    assert result.files == 1
    assert result.dry_run is True
    assert result.date_min == "2026-04-16"
    assert result.date_max == "2026-04-16"


def test_load_games_skips_rows_whose_pitchuid_already_exists(monkeypatch, fixture_df):
    all_pitch_uids = set(fixture_df["PitchUID"].astype(str))
    monkeypatch.setattr(games, "existing_keys", lambda engine, table, col: all_pitch_uids)
    monkeypatch.setattr(
        games, "chunked_insert",
        lambda *a, **k: pytest.fail("chunked_insert must not be called with nothing new to insert"),
    )

    result = load_games(engine=object(), sftp=object(), dry_run=True)

    assert result.inserted == 0
    assert result.skipped == 30


def test_load_games_not_dry_run_calls_chunked_insert_with_all_new_rows(monkeypatch):
    inserted_rows = []
    monkeypatch.setattr(games, "existing_keys", lambda engine, table, col: set())

    def fake_chunked_insert(engine, table, rows, chunksize=500):
        assert table == "GAMES"
        inserted_rows.extend(rows)
        return len(rows)

    monkeypatch.setattr(games, "chunked_insert", fake_chunked_insert)

    result = load_games(engine=object(), sftp=object(), dry_run=False)

    assert len(inserted_rows) == 30
    assert result.inserted == 30
    assert result.dry_run is False


def test_load_games_within_run_duplicate_pitchuid_is_skipped_not_inserted_twice(monkeypatch, fixture_df):
    # Two "files" that both resolve to the same fixture data -- the second
    # pass's rows should all be seen-this-run duplicates.
    monkeypatch.setattr(
        games,
        "iter_game_files",
        lambda sftp, root="/v3": [
            "/v3/2026/04/16/20260416-sample.csv",
            "/v3/2026/04/16/20260416-sample-dup.csv",
        ],
    )
    monkeypatch.setattr(games, "existing_keys", lambda engine, table, col: set())
    monkeypatch.setattr(
        games, "chunked_insert",
        lambda *a, **k: pytest.fail("chunked_insert must not be called under dry_run"),
    )

    result = load_games(engine=object(), sftp=object(), dry_run=True)

    assert result.files == 2
    assert result.inserted == 30
    assert result.skipped == 30


def test_load_games_rows_with_blank_pitchuid_use_composite_key_not_collapsed(monkeypatch):
    # Two rows sharing a GameUID but with distinct PitchNo, both missing
    # PitchUID (as pandas reads a genuinely blank CSV cell -> NaN). Before
    # the fix these both stringified to the literal "nan" and collapsed
    # onto one dedup key, silently dropping one of the two real rows.
    two_rows_df = pd.DataFrame({
        "PitchNo": [1, 2],
        "Date": ["2026-04-16", "2026-04-16"],
        "GameUID": ["g1", "g1"],
        "GameID": ["gid1", "gid1"],
        "PitchUID": [float("nan"), float("nan")],
    })
    monkeypatch.setattr(games, "_read_csv_from_sftp", lambda sftp, path: two_rows_df.copy())
    monkeypatch.setattr(games, "existing_keys", lambda engine, table, col: set())
    monkeypatch.setattr(
        games, "chunked_insert",
        lambda *a, **k: pytest.fail("chunked_insert must not be called under dry_run"),
    )

    result = load_games(engine=object(), sftp=object(), dry_run=True)

    assert result.inserted == 2
    assert result.skipped == 0


# ---- excluded_game_ids / exclusion during load --------------------------

def test_excluded_game_ids_empty_when_file_absent(tmp_path):
    assert games.excluded_game_ids(tmp_path / "nope.json") == set()


def test_excluded_game_ids_reads_committed_list(tmp_path):
    p = tmp_path / "excluded_games.json"
    p.write_text(
        '[{"game_id": "gid1", "reason": "dup", "removed": "2026-10-15"}, '
        '{"game_id": "gid2", "reason": "dup", "removed": "2026-10-15"}]',
        encoding="utf-8",
    )
    assert games.excluded_game_ids(p) == {"gid1", "gid2"}


def test_pitch_uid_only_entry_blocks_pitches_not_the_game(tmp_path):
    p = tmp_path / "excluded_games.json"
    p.write_text(
        '[{"game_id": "gid1", "reason": "dup", "removed": "2026-10-15"}, '
        '{"game_id": null, "source_game_id": "gid2", "reason": "junk rows", '
        '"removed": "2026-10-16", "pitch_uids": ["u9"]}]',
        encoding="utf-8",
    )
    assert games.excluded_game_ids(p) == {"gid1"}
    assert games.excluded_pitch_uids(p) == {"u9"}


def test_excluded_pitch_uids_empty_when_file_absent(tmp_path):
    assert games.excluded_pitch_uids(tmp_path / "nope.json") == set()


def test_excluded_pitch_uids_flattens_every_entrys_list(tmp_path):
    p = tmp_path / "excluded_games.json"
    p.write_text(
        '[{"game_id": "gid1", "reason": "dup", "removed": "2026-10-15", '
        '  "pitch_uids": ["u1", "u2"]}, '
        ' {"game_id": "gid2", "reason": "dup", "removed": "2026-10-15", '
        '  "pitch_uids": ["u3"]}]',
        encoding="utf-8",
    )
    assert games.excluded_pitch_uids(p) == {"u1", "u2", "u3"}


def test_excluded_pitch_uids_tolerates_entries_without_the_field(tmp_path):
    """An older exclude-list entry written before pitch_uids existed."""
    p = tmp_path / "excluded_games.json"
    p.write_text(
        '[{"game_id": "gid1", "reason": "dup", "removed": "2026-10-15"}]',
        encoding="utf-8",
    )
    assert games.excluded_pitch_uids(p) == set()


def test_load_games_skips_rows_whose_gameid_is_excluded(monkeypatch, fixture_df):
    excluded_gid = str(fixture_df.iloc[0]["GameID"])
    monkeypatch.setattr(games, "excluded_game_ids", lambda path=None: {excluded_gid})
    monkeypatch.setattr(games, "excluded_pitch_uids", lambda path=None: set())
    monkeypatch.setattr(games, "existing_keys", lambda engine, table, col: set())
    monkeypatch.setattr(
        games, "chunked_insert",
        lambda *a, **k: pytest.fail("chunked_insert must not be called with nothing new to insert"),
    )

    result = load_games(engine=object(), sftp=object(), dry_run=True)

    assert result.inserted == 0
    assert result.skipped == 0
    assert result.skipped_excluded == 30


def test_load_games_skips_rows_whose_pitchuid_is_excluded(monkeypatch, fixture_df):
    """Catches Trackman's sidecar per-game files (e.g. a playerpositioning
    export), which carry an excluded game's PitchUIDs but no GameID column
    for `excluded_game_ids` to match on."""
    excluded_pids = set(fixture_df["PitchUID"].astype(str))
    monkeypatch.setattr(games, "excluded_pitch_uids", lambda path=None: excluded_pids)
    monkeypatch.setattr(games, "excluded_game_ids", lambda path=None: set())
    monkeypatch.setattr(games, "existing_keys", lambda engine, table, col: set())
    monkeypatch.setattr(
        games, "chunked_insert",
        lambda *a, **k: pytest.fail("chunked_insert must not be called with nothing new to insert"),
    )

    result = load_games(engine=object(), sftp=object(), dry_run=True)

    assert result.inserted == 0
    assert result.skipped == 0
    assert result.skipped_excluded == 30


def test_load_games_excluded_rows_never_reach_already_loaded_dedup(monkeypatch, fixture_df):
    """An excluded GameID is skipped outright -- it must not also get counted
    in `skipped` (the already-loaded/duplicate-within-run bucket)."""
    excluded_gid = str(fixture_df.iloc[0]["GameID"])
    monkeypatch.setattr(games, "excluded_game_ids", lambda path=None: {excluded_gid})
    all_pitch_uids = set(fixture_df["PitchUID"].astype(str))
    monkeypatch.setattr(games, "existing_keys", lambda engine, table, col: all_pitch_uids)

    result = load_games(engine=object(), sftp=object(), dry_run=True)

    assert result.skipped_excluded == 30
    assert result.skipped == 0


def test_load_games_limit_caps_files_processed(monkeypatch):
    monkeypatch.setattr(games, "existing_keys", lambda engine, table, col: set())
    monkeypatch.setattr(
        games, "chunked_insert",
        lambda *a, **k: pytest.fail("chunked_insert must not be called under dry_run"),
    )

    result = load_games(engine=object(), sftp=object(), dry_run=True, limit=0)

    assert result.files == 0
    assert result.inserted == 0
    assert result.skipped == 0
