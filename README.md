# PAW — LMU Baseball Analytics

PAW is the LMU Baseball program's analytics web app. It's a **Python** web app
(Flask + Dash) that reads the team's Trackman / HitTrax data out of the database
and turns it into interactive dashboards and pitcher reports for coaches and
players.

This README is the **from-scratch setup guide for new developers (interns).**
Follow it top to bottom on your own laptop and by the end you'll be able to open
the project in Cursor, run the app locally, and start coding — the same way the
rest of the team works.

> **You do not need to be an expert.** Most of this is copy-paste. When something
> goes wrong, that's normal — jump to [Troubleshooting](#troubleshooting) or ask
> in the team chat.

---

## Table of contents

1. [How this guide is organized](#how-this-guide-is-organized)
2. [What you'll end up with](#what-youll-end-up-with)
3. [Step 1 — GitHub account + repo access](#step-1--github-account--repo-access)
4. [Step 2 — Install Git](#step-2--install-git)
5. [Step 3 — Install Python 3.12](#step-3--install-python-312)
6. [Step 4 — Install Cursor (your editor)](#step-4--install-cursor-your-editor)
7. [Step 5 — Install your AI coding assistant](#step-5--install-your-ai-coding-assistant)
8. [Step 6 — Get the code](#step-6--get-the-code)
9. [Step 7 — Set up the Python environment](#step-7--set-up-the-python-environment)
10. [Step 8 — Install the headless browser (for reports)](#step-8--install-the-headless-browser-for-reports)
11. [Step 9 — Add your secrets (`.env`)](#step-9--add-your-secrets-env)
12. [Step 10 — Create a login for yourself](#step-10--create-a-login-for-yourself)
13. [Step 11 — Run the app](#step-11--run-the-app)
14. [Step 12 — Open it in Cursor and start coding](#step-12--open-it-in-cursor-and-start-coding)
15. [Running the tests](#running-the-tests)
16. [Everyday workflow (git basics)](#everyday-workflow-git-basics)
17. [Troubleshooting](#troubleshooting)
18. [Project layout & where to learn more](#project-layout--where-to-learn-more)

---

## How this guide is organized

Some steps are different depending on your setup. Wherever that happens you'll
see clearly-labeled options — **just follow the one that matches you** and ignore
the others:

- 🍎 **macOS** vs 🪟 **Windows** — pick your operating system.
- 🤖 **Claude Code** vs 🤖 **Codex** — pick which AI assistant you'll use. (You
  can install both later; start with one.)

If a step has no label, everyone does it the same way.

---

## What you'll end up with

When you finish, you'll have:

- The project code on your laptop.
- A working Python environment with all dependencies installed.
- The app running locally at **http://127.0.0.1:8050**.
- Cursor open on the project with your AI assistant (Claude Code or Codex) ready
  to help you write code.

Rough time: **30–60 minutes** the first time.

---

## Step 1 — GitHub account + repo access

The code lives in a **private GitHub repository**. You need a GitHub account, and
Brad needs to add that account to the repo.

1. If you don't have one, create a free account at <https://github.com>.
2. Send Brad (**bradley.haskell@newrange.com**) your **GitHub username**.
3. Wait for the email invite from GitHub and click **Accept**.

You can't clone the code until you've accepted the invite, so do this first.

---

## Step 2 — Install Git

Git is the tool that downloads the code and tracks your changes.

### 🍎 macOS

Open the **Terminal** app (press `Cmd+Space`, type "Terminal", hit Enter) and run:

```bash
git --version
```

If Git isn't installed, macOS will pop up a prompt to install the "Command Line
Developer Tools" — click **Install** and wait. Re-run `git --version` after.

### 🪟 Windows

1. Download **Git for Windows** from <https://git-scm.com/download/win>.
2. Run the installer. **Accept all the defaults** (just keep clicking Next).
3. This gives you a program called **Git Bash** — a terminal we'll use for the
   command-line steps below.

Open **Git Bash** (Start menu → type "Git Bash") and confirm:

```bash
git --version
```

> **Windows tip:** When this guide shows terminal commands, run them in **Git
> Bash**, not the old Command Prompt. Cursor also has a built-in terminal you can
> use once we get there.

---

## Step 3 — Install Python 3.12

The app runs on **Python 3.12**. (Newer versions like 3.13 may work but 3.12 is
what we test against — please use it to avoid surprises.)

### 🍎 macOS

Easiest is the official installer:

1. Go to <https://www.python.org/downloads/macos/>.
2. Download the latest **Python 3.12.x** macOS installer and run it.
3. Confirm in Terminal:

   ```bash
   python3.12 --version
   ```

### 🪟 Windows

1. Go to <https://www.python.org/downloads/windows/>.
2. Download the latest **Python 3.12.x** "Windows installer (64-bit)".
3. Run it. **IMPORTANT: on the first screen, check the box "Add python.exe to
   PATH"** before clicking Install. This one checkbox prevents most "python not
   found" headaches.
4. Confirm in Git Bash:

   ```bash
   python --version
   ```

   If that doesn't say 3.12, try `py -3.12 --version`.

---

## Step 4 — Install Cursor (your editor)

**Cursor** is the code editor the team uses. It's a fork of VS Code with AI built
in, and it's where you'll spend your time.

1. Download it from <https://cursor.com> and install it like any other app.
2. Open it once so it finishes setup.

> Prefer plain **VS Code**? It works too — everything in this guide is the same.
> But we recommend Cursor because it matches how the rest of the team works.

---

## Step 5 — Install your AI coding assistant

You'll use an AI assistant that runs **in the terminal** to help you write and
understand code. Pick **one** to start. Both require you to sign in with **your
own account** (bring your own subscription).

### Option A — 🤖 Claude Code (Anthropic)

This is what Brad uses.

**Install (both macOS and Windows, run in your terminal / Git Bash):**

```bash
npm install -g @anthropic-ai/claude-code
```

*Don't have `npm`?* Install **Node.js LTS** first from <https://nodejs.org> (get
the "LTS" version, accept defaults), then re-run the command above.

*Prefer a no-Node install?* Native installers also exist:
- 🍎 macOS: `curl -fsSL https://claude.ai/install.sh | bash`
- 🪟 Windows (PowerShell): `irm https://claude.ai/install.ps1 | iex`

**Sign in:** run `claude` in your terminal the first time and follow the prompt
to log in with your Anthropic account (a Claude Pro or Max subscription, or API
billing). You only do this once.

Docs: <https://docs.claude.com/en/docs/claude-code>

### Option B — 🤖 Codex (OpenAI)

**Install (both macOS and Windows):**

```bash
npm install -g @openai/codex
```

(Same as above — if you don't have `npm`, install **Node.js LTS** from
<https://nodejs.org> first.)

**Sign in:** run `codex` in your terminal and log in with your OpenAI account
(ChatGPT Plus/Pro or API billing).

Docs: <https://developers.openai.com/codex/cli>

> Both tools run the same way: you open a terminal **inside the project folder**,
> launch the assistant, and describe what you want in plain English. We'll do
> that in Step 12.

---

## Step 6 — Get the code

Now clone (download) the repository. First pick a folder to keep your projects
in, then clone into it. Run these in your terminal (**Git Bash** on Windows):

```bash
# make a "code" folder in your home directory and go into it
mkdir -p ~/code
cd ~/code

# clone the repo
git clone https://github.com/LMU-Baseball/PAW.git
cd PAW
```

> This is a **private** repo, so the first time you clone, GitHub will ask you to
> log in / authorize in your browser — that's expected. (Make sure you've accepted
> the repo invite from Step 1 first, or the clone will fail with "not found".)

From now on, **all commands assume you are inside the `PAW` folder** (`cd ~/code/PAW`).

---

## Step 7 — Set up the Python environment

We use a **virtual environment** (`.venv`) — a private, per-project copy of
Python's packages so this project can't collide with anything else on your
machine. Create it once, then "activate" it whenever you work on the project.

### Create the virtual environment

```bash
# macOS
python3.12 -m venv .venv

# Windows (if the above says "command not found", use this)
py -3.12 -m venv .venv
```

### Activate it

**You must activate the venv in every new terminal session.** You'll know it
worked when your prompt shows `(.venv)` at the start of the line.

```bash
# 🍎 macOS
source .venv/bin/activate

# 🪟 Windows (Git Bash)
source .venv/Scripts/activate
```

### Install the dependencies

With the venv active:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

This pulls in Flask, Dash, pandas, and everything else (it may take a couple of
minutes).

---

## Step 8 — Install the headless browser (for reports)

The pitcher reports are rendered to PDF by a headless copy of Chromium (via a
tool called Playwright). Install it once:

```bash
playwright install chromium
```

> If you're only working on dashboards and not the PDF reports, the app still
> runs without this — but install it now so you don't hit a wall later.

---

## Step 9 — Add your secrets (`.env`)

The app reads database credentials and other secrets from a file named **`.env`**
in the project root. This file is **never committed to Git** (it holds passwords),
so it isn't in the repo you cloned — you have to create it.

1. There's a template in the repo called **`.env.example`**. Copy it:

   ```bash
   cp .env.example .env
   ```

2. **Get the real values from Brad.** The database credentials are shared
   privately (not over public channels). Brad will send you a filled-in `.env`
   or the exact values to paste in. Ask him: **bradley.haskell@newrange.com**.

3. Open `.env` in Cursor and paste in the real values (database host, user,
   password, etc.), then save.

> ⚠️ **Never** commit `.env`, paste its contents into a chat/issue, or share it
> outside the team. It's your key to the live database. The `.gitignore` already
> blocks it from being committed — keep it that way.

---

## Step 10 — Create a login for yourself

The app is login-gated. Create a local coach account so you can see everything
while developing. With your venv active and `.env` filled in:

```bash
flask --app run create-user \
  --email you@example.com \
  --name "Your Name" \
  --role coach \
  --password "pick-a-password"
```

This stores the account in a local file (`instance/paw_app.db`) on your machine —
it's just for your local dev server. Use `--role coach` so you can access every
part of the app while working.

> Forgot the password later? Reset it with:
> `flask --app run set-password --email you@example.com --password "new-password"`

---

## Step 11 — Run the app

```bash
python run.py
```

You should see:

```
  PAW is running →  http://127.0.0.1:8050
```

Open **http://127.0.0.1:8050** in your browser and log in with the account you
just created. 🎉

> **Use the exact address `127.0.0.1:8050`**, not `localhost:8050`. On Windows
> especially, `localhost` can resolve to IPv6 and fail to connect.

Stop the server anytime with **Ctrl+C** in the terminal.

---

## Step 12 — Open it in Cursor and start coding

This is the setup everyone uses day-to-day:

1. In Cursor: **File → Open Folder** → choose your `PAW` folder.
2. Open Cursor's built-in terminal: **View → Terminal** (or `` Ctrl+` ``).
3. In that terminal, **activate your venv** (Step 7) if it isn't already:
   - 🍎 macOS: `source .venv/bin/activate`
   - 🪟 Windows: `source .venv/Scripts/activate`
4. Launch your AI assistant right there in the terminal:
   - 🤖 Claude Code: type `claude`
   - 🤖 Codex: type `codex`
5. Now describe what you want in plain English (e.g. *"add a new column to the
   hitting dashboard sidebar"*). The assistant can read the code, make changes,
   and run commands with you.

A typical loop: ask the assistant to make a change → run `python run.py` (or the
tests) to see it → refine. Keep the app running in one terminal tab and your AI
assistant in another.

> **Heads up:** the dev server does **not** auto-restart when you edit Python
> files (this is on purpose — see [Troubleshooting](#troubleshooting)). After a
> Python change, stop the server (Ctrl+C) and run `python run.py` again. Edits to
> HTML templates *do* reload automatically.

---

## Running the tests

The project has a large automated test suite. Run it before you commit to make
sure you didn't break anything. With your venv active:

```bash
# run everything
pytest

# run one file (faster while you work)
pytest tests/test_hitting.py

# run tests matching a name
pytest -k hitting
```

Green means passing. If something's red, read the message — it usually points
right at the problem. Your AI assistant is great at helping here: paste the
failure and ask it what's going on.

---

## Everyday workflow (git basics)

Don't work directly on `main`. Make a branch, commit your work, and push it so
others can review.

**`CONTRIBUTING.md` (in the project root) is the canonical guide for this** —
branch naming, exactly which `git add` commands to run (and which to avoid),
running tests, and what happens after you open a PR. Read that for the full
workflow.

Then open a **Pull Request** on GitHub so your work can be reviewed and merged.
If any of this is fuzzy, ask your AI assistant to walk you through it — describing
what you want to do in plain English works well.

---

## Troubleshooting

**`python` / `python3.12` "command not found"**
Make sure Python 3.12 installed correctly. On Windows, re-run the installer and
confirm **"Add python.exe to PATH"** was checked. Try `py -3.12` on Windows or
`python3.12` on macOS.

**`(.venv)` isn't showing in my prompt**
You didn't activate the venv in this terminal. Re-run the activate command for
your OS (Step 7). You must do this in **every** new terminal window.

**The page won't load / "can't connect"**
Use the exact URL **http://127.0.0.1:8050** (not `localhost`). Make sure the
terminal running `python run.py` is still open and shows no errors.

**"Missing required environment variable: MYSQL_..."**
Your `.env` is missing or incomplete. Confirm the file is named exactly `.env`
(no `.txt`), lives in the project root, and has the real values from Brad
(Step 9).

**Dashboards load but show no data / database errors**
The credentials in `.env` are wrong or the database isn't reachable. Double-check
the values with Brad. (If you're off-campus, the database may require specific
network access — ask.)

**I edited a Python file but nothing changed in the browser**
The dev server doesn't auto-reload Python code (it's disabled on purpose so the
PDF report builder doesn't get interrupted mid-render). Stop the server with
**Ctrl+C** and run `python run.py` again. Template (HTML) edits *do* auto-reload.

**`playwright` or Chromium errors when generating a report**
Run `playwright install chromium` again (Step 8) with your venv active.

**Something else / totally stuck**
Paste the exact error into your AI assistant and ask. If you're still stuck,
message the team with: what you ran, the full error text, and your OS.

---

## Project layout & where to learn more

A quick map so you know where things live:

```
PAW/
├── run.py                 # dev entry point — this is what you run locally
├── config.py              # loads secrets from .env
├── requirements.txt       # Python dependencies
├── .env.example           # template for your .env (copy it, fill from Brad)
├── app/
│   ├── __init__.py        # create_app() — wires the whole app together
│   ├── dashboards/        # the Dash dashboards (hitting, pitching, catching, …)
│   ├── data/              # database reads + analytics/metric calculations
│   ├── reports/           # pitcher post-game PDF reports
│   ├── ingest/            # data pipeline (Trackman / HitTrax loaders)
│   ├── auth/              # login / user accounts
│   └── cli.py             # `flask` commands (create-user, rebuild-precalc, …)
├── tests/                 # the automated test suite (pytest)
└── docs/                  # deeper docs (deployment, pipeline runbook, specs)
```

Deeper documentation lives in **`docs/`**:

- **`docs/DEPLOY.md`** — how the app gets deployed to a live server.
- **`docs/pipeline-cron-runbook.md`** — how new game data gets loaded.
- **`docs/superpowers/specs/`** — design docs for major features.

**Best way to learn the codebase:** open it in Cursor and ask your AI assistant
things like *"walk me through how the hitting dashboard loads its data"* or
*"where is expected batting average calculated?"* It can read the whole project
and explain it far faster than reading file-by-file.

Welcome to the team — go build something. ⚾
