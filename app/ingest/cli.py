"""`flask ingest ...` CLI commands for the Trackman/HitTrax data loaders.

Registered onto the Flask app's CLI via `register_cli` in `app/cli.py`
(`server.cli.add_command(ingest_cli)`).
"""
from __future__ import annotations

import click

from app.db import get_engine
from app.ingest.bullpen import load_bullpen
from app.ingest.config import trackman_cfg
from app.ingest.connections import open_sftp

ingest_cli = click.Group("ingest", help="Data ingestion loaders (Trackman SFTP / HitTrax FTPS).")


@ingest_cli.command("bullpen")
@click.option(
    "--dry-run/--no-dry-run", default=True,
    help="Preview only, write nothing (default). Use --no-dry-run to actually insert.",
)
@click.option("--limit", type=int, default=None, help="Limit the number of practice CSV files processed.")
def bullpen_command(dry_run: bool, limit: int | None):
    """Load BULLPEN (Trackman practice pitching) from the SFTP /practice tree."""
    engine = get_engine()
    with open_sftp(trackman_cfg()) as sftp:
        result = load_bullpen(engine, sftp, dry_run=dry_run, limit=limit)
    click.echo(
        f"BULLPEN load: files={result.files} inserted={result.inserted} "
        f"skipped={result.skipped} date_min={result.date_min} date_max={result.date_max} "
        f"dry_run={result.dry_run}"
    )
