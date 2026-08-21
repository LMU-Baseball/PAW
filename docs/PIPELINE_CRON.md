# Pipeline cron (GitHub Actions)

`.github/workflows/pipeline-cron.yml` runs on three daily UTC crons, and each job is
gated to the slots it belongs to: `games` and `hittrax` at ~09:30 UTC (after HitTrax's
~08:40 UTC export), and `bullpen` twice a day at 04:00 and 16:00 UTC so players can see
bullpen reports the same evening as practice. A manual run ("Run workflow" in the
Actions tab, or `gh workflow run pipeline-cron.yml`) still runs all three jobs.

GitHub Actions cron is UTC-only and does not observe daylight saving. The bullpen times
are anchored to PST (UTC-8), so they land at 8pm/8am in winter and drift an hour later
(9pm/9am PDT) in summer. That drift direction is deliberate: an evening run that drifted
*earlier* could fire before practice ends and miss the session entirely.

This is the actual implemented schedule for `flask pipeline-load`. For the
pre-existing manual-run background (what the loader does, pre-flight steps, idempotency)
this grew out of, see `docs/pipeline-cron-runbook.md`.

## Jobs

| Job | Command | Schedule (UTC) | Mode |
|---|---|---|---|
| `games` | `flask pipeline-load --dry-run --since-days 3` | `30 9 * * *` | Dry-run — writes nothing yet. |
| `bullpen` | `flask ingest bullpen --no-dry-run` | `0 4 * * *`, `0 16 * * *` | **Live** — writes to `BULLPEN`. |
| `hittrax` | `flask ingest hittrax --dry-run --limit 20` | `30 9 * * *` | Dry-run — writes nothing yet. |

Because `on.schedule` is workflow-level in GitHub Actions, all three crons fire the whole
workflow; each job carries an `if:` condition on `github.event.schedule` (plus
`github.event_name == 'workflow_dispatch'`) so only the intended jobs actually run.

## Known issue: HitTrax FTPS connection limit AND `--limit` is not incremental

The HitTrax FTPS server drops the connection if `flask ingest hittrax` tries to
walk all ~580 remote files in one run (confirmed via a local pre-flight test:
fails with `Aborted!`/EOFError with no limit, succeeds with `--limit 5` or
`--limit 10`). The workflow's `hittrax` job uses `--limit 20` to stay safely inside
the working range.

**`--limit N` does NOT mean "the newest N files."** `app/ingest/hittrax.py`'s
`_list_csv_files` returns filenames from `sorted()` — plain alphabetical order —
and `extract_load_raw` takes `filenames[:limit]`, an alphabetical *prefix*. HitTrax
export filenames are `PlaysExport_<timestamp>.CSV` / `SessionExport_<timestamp>.CSV`,
so alphabetically every `PlaysExport_*` file sorts before every `SessionExport_*`
file. The FTPS server never deletes old files (currently ~580 files spanning
2025-11-07 to present, growing daily). That means a fixed `--limit 20` selects the
same 20 oldest `PlaysExport_*` files on every single run, forever: it will never
reach a `SessionExport_*` file (so `PRACTICE_SESSIONS` is never fed) and never reach
a new file, no matter how long the cron runs. A fixed `--limit` on this feed is not
an incremental "keep pace with new daily exports" mechanism at all — it just
reprocesses the same oldest files on a loop.

**Do not flip the `hittrax` job to `--no-dry-run` with a fixed `--limit` as it's
currently structured.** Doing so would produce a permanently green CI job that
ingests zero new rows, while `transform()` still runs its full destructive
delete-and-rebuild of `PRACTICE_SESSIONS`/`PRACTICE_PLAYS`/`player_stats_summary`
from that same stale raw data on every run. That's a silent-staleness trap, not a
working incremental pipeline — it would look healthy in the Actions tab while
quietly never ingesting anything new.

