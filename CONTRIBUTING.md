# Contributing to PAW

Welcome! This guide is everything you need. If you get stuck, ask Brad —
that is faster than guessing.

## Before you start

**Do `README.md`'s Steps 1–11 first** — GitHub access, installing Git and
Python, cloning the repo, creating your `.venv`, and getting your `.env` file
from Brad. Come back here once `python run.py` works and you can log in
locally. This file does not repeat that setup — it covers the day-to-day
workflow for making a change, and repeating those commands here is exactly
how they'd drift out of sync with README (it already happened once).

One reminder because it matters every time you open a new terminal: activate
your `.venv` before running anything —
`source .venv/Scripts/activate` (Windows Git Bash) or
`source .venv/bin/activate` (Mac/Linux). You'll know it worked when your
prompt shows `(.venv)`.

## The one rule

**Never push to `main`.** All work goes through a pull request. `main` is what
the team actually uses, so a bug there breaks the site for real coaches and
players.

## Making a change

```bash
git checkout main
git pull                                  # start from the latest code
git checkout -b your-name/what-you-are-doing
```

Branch names look like `maria/fix-velo-chart` or `jordan/add-catcher-tab`.

Make your edits, then:

```bash
python -m pytest -q                       # make sure nothing broke
git status                                 # look at what changed
git add path/to/the/file.py                # stage only YOUR files, one by one
git commit -m "fix: velo chart showed the wrong season"
git push -u origin your-name/what-you-are-doing
```

> **Don't use `git add .` or `git add -A`.** This repo has scratch folders
> and local notes that are never meant to be committed. Those "stage
> everything" commands sweep them in anyway, and once something is committed
> it's in the project's history for good. `git status` shows you exactly
> what changed — stage only the files you meant to touch.

> **The full test suite takes about 16 minutes** and needs the real `.env` to
> reach the database — it has not hung if it looks quiet for a while. If you
> only touched one area, you can iterate faster with a single file first (for
> example `python -m pytest tests/test_hitting.py -q`), then run the full
> `python -m pytest -q` before you push.

GitHub prints a link. Open it, fill in the three questions, and click
**Create pull request**.

## What happens next

1. **Automated checks (CI) run** — these are fast (a couple of minutes) and
   only check for lint errors, that every file still imports, and a small
   security-focused test file. **CI does not run the full test suite** —
   that's why you run `python -m pytest -q` yourself before pushing. If CI
   goes red, click "Details" to see why, push a fix to the same branch, and
   it re-runs automatically.
2. Brad reviews it. He may leave comments asking for changes — that is normal
   and happens to everyone.
3. Once approved, it gets merged into `main`. You can delete your branch
   after that — GitHub shows a **Delete branch** button on the merged PR
   page.

## Running the app

```bash
python run.py
```

Open **http://127.0.0.1:8050** (use `127.0.0.1`, not `localhost`).

> If that command errors with `UnicodeEncodeError` and mentions an arrow
> character, your terminal isn't reading output as UTF-8. Prefix the command:
> `PYTHONIOENCODING=utf-8 python run.py`.

## Things that will get a PR sent back

- Committing `.env`, a password, or a database credential
- Pushing directly to `main`
- A PR with no description
- Tests failing

## Getting unstuck

- Tests failing and you did not touch that file? Run `git pull` — you may be
  behind `main`.
- Something is broken and you want to start over on your branch:
  `git checkout main && git pull && git checkout -b your-name/try-again`
- Still stuck? Ask. Genuinely.
