# Pipeline Automation & Scheduling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Schedule the three already-merged ingest CLI commands (`flask pipeline-load`,
`flask ingest bullpen`, `flask ingest hittrax`) to run daily via GitHub Actions, so the
pipeline is live-tested (connectivity/auth, not yet real data) before fall files start
arriving.

**Architecture:** A single GitHub Actions workflow file with three independent jobs
(one per loader), triggered by both a daily `schedule:` cron and a manual
`workflow_dispatch:`. No application code changes — this is CI/infra wiring around
existing, already-tested CLI commands. Secrets live in the GitHub repo's Actions
secrets store, named to match the existing `.env.example` convention.

**Tech Stack:** GitHub Actions (`actions/checkout@v4`, `actions/setup-python@v5`),
Python 3.12, the repo's existing Flask CLI (`python -m flask --app run ...`).

**Spec:** `docs/superpowers/specs/2026-08-19-pipeline-automation-scheduling-design.md`

## Global Constraints

- No application code changes in this plan — only `.github/workflows/`, one new docs
  file, and (outside git) GitHub repo secrets.
- `bullpen` job runs live (`--no-dry-run`) from day one. `games` and `hittrax` jobs run
  `--dry-run` only in this round (per spec §2's rollout table) — do not add
  `--no-dry-run` to those two commands anywhere in this plan.
- Skip `playwright install chromium` in the workflow — no PDF/browser rendering happens
  on any ingest path, and the browser download is unnecessary CI time.
- Never print secret values to logs, commit messages, or this plan's output.

---

## Task 1: Local pre-flight — confirm the three commands still boot and connect

This has no file deliverable; it's a correctness gate before Task 2 encodes these exact
commands into YAML. Uses the maintainer's local `.env` (already has all required vars
per `app/ingest/config.py` / `config.py`: `MYSQL_HOST/USER/PASSWORD/DB`,
`TM_SFTP_HOST/USER/PASS`, `HT_FTPS_HOST/USER/PASSWORD/REMOTE_DIR`; the `*_PORT` vars and
`TM_SFTP_DIR` are either optional-with-defaults or unused by the current loaders).

**Files:** none.

**Interfaces:**
- Consumes: `flask pipeline-load`, `flask ingest bullpen`, `flask ingest hittrax` (all
  already implemented in `app/cli.py` / `app/ingest/cli.py`).
- Produces: confirmation that all three commands exit 0 in dry-run against prod RDS +
  the live SFTP/FTPS servers, from a fresh shell — the same precondition the GitHub
  Actions runner will be in.

- [ ] **Step 1: Run the games pipeline dry-run**

```bash
PYTHONIOENCODING=utf-8 python -m flask --app run pipeline-load --dry-run --since-days 3
```

Expected: exits 0, prints a `pipeline-load: files=... inserted=0 ... dry_run=True`
summary line. `inserted=0` is expected (offseason — no new upload-window files).

- [ ] **Step 2: Run the bullpen dry-run**

```bash
PYTHONIOENCODING=utf-8 python -m flask --app run ingest bullpen --dry-run
```

