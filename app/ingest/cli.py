"""`flask ingest ...` CLI commands for the Trackman/HitTrax data loaders.

Registered onto the Flask app's CLI via `register_cli` in `app/cli.py`
(`server.cli.add_command(ingest_cli)`).
"""
from __future__ import annotations

from datetime import datetime, timezone

import click

from app.db import get_engine
from app.ingest.bullpen import load_bullpen
from app.ingest.config import hittrax_cfg, trackman_cfg
from app.ingest.connections import open_ftps, open_sftp
from app.ingest.games import load_games
from app.ingest.hittrax import extract_load_raw

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


@ingest_cli.command("games")
@click.option(
    "--dry-run/--no-dry-run", default=True,
    help="Preview only, write nothing (default). Use --no-dry-run to actually insert.",
)
@click.option("--limit", type=int, default=None, help="Limit the number of game CSV files processed.")
def games_command(dry_run: bool, limit: int | None):
    """Load GAMES (Trackman regular/scrimmage games) from the SFTP /v3 tree."""
    engine = get_engine()
    with open_sftp(trackman_cfg()) as sftp:
        result = load_games(engine, sftp, dry_run=dry_run, limit=limit)
    click.echo(
        f"GAMES load: files={result.files} inserted={result.inserted} "
        f"skipped={result.skipped} date_min={result.date_min} date_max={result.date_max} "
        f"dry_run={result.dry_run}"
    )


@ingest_cli.command("hittrax-raw")
@click.option(
    "--dry-run/--no-dry-run", default=True,
    help="Preview only, write nothing (default). Use --no-dry-run to actually insert.",
)
@click.option("--limit", type=int, default=None, help="Limit the number of HitTrax CSV files processed.")
def hittrax_raw_command(dry_run: bool, limit: int | None):
    """Load raw HitTrax exports (Plays/Session CSVs) into `raw_practice_csv` from the FTPS root."""
    engine = get_engine()
    ingested_at = datetime.now(timezone.utc)
    with open_ftps(hittrax_cfg()) as ftps:
        result = extract_load_raw(engine, ftps, ingested_at=ingested_at, dry_run=dry_run, limit=limit)
    click.echo(
        f"HitTrax raw load: files={result.files} inserted={result.inserted} "
        f"ignored={result.skipped} dry_run={result.dry_run}"
    )
