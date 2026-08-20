# Pipeline automation & scheduling design

**Date:** 2026-08-19
**Status:** Design approved. Builds the GitHub Actions scheduling layer around the
already-merged ingest CLI (`flask ingest bullpen|games|hittrax`, `flask pipeline-load`).
No loader logic changes in this round.

## Goal

Get the Trackman/HitTrax data pipeline running on a real, unattended daily schedule
*before* fall practice/games start, so any wiring problems (bad secrets, unreachable
servers, a broken CLI invocation) surface now — via harmless no-op runs against an
empty offseason feed — instead of during the season when stale dashboards would be
the first symptom.

## Context

Three loaders already exist and are merged to `main`, each dry-run-capable and
idempotent (insert-only + dedup keys, or transactional delete-rebuild for HitTrax's
transform step):

- `flask pipeline-load` (`app/ingest/pipeline.py`) — Trackman SFTP `/v3` game files →
  `GAMES`, LMU-filtered, upload-window-pruned (`--since-days`, default 3), triggers
  `precalc.rebuild_all` + a cache-version bump on a live run with inserts. Built per
  `docs/superpowers/specs/2026-08-07-pipeline-cron-design.md`. **Never run against prod.**
- `flask ingest bullpen` (`app/ingest/bullpen.py`) — Trackman SFTP `/practice` pitching
  session files → `BULLPEN`. Full-tree walk each run (no window pruning). **Run against
  prod once already** (2026-08, backfill — see memory §3k), proved safe.
- `flask ingest hittrax` (`app/ingest/hittrax.py`) — HitTrax FTPS flat root →
  `RAW_PRACTICE_CSV` → transform → `practice_sessions`/`practice_plays`/
  `player_stats_summary`. Full-tree walk each run. **Never run against prod.**

None of the three has ever been scheduled. Render's free-tier web service has no
cron/worker dyno, so the schedule lives outside Render entirely.

## Design

### 1. Where it runs: GitHub Actions, in this repo

New workflow file `.github/workflows/pipeline-cron.yml`. Triggers:

```yaml
on:
  schedule:
    - cron: "30 9 * * *"   # ~09:30 UTC daily — after HitTrax's ~08:40 UTC export
  workflow_dispatch: {}     # manual "Run workflow" button, for on-demand testing
```

Three independent jobs (`games`, `bullpen`, `hittrax`), each: checkout →
`actions/setup-python@v5` (3.12) → `pip install -r requirements.txt` (Playwright's
Python package installs; `playwright install chromium` is skipped — no PDF rendering
happens in any ingest path) → run its CLI command via
`python -m flask --app run <command>` with `PYTHONIOENCODING=utf-8` and secrets as env.

Jobs are independent (different tables, no shared write path) and run in parallel —
one job failing doesn't block or mask the others, and each shows its own pass/fail in
the run summary.

### 2. Commands & rollout mode

| Job | Command | Mode |
|---|---|---|
| bullpen | `flask ingest bullpen --no-dry-run` | **Live now** — already proven against prod. |
| games | `flask pipeline-load --dry-run --since-days 3` | **Dry-run** — flip to `--no-dry-run` after reviewing real fall output. |
| hittrax | `flask ingest hittrax --dry-run` | **Dry-run** — same reasoning; never touched prod. |

Flipping a dry-run job to live is a one-line edit to the workflow file (change the
flag) + push. No code change, no redeploy.

### 3. Secrets

GitHub repo secrets (Settings → Secrets and variables → Actions), named to match
`.env.example`: `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DB`,
`TM_SFTP_HOST`, `TM_SFTP_PORT`, `TM_SFTP_USER`, `TM_SFTP_PASS`, `TM_SFTP_DIR`,
`HT_FTPS_HOST`, `HT_FTPS_PORT`, `HT_FTPS_USER`, `HT_FTPS_PASSWORD`,
`HT_FTPS_REMOTE_DIR`, `SECRET_KEY` (Flask app boot requires it even for CLI-only use).
No `APP_DATABASE_URL`/`APP_DB_NAME` needed — the ingest commands never touch the app DB;
letting it fall back to an ephemeral runner-local SQLite file is fine.

### 4. Failure surfacing

GitHub's default behavior: a failed scheduled/dispatched workflow run emails the
repo's watchers (you). No additional code — this was the explicit choice over a
health-page indicator or a Slack webhook, to keep this round scoped.

### 5. Validation now (offseason)

There's no live game/practice data yet, so "testing" this round means proving the
plumbing rather than the data:

- The workflow triggers (schedule registered, manually dispatchable).
- Secrets resolve and the Flask app boots under `flask --app run`.
- Each job actually reaches its target (RDS for all three; SFTP for games/bullpen;
  FTPS for hittrax) and authenticates — even though the real result is "0 files in
  window" or "0 new rows" for games/bullpen (offseason) and whatever HitTrax's current
  export volume is.
- A manual `workflow_dispatch` run during implementation, watched end-to-end, stands
  in for the "first real cron fire" since the scheduled time won't have passed yet.

### 6. Out of scope (explicit deferrals)

- Adding upload-window pruning to `bullpen`/`hittrax` (mirroring what `games` already
  has) — both do a full-directory walk every run. Safe today at current file counts
  (idempotent dedup); revisit if a run's walk time becomes a problem.
- Any alerting beyond GitHub's default failure email (no health-page indicator, no
  Slack/webhook).
- The Performance Council board (unrelated feature, separate ticket).
- Making bullpen/hittrax's target scope LMU-only at load time (they already scope LMU
  at *read* time via team-code filters in `app/data/bullpen.py` / the practice tables;
  changing the *load* to filter would be a loader-logic change, not scheduling).

## Testing

No new unit tests are needed — the loaders' logic is already covered by existing
tests (per the 2026-08-07 spec and the ingestion-loaders branch's own test suite).
What's added here is infrastructure (a workflow YAML + repo secrets), verified by:

- `flask --app run ingest bullpen --dry-run` / `games --dry-run` (via `pipeline-load
  --dry-run`) / `hittrax --dry-run` run manually with the same env the workflow will
  use (to catch boot/secret problems before wiring the workflow).
- A manual `workflow_dispatch` run of the finished workflow, all three jobs green.
- Full existing test suite stays green (no application code changes).

## Success criteria

`.github/workflows/pipeline-cron.yml` exists, scheduled daily + manually dispatchable;
all three jobs run green on a manual dispatch (bullpen live, games/hittrax dry-run);
secrets are set in the repo (not committed); flipping games/hittrax to live later is a
one-line workflow edit with no code change.
