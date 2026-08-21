# PAW — In-season AWS deploy guide

**Status:** Reference checklist (not implemented yet)  
**Audience:** You + Claude Code when ready to ship a public HTTPS link for coaches/players  
**Recommended shape:** Always-on **EC2** in the **same AWS region/VPC as the analytics RDS**, with **gunicorn** + HTTPS reverse proxy  
**App entrypoint:** `run:app` (Flask factory via `run.py`)  
**Prod server already listed in deps:** `gunicorn>=22.0` in `requirements.txt`

This doc is the handoff. When deploying, follow the phases in order; do not skip security-group or secrets steps.

---

## 1. Goal

Coaches and players open one HTTPS URL (e.g. `https://paw.example.com`), log in, and use:

| Surface | Path |
|---------|------|
| Home / hubs | `/`, `/hitting`, `/pitching`, `/catching` |
| Hitting game stats | `/dash/hitting/` |
| Pitching game stats | `/dash/pitching/` |
| Catching game stats | `/dash/catching/` |
| HitTrax practice | `/dash/hitting-practice/` |
| Pitcher postgame PDF | `/reports/pitching` |

Your laptop is **not** the server. Local `python run.py` stays for development only.

---

## 2. Architecture (target)

```
Internet (HTTPS)
    → reverse proxy (Caddy or nginx + Let's Encrypt / ALB+ACM)
        → gunicorn → Flask + Dash (PAW)
            → AWS RDS MySQL  (analytics warehouse: Trackman / HitTrax tables)
            → App DB          (user accounts: prefer MySQL on same RDS, not ephemeral SQLite)
```

**Why EC2 next to RDS (not Render as the season home):**
- Same credentials / same warehouse you already use locally
- Lower DB latency than a different cloud region
- Straightforward security group: RDS accepts MySQL **only** from the app
- Playwright (pitcher PDF) needs Chromium on the host; a small VM is predictable

Render/Railway/Fly are fine for a **quick staging link**. For in-season daily use, prefer this AWS path.

---

## 3. Prerequisites (before Claude Code starts infra)

- [ ] Feature freeze for the build you want coaches to use
- [ ] Local login + dashboards + at least one pitcher PDF work against live RDS
- [ ] You know the RDS **region**, **VPC**, and current security groups
- [ ] Strong production `SECRET_KEY` generated (do not reuse the dev default)
- [ ] Decision on public hostname (custom domain vs EC2/ALB default URL first)
- [ ] AWS account access that can create EC2, security groups, and (optional) ACM/ALB
- [ ] Confirm any passwords that ever lived in local `src/` R files were **rotated** if those files were shared outside git

**Do not commit:** real `.env`, RDS passwords, SSH keys, or PEM files. `.env` is gitignored; only `.env.example` is tracked.

---

## 4. Environment variables

Copy from `.env.example` and set on the **server** (or AWS Secrets Manager / SSM), never in git.

### Required for the web app

| Variable | Purpose |
|----------|---------|
| `MYSQL_HOST` | Analytics RDS hostname |
| `MYSQL_PORT` | Usually `3306` |
| `MYSQL_USER` | DB user (prefer least privilege) |
| `MYSQL_PASSWORD` | DB password |
| `MYSQL_DB` | Usually `lmubaseball` |
| `SECRET_KEY` | Flask session signing — **must** be a long random production value |

### Strongly recommended for production

| Variable | Purpose |
|----------|---------|
| `APP_DATABASE_URL` | Persistent SQLAlchemy URL for **user accounts**. If unset, the app defaults to SQLite under `instance/paw_app.db`, which is easy to lose on instance replace. Example: `mysql+pymysql://appuser:…@same-rds-host:3306/paw_app` |

### Optional on the web host

| Variable | Purpose |
|----------|---------|
| `FTPS_*` | HitTrax FTPS ingest — only if the **pipeline** runs on this same box. The Dash practice UI only needs MySQL `practice_*` tables. |
| `PAW_REPORT_CACHE_DIR` | Override pitcher report cache dir (default under `instance/report_cache`) |

### Same RDS credentials?

**Yes.** The deployed app uses the same `MYSQL_*` warehouse as local dev. You are not copying the database — you are pointing the hosted app at it.

Prefer a DB user that can read analytics tables (and write only if something on this host truly needs write access). Keep FTPS secrets off the web box unless ingest runs there.

---

## 5. Phase A — Repo packaging (Claude Code can implement)

Create these if they do not exist yet:

