"""`flask ingest ...` CLI commands for the Trackman/HitTrax data loaders.

Registered onto the Flask app's CLI via `register_cli` in `app/cli.py`
(`server.cli.add_command(ingest_cli)`).
"""
from __future__ import annotations

from datetime import datetime, timezone

import click

from app.db import get_engine
from app.ingest.add_game_type import backfill_game_type
from app.ingest.backfill_zone import backfill_zone
from app.ingest.bullpen import load_bullpen
from app.ingest.config import hittrax_cfg, trackman_api_cfg, trackman_cfg
from app.ingest.connections import open_ftps, open_sftp
from app.ingest.games import load_games
from app.ingest.hittrax import extract_load_raw, transform
from app.ingest.normalize_games_date import normalize_dates
from app.ingest.bullpen_video import load_bullpen_video
from app.ingest.trackman_video import Session, edgertronic_clips
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


@ingest_cli.command("backfill-game-type")
@click.option(
    "--dry-run/--no-dry-run", default=True,
    help="Preview only, write nothing (default). Use --no-dry-run to actually update.",
)
def backfill_game_type_command(dry_run: bool):
    """One-time: add GAMES.GameType and backfill from dim_tm_game.game_type."""
    engine = get_engine()
    result = backfill_game_type(engine, dry_run=dry_run)
    click.echo(
        f"GAMES.GameType backfill: would_update={result['would_update']} dry_run={dry_run}"
    )


@ingest_cli.command("backfill-zone")
@click.option(
    "--dry-run/--no-dry-run", default=True,
    help="Preview only, write nothing (default). Use --no-dry-run to actually update.",
)
def backfill_zone_command(dry_run: bool):
    """One-time: backfill GAMES.Zone from fact_tm_game_pitch.izt_zone (joined on PitchUID)."""
    engine = get_engine()
    result = backfill_zone(engine, dry_run=dry_run)
    click.echo(
        f"GAMES.Zone backfill: would_update={result['would_update']} dry_run={dry_run}"
    )


@ingest_cli.command("hittrax-raw")
@click.option(
    "--dry-run/--no-dry-run", default=True,
    help="Preview only, write nothing (default). Use --no-dry-run to actually insert.",
)
@click.option("--limit", type=int, default=None, help="Limit the number of HitTrax CSV files processed.")
def hittrax_raw_command(dry_run: bool, limit: int | None):
    """Load raw HitTrax exports (Plays/Session CSVs) into `RAW_PRACTICE_CSV` from the FTPS root."""
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
    """Rebuild PRACTICE_SESSIONS/PRACTICE_PLAYS from RAW_PRACTICE_CSV."""
    engine = get_engine()
    result = transform(engine, dry_run=dry_run)
    click.echo(
        f"HitTrax transform: sessions={result['sessions']} plays={result['plays']} "
        f"players={result['players']} dry_run={dry_run}"
    )


@ingest_cli.command("trackman-video-check")
@click.option("--days", type=int, default=7,
             help="How many days back to check for practice sessions "
                  "(max 30, TrackMan's discovery-query limit).")