Expected: exits 0, prints a `BULLPEN load: files=... inserted=0 ... dry_run=True`
summary (`inserted=0` because prior runs already dedup'd everything present).

- [ ] **Step 3: Run the hittrax dry-run**

```bash
PYTHONIOENCODING=utf-8 python -m flask --app run ingest hittrax --dry-run
```

Expected: exits 0, prints `HitTrax raw load: ...` then `HitTrax transform: ...` summary
lines, `dry_run=True`.

- [ ] **Step 4: If any command fails**

Stop and diagnose before proceeding to Task 2 — a local failure now means the GitHub
Actions job will fail identically (same code, same creds, same servers). Common causes:
a stale/rotated credential in `.env`, or a network egress block specific to this
environment (unlikely — recon in memory §10 already confirmed both servers reachable
from a Windows dev box; GitHub's runners are a different network and reachability
there is exactly what Task 5's manual dispatch will separately confirm).

---

## Task 2: Create the GitHub Actions workflow

**Files:**
- Create: `.github/workflows/pipeline-cron.yml`

**Interfaces:**
- Consumes: the three CLI commands verified in Task 1; secrets named
  `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DB`,
  `TM_SFTP_HOST`, `TM_SFTP_PORT`, `TM_SFTP_USER`, `TM_SFTP_PASS`,
  `HT_FTPS_HOST`, `HT_FTPS_PORT`, `HT_FTPS_USER`, `HT_FTPS_PASSWORD`, `HT_FTPS_REMOTE_DIR`
  (set in Task 4; the `*_PORT` ones are optional overrides — the loaders default to
  22/21 — included here only for parity with `.env.example`, harmless if unset since
  `env:` maps an unset secret to an empty string which `os.getenv("X", default)` on an
  *unset* var — not an empty one — would still fall back to; to avoid the edge case
  where GitHub sets an empty-string env var and defeats the Python default, this
  workflow simply omits the `*_PORT` keys from `env:` entirely rather than mapping them
  from possibly-unset secrets).
- Produces: a scheduled + manually-dispatchable workflow named `pipeline-cron.yml` with
  jobs `games`, `bullpen`, `hittrax` — the name each job will be referred to by in
  `gh run` output and the Actions UI.

- [ ] **Step 1: Write the workflow file**

```yaml
name: pipeline-cron

on:
  schedule:
    - cron: "30 9 * * *"   # ~09:30 UTC daily — after HitTrax's ~08:40 UTC export
  workflow_dispatch: {}     # manual "Run workflow" button, for on-demand verification

jobs:
  games:
    runs-on: ubuntu-latest
    env:
      MYSQL_HOST: ${{ secrets.MYSQL_HOST }}
      MYSQL_USER: ${{ secrets.MYSQL_USER }}
      MYSQL_PASSWORD: ${{ secrets.MYSQL_PASSWORD }}
      MYSQL_DB: ${{ secrets.MYSQL_DB }}
      TM_SFTP_HOST: ${{ secrets.TM_SFTP_HOST }}
      TM_SFTP_USER: ${{ secrets.TM_SFTP_USER }}
      TM_SFTP_PASS: ${{ secrets.TM_SFTP_PASS }}
      PYTHONIOENCODING: utf-8
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      # DRY-RUN ONLY this round (see spec §2 rollout table). Flip to
      # --no-dry-run once fall data is confirmed flowing and a few dry-run
      # runs have been reviewed.
      - run: python -m flask --app run pipeline-load --dry-run --since-days 3

  bullpen:
    runs-on: ubuntu-latest
    env:
      MYSQL_HOST: ${{ secrets.MYSQL_HOST }}
      MYSQL_USER: ${{ secrets.MYSQL_USER }}
      MYSQL_PASSWORD: ${{ secrets.MYSQL_PASSWORD }}
      MYSQL_DB: ${{ secrets.MYSQL_DB }}
      TM_SFTP_HOST: ${{ secrets.TM_SFTP_HOST }}
      TM_SFTP_USER: ${{ secrets.TM_SFTP_USER }}
      TM_SFTP_PASS: ${{ secrets.TM_SFTP_PASS }}
      PYTHONIOENCODING: utf-8
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      # LIVE from day one — already run against prod once (2026-08) and
      # proved safe (insert-only, PlayID-deduped).
      - run: python -m flask --app run ingest bullpen --no-dry-run

  hittrax:
    runs-on: ubuntu-latest
    env:
      MYSQL_HOST: ${{ secrets.MYSQL_HOST }}
      MYSQL_USER: ${{ secrets.MYSQL_USER }}
      MYSQL_PASSWORD: ${{ secrets.MYSQL_PASSWORD }}
      MYSQL_DB: ${{ secrets.MYSQL_DB }}
      HT_FTPS_HOST: ${{ secrets.HT_FTPS_HOST }}
      HT_FTPS_USER: ${{ secrets.HT_FTPS_USER }}
      HT_FTPS_PASSWORD: ${{ secrets.HT_FTPS_PASSWORD }}
      HT_FTPS_REMOTE_DIR: ${{ secrets.HT_FTPS_REMOTE_DIR }}
      PYTHONIOENCODING: utf-8
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      # DRY-RUN ONLY this round (see spec §2 rollout table). Flip to
      # --no-dry-run once fall data is confirmed flowing and a few dry-run
      # runs have been reviewed.
      - run: python -m flask --app run ingest hittrax --dry-run
```

- [ ] **Step 2: Validate the YAML parses**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/pipeline-cron.yml'))" && echo OK
```

Expected: `OK` (a parse error means a YAML syntax mistake — fix before continuing).

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/pipeline-cron.yml
git commit -m "feat(pipeline): schedule games/bullpen/hittrax ingest via GitHub Actions cron"
```

---

## Task 3: Document the required secrets and the dry-run→live flip

**Files:**
- Create: `docs/PIPELINE_CRON.md`

**Interfaces:**
- Consumes: the exact secret names from Task 2's workflow file.
- Produces: a doc future-you (or an intern) reads before touching the workflow again —
  no other task depends on this file's content, but it's the reference for Task 4.

- [ ] **Step 1: Write the doc**

```markdown
# Pipeline cron (GitHub Actions)

Runs `.github/workflows/pipeline-cron.yml` daily at ~09:30 UTC (and on-demand via
"Run workflow" in the Actions tab, or `gh workflow run pipeline-cron.yml`).

## Jobs

| Job | Command | Mode |
|---|---|---|
| `games` | `flask pipeline-load --dry-run --since-days 3` | Dry-run — writes nothing yet. |
| `bullpen` | `flask ingest bullpen --no-dry-run` | **Live** — writes to `BULLPEN`. |
| `hittrax` | `flask ingest hittrax --dry-run` | Dry-run — writes nothing yet. |

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
   hittrax` line.
4. Commit and push. No other change needed — the next scheduled or manual run uses
   the new flag.

## Failure notifications

GitHub emails the repo's watchers automatically when a scheduled or manually
dispatched workflow run fails. No extra configuration. Check the failing job's log in
the Actions tab for which loader broke and why.
```

- [ ] **Step 2: Commit**

```bash
git add docs/PIPELINE_CRON.md
git commit -m "docs(pipeline): document cron secrets and the dry-run to live flip"
```

---

## Task 4: Add the GitHub Actions secrets (requires explicit go-ahead)

This task pushes real production credentials (from the local `.env`) into GitHub's
Actions secrets store for the `LMU-Baseball/PAW` repo. **Do not run this task's
commands without the user explicitly confirming in-session first** — it's the one step
in this plan that reaches outside the local repo into a third-party system holding
live credentials.

**Files:** none (GitHub repo settings, not tracked in git).

**Interfaces:**
- Consumes: the 11 required values from the local `.env` (Task 1 already confirmed
  they're current/working).
- Produces: the 11 secrets Task 2's workflow reads via `${{ secrets.NAME }}`.

- [ ] **Step 1: Confirm with the user before running anything in this task**

Ask explicitly: "About to push the 11 required secrets from your local `.env` into
the `LMU-Baseball/PAW` GitHub repo's Actions secrets. OK to proceed?" Wait for a yes.

- [ ] **Step 2: Set each secret from the local `.env` via `gh`**

`gh` is already authenticated (confirmed: `bradhaskell`, `repo` scope). Run from the
repo root, one secret at a time, sourcing values straight from `.env` so the values
never appear in shell history or this session's visible output:

```bash
set -a; source .env; set +a
gh secret set MYSQL_HOST --body "$MYSQL_HOST"
gh secret set MYSQL_USER --body "$MYSQL_USER"
gh secret set MYSQL_PASSWORD --body "$MYSQL_PASSWORD"
gh secret set MYSQL_DB --body "$MYSQL_DB"
gh secret set TM_SFTP_HOST --body "$TM_SFTP_HOST"
gh secret set TM_SFTP_USER --body "$TM_SFTP_USER"
gh secret set TM_SFTP_PASS --body "$TM_SFTP_PASS"
gh secret set HT_FTPS_HOST --body "$HT_FTPS_HOST"
gh secret set HT_FTPS_USER --body "$HT_FTPS_USER"
gh secret set HT_FTPS_PASSWORD --body "$HT_FTPS_PASSWORD"
gh secret set HT_FTPS_REMOTE_DIR --body "$HT_FTPS_REMOTE_DIR"
```

- [ ] **Step 3: Verify the secret names registered (not values — `gh` never shows values)**

```bash
gh secret list
```

Expected: all 11 names listed, each with an "Updated" timestamp of just now.

No commit — nothing in this task touches git.

---

## Task 5: Manual dispatch — verify all three jobs run green end-to-end

**Files:** none.

**Interfaces:**
- Consumes: the workflow from Task 2, the secrets from Task 4.
- Produces: the first real (non-local) proof that GitHub Actions' network can reach
  RDS + the Trackman SFTP + the HitTrax FTPS server and authenticate to all three —
  the actual goal of this whole plan.

- [ ] **Step 1: Trigger a manual run**

```bash
gh workflow run pipeline-cron.yml
```

- [ ] **Step 2: Watch it to completion**

```bash
gh run watch $(gh run list --workflow=pipeline-cron.yml --limit 1 --json databaseId --jq '.[0].databaseId')
```

Expected: all three jobs (`games`, `bullpen`, `hittrax`) complete with a green check.

- [ ] **Step 3: Read each job's log for its summary line**

```bash
gh run view --log $(gh run list --workflow=pipeline-cron.yml --limit 1 --json databaseId --jq '.[0].databaseId')
```

Confirm: `games` shows `dry_run=True`; `bullpen` shows `dry_run=False` with an
`inserted=` count (0 is fine — means dedup correctly found nothing new); `hittrax`
shows `dry_run=True` for both its raw-load and transform lines. Any job that errored
instead of printing its summary line means a secret or connectivity problem — fix
before considering this plan done.

- [ ] **Step 4: Report back**

No commit — summarize the run result (all three green? any failures + why) so the
user knows the pipeline is live-scheduled and what, if anything, still needs fixing
before fall.

---

## Plan self-review notes

- **Spec coverage:** §1 (GH Actions venue) → Task 2. §2 (commands/rollout modes) →
  Task 2 (per-job flags) + Task 3 (flip instructions). §3 (secrets) → Task 2
  (interfaces) + Task 4, corrected from the spec's approximate 15-name list down to
  the 11 actually required (`SECRET_KEY` has a code-level dev fallback so CLI boot
  doesn't need it; `TM_SFTP_DIR` is unused by any current loader; the `*_PORT` vars
  have working defaults) — this is a precision fix, not a scope change, and matches
  the spec's intent (secrets "named to match `.env.example`" — a strict subset of
  those names). §4 (failure surfacing = default email) → Task 3's doc, no code. §5
  (offseason validation = plumbing not data) → Task 1 (local) + Task 5 (CI). §6 (out
  of scope) → nothing in this plan touches bullpen/hittrax windowing, alerting beyond
  email, or Performance Council — confirmed no task drifts into those.
- **Placeholder scan:** no TBD/TODO; every step has literal commands or file content.
- **Type/name consistency:** job names (`games`/`bullpen`/`hittrax`) and the workflow
  filename (`pipeline-cron.yml`) are identical across Tasks 2, 3, and 5's `gh`
  invocations.
