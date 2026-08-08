"""Daily pipeline: load newly-uploaded LMU games from the Trackman SFTP into
GAMES, then rebuild the precalc rollups. The cron entrypoint (`flask
pipeline-load`) is a thin wrapper over `run_pipeline`.

Collaborators are module-level imports so tests can monkeypatch them without
touching the network / DB.
"""
from __future__ import annotations

from app.db import get_engine
from app.ingest.connections import open_sftp
from app.ingest.config import trackman_cfg
from app.ingest.games import load_games
from app.data import precalc


def run_pipeline(engine=None, *, dry_run: bool = True, since_days: int = 3) -> dict:
    """Load new LMU games (upload-folder-pruned, LMU-only) then, only on a real
    run that inserted rows, rebuild all precalc rollups. Returns
    {"load": LoadResult, "rebuilt": dict | None}."""
    engine = engine or get_engine()
    with open_sftp(trackman_cfg()) as sftp:
        res = load_games(engine, sftp, dry_run=dry_run,
                         since_days=since_days, lmu_only=True)
    rebuilt = None
    if not dry_run and res.inserted > 0:
        rebuilt = precalc.rebuild_all(engine)
    return {"load": res, "rebuilt": rebuilt}
