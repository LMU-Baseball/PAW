# Pipeline cron (GitHub Actions)

Runs `.github/workflows/pipeline-cron.yml` daily at ~09:30 UTC (and on-demand via
"Run workflow" in the Actions tab, or `gh workflow run pipeline-cron.yml`).

## Jobs

| Job | Command | Mode |
|---|---|---|
| `games` | `flask pipeline-load --dry-run --since-days 3` | Dry-run — writes nothing yet. |
| `bullpen` | `flask ingest bullpen --no-dry-run` | **Live** — writes to `BULLPEN`. |
| `hittrax` | `flask ingest hittrax --dry-run --limit 20` | Dry-run — writes nothing yet. |

## Known issue: HitTrax FTPS connection limit

The HitTrax FTPS server drops the connection if `flask ingest hittrax` tries to
walk all ~580 remote files in one run (confirmed via a local pre-flight test:
fails with `Aborted!`/EOFError with no limit, succeeds with `--limit 5` or
`--limit 10`). The workflow's `hittrax` job uses `--limit 20` to stay safely inside
the working range.

This caps each run to 20 files. Once new daily HitTrax exports (~2 files/day) are
the only thing being pulled, 20 is plenty of headroom. But the current ~580-file
backlog won't clear via the daily cron alone at that pace — before flipping
`hittrax` to `--no-dry-run` (see below), either run a few manual higher-`--limit`
passes to catch the backlog up first, or treat backlog-clearing and building
retry/pagination into `_download`/`extract_load_raw` as separate follow-up work.

## Required repo secrets

Settings → Secrets and variables → Actions → New repository secret. Values come from
the same source as the local `.env` (never commit them):

- `MYSQL_HOST`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DB`
- `TM_SFTP_HOST`, `TM_SFTP_USER`, `TM_SFTP_PASS`
- `HT_FTPS_HOST`, `HT_FTPS_USER`, `HT_FTPS_PASSWORD`, `HT_FTPS_REMOTE_DIR`

(`MYSQL_PORT`/`TM_SFTP_PORT`/`HT_FTPS_PORT` and `TM_SFTP_DIR` are not set — the loaders
default the ports to 3306/22/21, and no current loader reads `TM_SFTP_DIR`.)

## Flipping games/hittrax from dry-run to live

Once fall data is confirmed flowing (check a dry-run run's log for a nonzero
`inserted=` count, or `files=` > 0) and you're satisfied with what it logged:

1. Edit `.github/workflows/pipeline-cron.yml`.
2. In the `games` job, change `--dry-run` to `--no-dry-run` on the `pipeline-load`
   line.
3. In the `hittrax` job, change `--dry-run` to `--no-dry-run` on the `flask ingest
   hittrax` line, keeping `--limit 20` in place (the line becomes `flask ingest
   hittrax --no-dry-run --limit 20`). See the "Known issue: HitTrax FTPS connection
   limit" section above regarding the backlog.
4. Commit and push. No other change needed — the next scheduled or manual run uses
   the new flag.

## Failure notifications

GitHub emails the repo's watchers automatically when a scheduled or manually
dispatched workflow run fails. No extra configuration. Check the failing job's log in
the Actions tab for which loader broke and why.
