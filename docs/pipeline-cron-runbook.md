# Daily pipeline cron — runbook

The verifiable core is built + unit-tested (`flask pipeline-load`, LMU-aware
upload-folder-pruned SFTP selection, keepalive, cross-process cache
invalidation). This runbook covers the two **deferred** steps that need live
data + supervision — do them in **Fall 2026** once real games start uploading.

## What `pipeline-load` does

```
flask --app run pipeline-load [--dry-run|--no-dry-run] [--since-days N]
```

1. Opens the Trackman SFTP (keepalive on) and walks only `/v3/YYYY/MM/DD`
   upload folders from the last `--since-days` days (default 3).
2. Parses each game CSV; keeps only games LMU played (`is_lmu_game`); dedups on
   `PitchUID`; inserts new rows into `GAMES` (insert-only). `--dry-run` (the
   default) writes nothing and just reports counts.
3. On a real run (`--no-dry-run`) that inserted rows, rebuilds all precalc
   rollups and bumps `precalc_meta.version` (which makes running web workers
   drop their caches within ~60s).

## Pre-flight (required, supervised)

1. Set the Trackman SFTP secrets in `.env` (never commit): `TM_SFTP_HOST`,
   `TM_SFTP_PORT` (default 22), `TM_SFTP_USER`, `TM_SFTP_PASS`. Without these
   the command fails fast on the config guard — that's expected in the
   offseason.
2. **Dry-run first** and eyeball the output — confirm `files`/`inserted`/
   `non_lmu` look right and the date span matches the new games:
   ```
   flask --app run pipeline-load --dry-run --since-days 7
   ```
3. Only then do a real run:
   ```
   flask --app run pipeline-load --no-dry-run --since-days 3
   ```
   Idempotent: re-running skips already-loaded PitchUIDs.

## Scheduling (choose one, once verified)

**Superseded:** `flask pipeline-load` is now actually scheduled via GitHub Actions —
see `docs/PIPELINE_CRON.md` and `.github/workflows/pipeline-cron.yml` (the `games`
job, currently `--dry-run`). The options below predate that and are historical
background only; don't stand up a second, duplicate schedule for the same loader
from this list.

- **OS cron (Linux host)** — daily at, say, 06:00:
  ```
  0 6 * * *  cd /path/to/PAW && /path/to/venv/bin/flask --app run pipeline-load --no-dry-run --since-days 3 >> /var/log/paw-pipeline.log 2>&1
  ```
- **Windows Task Scheduler** — a daily task running the same `flask ... pipeline-load --no-dry-run` line.
- **Claude Code scheduled agent** — the `schedule` skill can run it on a cron.

Keep `--since-days` comfortably larger than the cron interval (a few days) so a
missed run self-heals on the next one (dedup makes overlap harmless).

## Notes / limits

- `--since-days` prunes by **upload** date (folder date), which is correct for
  incremental daily runs; a one-time historical backfill is NOT this tool's job
  (history was already backfilled from the warehouse in Phase 1).
- If you run a very large `--since-days` (hundreds of days), the walk grows
  toward the full ~50k-file `/v3` swamp; the keepalive helps but keep the window
  small for the daily job.
