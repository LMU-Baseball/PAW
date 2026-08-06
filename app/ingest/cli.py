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
from app.ingest.hittrax import extract_load_raw, transform
from app.ingest.normalize_games_date import normalize_dates
from app.ingest.warehouse_to_games import load_backfill

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


@ingest_cli.command("backfill-games")
@click.option(
    "--dry-run/--no-dry-run", default=True,
    help="Preview only, write nothing (default). Use --no-dry-run to actually insert.",
)
@click.option("--since", default=None, help="Only warehouse games on/after this date (YYYY-MM-DD).")
def backfill_games_command(dry_run: bool, since: str | None):
    """Backfill GAMES from the tm_* warehouse (one-time CAPS-migration step; no SFTP)."""
    engine = get_engine()
    result = load_backfill(engine, dry_run=dry_run, since=since)
    click.echo(
        f"GAMES backfill: games={result.files} inserted={result.inserted} "
        f"skipped={result.skipped} date_min={result.date_min} date_max={result.date_max} "
        f"dry_run={result.dry_run}"
    )


@ingest_cli.command("normalize-games-date")
@click.option(
    "--dry-run/--no-dry-run", default=True,
    help="Preview only, write nothing (default). Use --no-dry-run to actually update.",
)
def normalize_games_date_command(dry_run: bool):
    """One-time: normalize GAMES.Date (mixed ISO + US m/d/yy) to ISO YYYY-MM-DD."""
    engine = get_engine()
    result = normalize_dates(engine, dry_run=dry_run)
    click.echo(
        f"GAMES.Date normalize: scanned={result['scanned']} would_change={result['would_change']} "
        f"unparseable={result['unparseable']} dry_run={dry_run}"
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


@ingest_cli.command("hittrax-transform")
@click.option(
    "--dry-run/--no-dry-run", default=True,
    help="Preview only, write nothing (default). Use --no-dry-run to actually rebuild.",
)
def hittrax_transform_command(dry_run: bool):
    """Rebuild practice_sessions/practice_plays/player_stats_summary from raw_practice_csv."""
    engine = get_engine()
    result = transform(engine, dry_run=dry_run)
    click.echo(
        f"HitTrax transform: sessions={result['sessions']} plays={result['plays']} "
        f"players={result['players']} dry_run={dry_run}"
    )


@ingest_cli.command("hittrax")
@click.option(
    "--dry-run/--no-dry-run", default=True,
    help="Preview only, write nothing (default). Use --no-dry-run to actually load + transform.",
)
@click.option("--limit", type=int, default=None, help="Limit the number of HitTrax CSV files processed.")
def hittrax_command(dry_run: bool, limit: int | None):
    """Full HitTrax pipeline: extract+load raw (FTPS) THEN transform to practice_* tables."""
    engine = get_engine()
    ingested_at = datetime.now(timezone.utc)
    with open_ftps(hittrax_cfg()) as ftps:
        raw_result = extract_load_raw(engine, ftps, ingested_at=ingested_at, dry_run=dry_run, limit=limit)
    click.echo(
        f"HitTrax raw load: files={raw_result.files} inserted={raw_result.inserted} "
        f"ignored={raw_result.skipped} dry_run={raw_result.dry_run}"
    )
    transform_result = transform(engine, dry_run=dry_run)
    click.echo(
        f"HitTrax transform: sessions={transform_result['sessions']} plays={transform_result['plays']} "
        f"players={transform_result['players']} dry_run={dry_run}"
    )
