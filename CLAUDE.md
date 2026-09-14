# CLAUDE.md — instructions for AI assistants working in this repo

This file is for **Claude Code** (and any AI assistant) working in the PAW
codebase, including intern-driven sessions. `README.md` and `CONTRIBUTING.md`
are the canonical human-facing docs — this file exists so an AI assistant
follows the same rules automatically, without an intern having to remember to
ask for them.

If anything here conflicts with a direct instruction from the person you're
working with in a given session, ask before overriding — but the rules below
should be the default, not something an intern has to request each time.

## The one rule that matters most

**Never push to `main`. Always work on a branch and open a Pull Request.**
`main` auto-deploys to the live app coaches and players use — see
`docs/DEPLOY.md`. This applies even if a command would technically succeed.

## Definition of "done" for any task

A task is not finished when the code change is made — it's finished when a PR
exists for a human to review. At the end of any piece of work:

1. `git checkout main && git pull` before branching, if not already current.
2. Branch name: `your-name/what-you-are-doing` (e.g. `maria/fix-velo-chart`).
3. Run the relevant tests before committing — at minimum the file(s) you
   touched (`python -m pytest tests/test_hitting.py -q`), and the full suite
   (`python -m pytest -q`) before opening the PR if time allows (it takes
   ~16 minutes and needs the real `.env`).
4. Stage **only the files you meant to change** — run `git status` first and
   `git add path/to/file.py` one at a time. **Never `git add .` or
   `git add -A`.** This repo has local scratch/notes directories
   (`memory/`, `.superpowers/`) that must never be committed.
5. Commit with a short, conventional message (`fix: ...`, `feat: ...`).
6. `git push -u origin your-name/what-you-are-doing`, then open the PR on
   GitHub (or with `gh pr create`) and fill in the PR template — what changed,
   how it was tested, a screenshot if anything visual changed.
7. Do not merge it yourself. `CODEOWNERS` auto-requests Brad's review; wait
   for that.

Follow `CONTRIBUTING.md` exactly for the git mechanics — this section
summarizes it for an AI assistant, it doesn't replace it.

## Secrets

- Never read, print, commit, or paste the contents of `.env` anywhere
  (chat, commit message, PR description, issue). It holds live database and
  FTPS/SFTP credentials for a **public** repo.
- If a task looks like it needs a new secret or credential, stop and ask
  rather than hardcoding one or inventing a placeholder that looks real.
- `memory/` (this assistant's own notes) is gitignored on purpose — never add
  it to a commit even by accident via a broad `git add`.

## Matching the existing look and structure

Coaches compare dashboards against each other, so new work should look like
it belongs, not like a one-off. Before building a new dashboard, chart, or
report:

- **Reuse `app/dashboards/shell.py`** for brand constants and shared chrome —
  `CRIMSON` (`#9A0021`) and `BLUE` (`#0076A5`) are the two brand colors, the
  `_INDEX_STRING`/fonts/header are defined once there for every dashboard.
  Don't hardcode a new color or re-declare the header elsewhere.
- **Reuse the shared layout CSS classes** already used across dashboards
  (`paw-dash-row`, `paw-dash-sidebar`, `paw-chart-row`, `paw-chart-grid`) —
  they already have the mobile breakpoint handled in `shell.py`'s
  `@media (max-width: 720px)` block. A new hand-rolled flex/grid layout is a
  sign something should reuse an existing class instead.
- **Follow the existing per-dashboard file split**: each dashboard under
  `app/dashboards/<name>/` separates `layout.py` (structure), `callbacks.py`
  (interactivity), `charts.py` (plotting), and `tables.py` (tabular
  rendering) — see `app/dashboards/hitting/` as the reference. Put new code
  in the file that matches that role rather than inventing a new split.
- **Data access lives in `app/data/`, not in dashboard files.** Dashboards
  should call into `app/data/*.py` for queries/metric calculations, mirroring
  how existing dashboards are wired.
- Look at a sibling dashboard doing something similar before building
  something new from scratch — most patterns (date-range pickers, zone
  grids, PDF report generation) already exist once and are meant to be
  reused, not reimplemented.

## Code style

- Lint with `ruff check .` before opening a PR — CI runs this and blocks on
  real bugs (`ruff.toml` intentionally limits checks to `F`/`E9`/`B`, not
  style nits, so don't go beyond what it enforces).
- No comments explaining *what* code does — names should do that. Only
  comment a non-obvious *why* (a workaround, a hidden constraint), matching
  the existing codebase's style.
- Don't refactor or restructure code outside the scope of the task at hand.
  Existing "pre-existing lint ignore" comments in `ruff.toml` are deliberate
  scope boundaries from past work — don't use a new task as an excuse to
  clean those up unless asked.

## Tests

- New logic (a new metric, a new data transform, a new callback) should get
  a test alongside the existing ones in `tests/`, following the naming/style
  of the test file for that dashboard (e.g. `tests/test_hitting.py`).
- If a test fails and you didn't touch that area, run `git pull` first —
  `main` may have moved.