@click.option("--session-type", type=click.Choice(["All", "Pitching", "Hitting"]), default="All")
def trackman_video_check_command(days: int, session_type: str):
    """Smoke test for the Trackman Data API credentials (TM_API_CLIENT_ID/
    SECRET): authenticate, list practice sessions from the last N days, and
    (for the most recent one) count its Edgertronic video clips. Read-only --
    writes nothing to the DB. This is how to confirm the credentials + the
    account's practice-video access actually work before any real loader is
    built on top of `app.ingest.trackman_video`."""
    import json
    from datetime import datetime, timedelta, timezone

    client = Session(trackman_api_cfg())
    client.get_token()
    click.echo("Authenticated OK.")

    now = datetime.now(timezone.utc)
    date_from = (now - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
    date_to = now.strftime("%Y-%m-%dT23:59:59Z")
    sessions = client.discover_practice_sessions(date_from, date_to, session_type=session_type)
    click.echo(f"Found {len(sessions)} practice session(s) between {date_from} and {date_to}.")
    for s in sessions[:10]:
        click.echo(f"  sessionId={s.get('sessionId')}  "
                   f"date={s.get('gameDateLocal', s.get('gameDateUtc'))}  "
                   f"type={s.get('sessionType')}  external={s.get('externalSessionId')}")

    dumped_sample = False
    for s in sessions:
        session_id = s.get("sessionId")
        metadata = client.practice_video_metadata(session_id)
        by_camera: dict[str, int] = {}
        for row in metadata:
            # TrackMan's docs show `cameraName`; LMU's real account
            # populates `cameraType` instead (cameraName comes back "") --
            # see app.ingest.trackman_video.EDGERTRONIC_CAMERA's docstring.
            cam = row.get("cameraType") or row.get("cameraName") or "(none)"
            by_camera[cam] = by_camera.get(cam, 0) + 1
        breakdown = ", ".join(f"{cam}={n}" for cam, n in sorted(by_camera.items())) or "no clips at all"
        click.echo(f"Session {session_id} ({s.get('gameDateLocal', s.get('gameDateUtc'))}): "
                  f"{len(metadata)} total clip(s) -- {breakdown}")
        clips = edgertronic_clips(metadata)
        if clips:
            click.echo(f"  sample Edgertronic playId={clips[0].get('playId')}")
        if metadata and not dumped_sample:
            click.echo("\nRaw sample clip record (first clip, first session with any):")
            click.echo(json.dumps(metadata[0], indent=2, default=str))
            dumped_sample = True


@ingest_cli.command("bullpen-video")
@click.option(
    "--dry-run/--no-dry-run", default=True,
    help="Preview only, download/write nothing (default). Use --no-dry-run to actually "
         "download clips into the database and index them.",
)
@click.option("--days", type=int, default=3,
             help="How many days back to check for practice sessions (max 29 -- "
                  "see the date-math note below).")
@click.option("--limit", type=int, default=None,
             help="Cap the total number of clips downloaded this run (across all sessions).")
def bullpen_video_command(dry_run: bool, days: int, limit: int | None):
    """Load Edgertronic bullpen video from the TrackMan Data API: discover
    Pitching practice sessions from the last N days, download any
    not-yet-indexed clips, remux them from TrackMan's raw QuickTime .mov to
    browser-playable MP4 (see app.ingest.bullpen_video.remux_to_mp4 -- Chrome
    won't play the raw .mov container), and index the MP4 bytes into
    bullpen_video_clips (a DB BLOB -- see app.data.bullpen_video's module
    docstring for why). Requires TM_API_CLIENT_ID/SECRET (see
    app.ingest.config.trackman_api_cfg) and the `ffmpeg` binary on PATH."""
    from datetime import datetime, timedelta, timezone

    from app.ingest.trackman_video import MAX_DISCOVERY_SPAN_DAYS

    client = Session(trackman_api_cfg())
    now = datetime.now(timezone.utc)
    # date_from pads back to the START of that day and date_to pads forward
    # to the END of today, so the actual span is `days` PLUS almost a full
    # day -- confirmed live (2026-09-22) that --days 30 alone trips
    # TrackMan's 30-day cap ("date-range of 31.99... is too long"). Clamping
    # to MAX_DISCOVERY_SPAN_DAYS - 1 keeps the padded span under the limit.
    days = min(days, MAX_DISCOVERY_SPAN_DAYS - 1)
    date_from = (now - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
    date_to = now.strftime("%Y-%m-%dT23:59:59Z")

    result = load_bullpen_video(client, date_from, date_to, session_type="Pitching",
                                dry_run=dry_run, limit=limit)
    click.echo(
        f"Bullpen video load: sessions={result.sessions} clips_found={result.clips_found} "
        f"downloaded={result.clips_downloaded} skipped_existing={result.clips_skipped_existing} "
        f"missing_blob={result.clips_missing_blob} sessions_errored={result.sessions_errored} "
        f"clips_errored={result.clips_errored} dry_run={result.dry_run}"
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