1. **`Dockerfile`**
   - Base: Python 3.12 (or whatever CI/local uses)
   - `pip install -r requirements.txt`
   - Install Playwright Chromium **and** OS deps (`playwright install --with-deps chromium`)
   - **Pin `playwright` in `requirements.txt`, and bump the pin and that install
     step together.** Playwright stamps its browser dir with a build number tied
     to the package version (`playwright==1.61.0` →
     `chromium_headless_shell-1228`), so a drifting version looks for a build the
     image never downloaded
   - **Set `PLAYWRIGHT_BROWSERS_PATH=0` if the browsers are installed on a
     different filesystem than the one the app runs on** (multi-stage image, or a
     managed platform like Render). `0` puts the browsers inside the `playwright`
     package in site-packages so they ship with the build; a single-stage
     Dockerfile that installs as the same user it runs as does not need it.
     Symptom when this is wrong: `Executable doesn't exist at
     …/chrome-headless-shell` + "Looks like Playwright was just installed or
     updated" — this broke PDF downloads on the Render interim host, 2026-08-20
     (see `docs/DEPLOY.md` §3)
   - `WORKDIR` = app root; copy app code
   - Default `CMD`: gunicorn (see below)
   - Do **not** bake `.env` or secrets into the image

2. **`.dockerignore`**
   - Exclude `.git`, `.env`, `.venv`, `instance/`, `__pycache__/`, `src/`, tests caches, etc.

3. **Production start command** (document in Dockerfile `CMD` and here):

```bash
gunicorn -b 0.0.0.0:8000 -w 2 --timeout 120 "run:app"
```

Notes:
- `-w 2` is a starting point; raise only if CPU allows
- `--timeout 120` (or higher) because pitcher PDF builds via Playwright can be slow
- **Never** run `debug=True` / `python run.py` in production

4. **Optional:** `docker-compose.yml` for local prod-parity smoke (app only; still use real or tunnelled RDS carefully)

5. **Optional:** tiny `scripts/deploy_ec2.sh` that SSHes, pulls, rebuilds, restarts — keep secrets out of the script

---

## 6. Phase B — AWS network + EC2

### 6.1 Security groups

**EC2 (app) SG — inbound:**
- `443/tcp` from `0.0.0.0/0` (HTTPS for coaches/players)
- `80/tcp` from `0.0.0.0/0` (HTTP → HTTPS redirect only)
- `22/tcp` **only from your IP** (SSH); remove wide-open SSH

**EC2 SG — outbound:** default allow (needs RDS + Let’s Encrypt / package updates)

**RDS SG — inbound:**
- `3306/tcp` **source = EC2 app security group only**
- Remove any `0.0.0.0/0` MySQL rules if present

Put EC2 in the **same VPC** (and region) as RDS so private connectivity works without exposing MySQL publicly.

### 6.2 Instance sizing

| Workload | Suggested starting size |
|----------|-------------------------|
| Dashboards + light PDF use | `t3.small` (2 vCPU / 2 GB) may work |
| Regular Playwright PDF generation | Prefer **`t3.medium` (2 vCPU / 4 GB)** |

Playwright is less of a RAM floor than it looks: a single pitcher PDF rendered
fine on a 512 MB Render instance (2026-08-20). Size for concurrent report builds
plus dashboard traffic on an always-on box, not for one PDF — the table above
still stands.

Storage: 20–30 GB gp3 is usually enough; watch report-cache growth.

### 6.3 AMI / runtime

- Ubuntu LTS or Amazon Linux 2023
- Install **Docker** (recommended path) *or* Python 3.12 + nginx + systemd
- Attach an IAM role only if you use SSM/Secrets Manager/ECR — no long-lived keys in the repo

---

## 7. Phase C — Run the app on the instance

### Docker path (preferred)

```bash
# On EC2, after cloning the repo or pulling from ECR:
docker build -t paw:latest .
docker run -d --name paw \
  --restart unless-stopped \
  -p 8000:8000 \
  --env-file /etc/paw/paw.env \
  paw:latest
```

`/etc/paw/paw.env` should be root-readable only (`chmod 600`), filled from §4.

### First-time app DB + users

```bash
# Inside the container or venv with APP_DATABASE_URL set:
flask --app run create-user --email coach@lmu.edu --name "Coach" --role coach --password '…'
flask --app run create-user --email player@lmu.edu --name "Player" --role player --password '…' --trackman-id <ID>
```

Use real team emails/passwords; do not reuse documented demo passwords from old plan docs (`paw2026`) on a public URL.

### Roster media / instance files

`instance/` is gitignored. On a fresh host you may need to:
- Run `scripts/scrape_roster_media.py` (if used), or
- Copy a known-good `instance/roster_media.json` onto the server

