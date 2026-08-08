"""Daily pipeline orchestration (mocked SFTP/loader/rebuild)."""
from contextlib import contextmanager

from app.ingest import pipeline
from app.ingest.common import LoadResult


@contextmanager
def _fake_sftp(cfg):
    yield object()


def _result(inserted):
    return LoadResult(inserted=inserted, skipped=0, files=1, date_min=None,
                      date_max=None, dry_run=False, skipped_non_lmu=0)


def _wire(monkeypatch, inserted):
    captured = {}
    monkeypatch.setattr(pipeline, "trackman_cfg", lambda: {})
    monkeypatch.setattr(pipeline, "open_sftp", _fake_sftp)

    def fake_load(engine, sftp, **kw):
        captured.update(kw)
        return _result(inserted)

    monkeypatch.setattr(pipeline, "load_games", fake_load)
    rebuilds = {"n": 0}
    monkeypatch.setattr(pipeline.precalc, "rebuild_all",
                        lambda e=None: rebuilds.__setitem__("n", rebuilds["n"] + 1) or {})
    return captured, rebuilds


def test_pipeline_dry_run_skips_rebuild(monkeypatch):
    captured, rebuilds = _wire(monkeypatch, inserted=5)
    out = pipeline.run_pipeline(engine=object(), dry_run=True, since_days=3)
    assert captured["dry_run"] is True and captured["since_days"] == 3
    assert captured["lmu_only"] is True
    assert rebuilds["n"] == 0 and out["rebuilt"] is None   # dry run never rebuilds


def test_pipeline_rebuilds_on_real_run_with_inserts(monkeypatch):
    _captured, rebuilds = _wire(monkeypatch, inserted=5)
    out = pipeline.run_pipeline(engine=object(), dry_run=False, since_days=3)
    assert rebuilds["n"] == 1 and out["rebuilt"] == {}


def test_pipeline_skips_rebuild_when_no_inserts(monkeypatch):
    _captured, rebuilds = _wire(monkeypatch, inserted=0)
    out = pipeline.run_pipeline(engine=object(), dry_run=False, since_days=3)
    assert rebuilds["n"] == 0 and out["rebuilt"] is None   # nothing new -> no rebuild