Before hittrax can safely go live, the loader needs incremental file selection
(e.g., newest-first ordering instead of alphabetical, or skip filenames whose
`row_hash` already exists in `RAW_PRACTICE_CSV`). That's separate follow-up work,
out of scope for this cron-scheduling round — do not implement it as part of this
doc/workflow change. In the meantime, the current ~580-file backlog also won't
clear via the daily cron alone at `--limit 20`; catching it up (or not) is bundled
into that same follow-up work.

## Required repo secrets

Settings → Secrets and variables → Actions → New repository secret. Values come from
the same source as the local `.env` (never commit them):

- `MYSQL_HOST`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DB`
- `TM_SFTP_HOST`, `TM_SFTP_USER`, `TM_SFTP_PASS`
- `HT_FTPS_HOST`, `HT_FTPS_USER`, `HT_FTPS_PASSWORD`, `HT_FTPS_REMOTE_DIR`

(`MYSQL_PORT`/`TM_SFTP_PORT`/`HT_FTPS_PORT` and `TM_SFTP_DIR` are not set — the loaders
default the ports to 3306/22/21, and no current loader reads `TM_SFTP_DIR`.)

## Flipping games from dry-run to live

Once fall data is confirmed flowing (check a dry-run run's log for a nonzero
`inserted=` count, or `files=` > 0) and you're satisfied with what it logged:

1. Edit `.github/workflows/pipeline-cron.yml`.
2. In the `games` job, change `--dry-run` to `--no-dry-run` on the `pipeline-load`
   line. Leave the job's `if:` condition alone — this flip is about the flag, not the
   schedule.
3. Commit and push. No other change needed — the next scheduled or manual run uses
   the new flag. Note that the first LIVE run that actually inserts rows will also
   trigger `precalc.rebuild_all()` and bump the cache-invalidation version stamp
   (per `app/ingest/pipeline.py`'s `run_pipeline`) — this will be the first time
   that code path runs for real in production, not just locally.

`hittrax` is **not** part of this flip yet — see "Known issue: HitTrax FTPS
connection limit AND `--limit` is not incremental" above for why it must stay
`--dry-run` until incremental file selection is built.

## Changing a schedule

**The cron strings and the job `if:` conditions must be kept in sync.** `on.schedule` is
workflow-level, so every cron triggers the whole workflow and each job decides for itself
whether to run by comparing `github.event.schedule` against a literal cron string. If you
edit a cron in the `on:` block without updating the job condition that matches it, that
job's `if:` will never be true again and the job silently stops running — no failure, no
email, just a workflow run where the job is skipped. This is the easiest way to break this
workflow, so treat it as a two-line change every time.

To change when a job runs:

1. Edit the cron string in the `on.schedule` list in
   `.github/workflows/pipeline-cron.yml`.
2. Edit the **same** string inside that job's `if: ... github.event.schedule == '...'`
   condition. `games` and `hittrax` share the `30 9 * * *` slot, so changing it means
   updating both jobs. `bullpen` matches two crons and needs both updated.
3. Commit and push, then confirm on the next scheduled run that the job shows up in the
   Actions tab rather than being skipped.

Remember the times are UTC and do not shift with daylight saving — see the DST note at
the top of this doc before picking a new hour.

## Failure notifications

GitHub emails automatically when a scheduled or manually dispatched workflow run
fails. No extra configuration needed. Check the failing job's log in the Actions tab
for which loader broke and why.

For a **scheduled** run specifically, GitHub notifies the user who most recently
modified the workflow file — not generically "the repo's watchers" (that phrasing
applies to other GitHub notification types, not scheduled-workflow failures). If
that person changes, notifications silently move with them.

**Silent-death mode:** GitHub automatically disables a scheduled workflow after 60
days with no repository activity/commits, and a disabled schedule sends no failure
email at all — it simply stops running, so there's nothing to fail loudly. This is a
real risk during a long offseason gap between semesters. A `workflow_dispatch` run
or any commit to the repo resets the 60-day clock. During long quiet stretches,
periodically check the Actions tab (or `gh workflow list`) to confirm the schedule is
still enabled rather than relying on email alone.
