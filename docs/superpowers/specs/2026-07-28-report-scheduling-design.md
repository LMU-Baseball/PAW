# SP5 — Report Scheduling (design-only; wired at deploy)

Date: 2026-07-28
Status: Design-only (user decision 2026-07-28). No code this round.

## Purpose

Document how post-game reports will auto-run on a schedule so coaches have
next-morning access without manually triggering builds. Implementation is
deferred until deployment (it requires an always-on host + a confirmed Trackman
ingest cadence). This spec captures the approach so it can be executed quickly
at deploy time.

## Model

**Next-morning delivery via warm cache.** A scheduled job runs after the
overnight Trackman ingest and pre-generates each LMU pitcher's postgame PDF for
the most recent game(s), populating the existing on-disk cache
(`instance/report_cache/`, keyed by `report_data_version`). Because the report
route already serves cached bytes in ~0.3s, a coach's morning download is
instant instead of a ~5s cold build per pitcher.

**Late-night fallback.** The Trackman CSV upload timing is not guaranteed. Run
the job twice: a first pass late at night (e.g. ~1:00) and a fallback pass early
morning (e.g. ~6:00). The fallback re-checks for games ingested since the first
pass (compare `tm_ingest_file` / newest `dim_tm_game.game_date`) and builds any
that were missed. Idempotent: a game already cached at the current data version
is skipped.

## Trigger mechanism (decide at deploy, by host)

- **Preferred (Linux/container host):** a system `cron` entry (or a container
  sidecar cron) invoking a Flask CLI command.
- **Windows host:** Task Scheduler invoking the same CLI command.
- **In-process option (only if the app must self-schedule):** APScheduler
  background scheduler started in `create_app` under a run-once guard. Avoid
  unless there is no external scheduler — it complicates the single-writer /
  reloader story (§3b/§5 gotchas).

New Flask CLI command (to build at deploy): `flask --app run warm-reports
[--date YYYY-MM-DD] [--all-recent]` in `app/cli.py`. It resolves the target
game(s) via `P.recent_games` / `pitchers_for_game`, then calls
`build_pitcher_postgame(game_id, pitcher_id)` for each LMU pitcher (reusing the
exact code path + gate the landing page uses), logging successes/skips. No new
report logic — pure orchestration of the existing builder.

## Delivery (phased)

1. **Phase 1 (launch):** warm cache only. Coaches pull from
   `/reports/pitching`. Zero new delivery infra.
2. **Phase 2 (later, optional):** email the per-game ZIP
   (`pitching_all_zip` already builds it) to a coach distribution list after the
   morning pass; or drop the ZIP to a shared drive.

## Dependencies / blockers (must resolve before implementing)

1. **A resolved always-on deploy host** — there is no scheduler on a dev laptop.
   Tied to the deployment effort (`docs/deploy-aws.md`).
2. **Confirmed Trackman ingest cadence** — memory §9: the loader
   (`tm_game_loader_v3`) is dormant out of season; its first fall-2026 game is
   the real test. Scheduling a warm-up is pointless until games actually ingest
   overnight. Watch `tm_ingest_file` for the first fall game.

## Explicitly out of scope now

No CLI command, scheduler, or email code is written this round. Mobile
optimization is likewise deferred until after deployment (meeting note). This
document is the deliverable; revisit at deploy time.
