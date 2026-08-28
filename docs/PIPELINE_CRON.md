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
| `games` | `flask pipeline-load --no-dry-run --since-days 3` | `30 9 * * *` | **Live** as of 2026-08-28 — writes to `GAMES`, triggers `precalc.rebuild_all()` on any insert. |
| `bullpen` | `flask ingest bullpen --no-dry-run` | `0 4 * * *`, `0 16 * * *` | **Live** — writes to `BULLPEN`. |
| `hittrax` | `flask ingest hittrax --no-dry-run --limit 20` | `30 9 * * *` | **Live** as of 2026-08-28 — writes to `RAW_PRACTICE_CSV`, rebuilds `PRACTICE_SESSIONS`/`PRACTICE_PLAYS`. |

Because `on.schedule` is workflow-level in GitHub Actions, all three crons fire the whole
workflow; each job carries an `if:` condition on `github.event.schedule` (plus
`github.event_name == 'workflow_dispatch'`) so only the intended jobs actually run.

## HitTrax FTPS connection limit (still applies) + selection (FIXED 2026-08-28)

The HitTrax FTPS server drops the connection if `flask ingest hittrax` tries to
walk all ~600 remote files in one run (confirmed via a local pre-flight test:
fails with `Aborted!`/EOFError with no limit, succeeds with `--limit 5` or
`--limit 10`). The workflow's `hittrax` job uses `--limit 20` to stay safely inside
the working range — this constraint is about how many files one FTPS session can
download, and is unrelated to which files get picked, so it still applies and
`--limit` should stay conservative regardless of the fix below.

**RESOLVED: `--limit N` used to mean "the alphabetically-first N files," not
"the newest N."** `app/ingest/hittrax.py`'s `_list_csv_files` returns filenames
from `sorted()` — plain alphabetical order — and `extract_load_raw` took
`filenames[:limit]`, an alphabetical *prefix*. HitTrax export filenames are
`PlaysExport_<timestamp>.CSV` / `SessionExport_<timestamp>.CSV`, so alphabetically
every `PlaysExport_*` file sorts before every `SessionExport_*` file. The FTPS
server never deletes old files (~600 files spanning 2025-11-07 to present, growing
daily). That meant a fixed `--limit 20` selected the same 20 oldest `PlaysExport_*`
files on every single run, forever: it would never reach a `SessionExport_*` file
(so `PRACTICE_SESSIONS` was never fed) and never reach a new file, no matter how
long the cron ran.

**Fixed in `app/ingest/hittrax.py`'s `extract_load_raw`, live mode only
(`dry_run=False`):** the file list is now filtered against
`_already_loaded_files(engine)` (every distinct `source_file` already in
`RAW_PRACTICE_CSV` — a prior run already fully attempted it; re-processing it
would insert nothing new anyway thanks to `row_hash` + `INSERT IGNORE`) and
sorted newest-first by the timestamp embedded in the filename (`_sort_key`,
interleaving `PlaysExport_*`/`SessionExport_*` correctly by actual export time
instead of by name) before `--limit` is applied. Every run's `--limit` budget now
goes toward genuinely new files, newest first, with the historical backlog filling
in behind that over subsequent daily runs (~30 runs to fully clear the backlog at
`--limit 20`, since each run also has to pick up that day's ~2 new files first).
`dry_run=True` deliberately keeps its old behavior (no DB read, no exclusion) —
see the docstring for why.

This was the blocker for flipping `hittrax` to live — see the next section.

## Required repo secrets

Settings → Secrets and variables → Actions → New repository secret. Values come from
the same source as the local `.env` (never commit them):

- `MYSQL_HOST`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DB`
- `TM_SFTP_HOST`, `TM_SFTP_USER`, `TM_SFTP_PASS`
- `HT_FTPS_HOST`, `HT_FTPS_USER`, `HT_FTPS_PASSWORD`, `HT_FTPS_REMOTE_DIR`

(`MYSQL_PORT`/`TM_SFTP_PORT`/`HT_FTPS_PORT` and `TM_SFTP_DIR` are not set — the loaders
default the ports to 3306/22/21, and no current loader reads `TM_SFTP_DIR`.)

## `games` flipped to live (2026-08-28)

A scoped dry-run (`--since-days 21`) confirmed the SFTP walk + LMU filter work
correctly before flipping: `files=9 inserted=0 skipped=0 non_lmu=9` — 9 files
present in the last 3 weeks of upload folders, all correctly identified as
non-LMU (other programs' fall data on the shared Trackman SFTP), zero would-be
LMU inserts. LMU's own fall games hadn't started uploading yet as of that check,
which is exactly why the flip happened anyway rather than waiting: with the flag
already live, the very first LMU upload gets picked up automatically on the next
09:30 UTC run — nobody has to remember to come back and flip it once the season
starts. The first LIVE run that actually inserts rows will also trigger
`precalc.rebuild_all()` and bump the cache-invalidation version stamp (per
`app/ingest/pipeline.py`'s `run_pipeline`).

**To roll back:** edit `.github/workflows/pipeline-cron.yml`, change
`--no-dry-run` back to `--dry-run` on the `games` job's `pipeline-load` line,
commit and push.

## `hittrax` flipped to live (2026-08-28)

The selection bug that used to block this is fixed (see the section above) — the
loader now skips files already in `RAW_PRACTICE_CSV` and takes what's left
newest-first, so a live run makes real progress every day instead of looping on
the same stale alphabetical prefix. `--limit 20` is unchanged (already proven to
work over this FTPS connection via the prior dry-run jobs).

Each live run loads up to 20 new raw files (newest first) into
`RAW_PRACTICE_CSV`, then `transform()` rebuilds `PRACTICE_SESSIONS`/
`PRACTICE_PLAYS` from the full raw table (atomic — see `transform`'s docstring
for why `DELETE`, not `TRUNCATE`). Expect the ~600-file backlog to keep clearing
gradually behind the live edge — at `--limit 20`/day (minus ~2 consumed by that
day's new export), full catch-up takes several weeks. That's expected, not a
bug: recent practice data reaches the dashboards on the very next run, and the
historical backlog fills in behind it.

**To roll back:** edit `.github/workflows/pipeline-cron.yml`, change
`--no-dry-run` back to `--dry-run` on the `hittrax` job's `ingest hittrax` line,
commit and push.

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
