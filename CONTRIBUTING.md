# Contributing to PAW

Welcome! This guide is everything you need. If you get stuck, ask Brad —
that is faster than guessing.

> New to all this? See `README.md` first — it's the full from-scratch setup
> guide (installing Git, Python, Cursor, etc.). This file assumes that's done
> and covers the day-to-day workflow for making a change.

## The one rule

**Never push to `main`.** All work goes through a pull request. `main` is what
the team actually uses, so a bug there breaks the site for real coaches and
players.

## First-time setup

```bash
git clone https://github.com/LMU-Baseball/PAW.git
cd PAW
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Mac/Linux
pip install -r requirements.txt
```

Ask Brad for the `.env` file. **Never commit it** — it holds the database
password. It is already in `.gitignore`, so git will ignore it automatically.
(There's a `.env.example` in the repo showing which values it needs.)

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
git add .
git commit -m "fix: velo chart showed the wrong season"
git push -u origin your-name/what-you-are-doing
```

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
3. Once approved, it gets merged (squashed into one clean commit on `main`).
   Your branch is deleted automatically.

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