Without it, headshots/jersey media may fall back to placeholders.

---

## 8. Phase D — HTTPS + DNS

Pick one:

**A. Simple VM proxy (good default)**  
- Install Caddy or nginx on EC2  
- Proxy `https://paw…` → `http://127.0.0.1:8000`  
- Let’s Encrypt cert via Caddy/certbot  

**B. AWS ALB + ACM**  
- ALB terminates TLS; target group → EC2:8000  
- ACM certificate for your domain  

DNS: create `A` or `CNAME` for `paw.yourdomain.com` → EC2 elastic IP or ALB.

Open the **HTTPS** URL on a phone off university Wi‑Fi before calling it done.

---

## 9. Smoke-test checklist (definition of done)

From a device that is not your laptop:

- [ ] `https://…/login` loads (valid cert)
- [ ] Coach login works; hubs show Hitting / Pitching / Catching
- [ ] `/dash/hitting/`, `/dash/pitching/`, `/dash/catching/`, `/dash/hitting-practice/` load data
- [ ] Player login is scoped correctly (no other players’ selectors if that’s the rule)
- [ ] One pitcher PDF downloads from `/reports/pitching`
- [ ] Reboot the EC2 instance; app comes back; **user accounts still exist** (proves `APP_DATABASE_URL` persistence)
- [ ] Confirm RDS SG still has **no** public `3306` to the world

---

## 10. Updating the app in season (should stay easy)

After the first deploy, a normal change looks like:

```bash
ssh ec2-user@paw-host
cd /opt/paw   # or wherever the repo lives
git pull origin main
docker build -t paw:latest .
docker stop paw && docker rm paw
docker run -d --name paw --restart unless-stopped -p 8000:8000 --env-file /etc/paw/paw.env paw:latest
```

Expect ~seconds to a couple minutes of downtime with this simple swap. Fancy zero-downtime rolling deploys are optional later.

**Hard part = first setup. Weekly feature pushes should not require redoing networking.**

---

## 11. Operations notes

- Keep the instance **always on** during the season (no free-tier “sleep” hosts for game day).
- Back up the **app** database (user accounts) on a schedule.
- Rotate logs; prune `instance/report_cache` if disk grows.
- Deploy only from `main` (or a tagged release) once coaches are live.
- If you use a CI user to SSH/deploy, restrict by key + IP; prefer SSM Session Manager when possible.

---

## 12. What not to do

- Do not expose RDS MySQL to `0.0.0.0/0`
- Do not commit `.env` or put production passwords in GitHub Issues/PRs
- Do not run Flask debug mode / `use_reloader` in production
- Do not rely on default `SECRET_KEY=dev-only-change-me`
- Do not use ephemeral SQLite on a replaceable container without a volume **if** that SQLite is your only user store — set `APP_DATABASE_URL` instead
- Do not assume `src/` R apps are required on the server — they are legacy/local and gitignored

---

## 13. Claude Code — suggested work order when ready

Use this as the prompt checklist:

1. Add `Dockerfile` + `.dockerignore` with gunicorn CMD and Playwright Chromium deps.
2. Document exact build/run commands in this file’s §5–§7 if anything drifts.
3. (Optional) Add `APP_DATABASE_URL=` commented example to `.env.example`.
4. Help write the EC2 + security-group + Caddy/nginx steps as shell commands tailored to the chosen AMI.
5. Produce a one-page “go live” runbook: DNS, first users, smoke tests from §9.
6. Produce a one-page “update in season” script (§10).
7. Do **not** put real secrets in the repo; read them from a local env file the human provides.

Out of scope for the first deploy PR unless asked: full Terraform, ECS/Fargate, CI/CD to ECR, custom domain purchase.

---

## 14. Related repo facts

| Item | Location / note |
|------|-----------------|
| Config / env loading | `config.py` |
| Example env template | `.env.example` |
| Dev server | `python run.py` → `127.0.0.1:8050` |
| Prod WSGI target | `gunicorn … "run:app"` |
| User create CLI | `app/cli.py` → `flask --app run create-user` |
| Dash mounts | `app/dashboards/__init__.py` |
| Pitcher PDF (Playwright) | `app/reports/` — needs Chromium on the host |
| Legacy R source (not deployed) | gitignored `src/` |

---

## 15. Optional later upgrades

- GitHub Actions → build/push image to ECR → EC2 pulls on tag
- Move user DB and secrets fully into RDS + Secrets Manager
- ALB health checks on `/login` or a tiny `/health` route (add route if needed)
- Staging EC2 that shares read-only RDS access before promoting to the coach URL
