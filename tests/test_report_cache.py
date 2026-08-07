"""Unit tests for the pitcher-report PDF cache (no DB / no Chromium).

build_pitcher_postgame() should build a report once per (game_id, pitcher_id,
data-version) and serve the cached bytes afterward, rebuilding only when the
pitcher's data version changes.
"""
from pathlib import Path

import app.reports.pitcher_postgame as PP


def _patch(monkeypatch, tmp_path, version, build_counter):
    """Point the cache at tmp_path and stub out the version + heavy build."""
    monkeypatch.setattr(PP, "_CACHE_DIR", Path(tmp_path))
    monkeypatch.setattr(PP.pitching_caps, "report_data_version", lambda pid: version["v"])
    monkeypatch.setattr(PP, "_build_html", lambda gid, pid: "<html>report</html>")

    def _fake_pdf(html):
        build_counter["n"] += 1
        return b"%PDF-" + str(build_counter["n"]).encode()

    monkeypatch.setattr(PP, "html_to_pdf", _fake_pdf)


def test_second_call_is_served_from_cache(tmp_path, monkeypatch):
    version = {"v": "2026-05-16"}
    builds = {"n": 0}
    _patch(monkeypatch, tmp_path, version, builds)

    first = PP.build_pitcher_postgame(166, 1)
    second = PP.build_pitcher_postgame(166, 1)

    assert builds["n"] == 1          # built once, second call hit the cache
    assert first == second           # identical bytes
    assert first.startswith(b"%PDF-")
    # A cache file was actually written for this key.
    assert list(Path(tmp_path).glob("pitcher_1_game_166_*.pdf"))


def test_new_data_version_triggers_rebuild(tmp_path, monkeypatch):
    version = {"v": "2026-05-16"}
    builds = {"n": 0}
    _patch(monkeypatch, tmp_path, version, builds)

    PP.build_pitcher_postgame(166, 1)     # build @ v1
    version["v"] = "2026-05-20"           # pitcher threw again -> new version
    PP.build_pitcher_postgame(166, 1)     # must rebuild, not serve stale

    assert builds["n"] == 2


def test_distinct_pitchers_do_not_share_cache(tmp_path, monkeypatch):
    version = {"v": "2026-05-16"}
    builds = {"n": 0}
    _patch(monkeypatch, tmp_path, version, builds)

    PP.build_pitcher_postgame(166, 1)
    PP.build_pitcher_postgame(166, 2)

    assert builds["n"] == 2
