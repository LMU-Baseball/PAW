# PAW — Production Deploy Runbook (AWS Lightsail)

Deploys the Flask + Dash app to a single always-on Linux VM (AWS Lightsail) that
connects to the existing **AWS RDS MySQL** warehouse (`lmubaseball`, us-east-2).
nginx terminates HTTPS and serves static files; gunicorn runs the app on
loopback. Result: a private, login-gated URL players can open from any device.

> **Model recap.** One shared **coach** account (edits everything) + one shared
> **player** account (`role=player`, sees all data, read-only). Content is behind
> login; `/static/` assets (logos, fonts) are fetchable by URL. Google won't
> index it.

---

## 0. Prerequisites

- An AWS account with access to Lightsail + the RDS console (us-east-2).
- The `.env` values you already run locally (the `MYSQL_*` RDS creds). Keep them
  handy — they go on the server, never in git.
- (Optional but recommended) a domain/subdomain you can point at the server,
  e.g. `paw.lmulions.com`. HTTPS needs a hostname.

---

## 1. Create the Lightsail instance

1. Lightsail → **Create instance** → Region **us-east-2** (same as RDS).
2. Platform **Linux/Unix** → Blueprint **OS Only → Ubuntu 22.04 LTS**.
3. Plan: **$10/mo** (2 GB RAM) — the safe choice for a shared host: Chromium for
   the PDF reports wants headroom for back-to-back/concurrent builds. It is not a
   hard floor — a single report rendered fine on Render's 512 MB free instance
   (2026-08-20) — but concurrent rendering under load was never tested, so stay
   on 2 GB for the box coaches and players share.
4. Name it `paw-prod`, create.
5. Instance → **Networking** → attach a **Static IP** (free while attached). Note
   it — call it `LIGHTSAIL_IP` below.
6. Networking → **IPv4 Firewall**: keep 22 (SSH); add **443 (HTTPS)** and
   **80 (HTTP)** (80 is needed for the Let's Encrypt challenge). You do NOT need
   to open 8050 — gunicorn stays on loopback.

---

## 2. Let the server reach RDS

RDS is in its own VPC/security group; by default the Lightsail box can't connect.
Grant just this one host (least privilege — we are **not** rotating the DB
password yet, so keep the surface tiny):

1. RDS console → the `lmubaseball` instance → **Connectivity & security** → its
   **VPC security group**.
2. **Inbound rules → Edit → Add rule**: Type **MySQL/Aurora (3306)**, Source =
   `LIGHTSAIL_IP/32` (the static IP only — never `0.0.0.0/0`).
3. Save. (If Lightsail↔RDS refuses to connect even with this rule, it's because
   Lightsail is outside the RDS VPC — set up **Lightsail VPC peering** from the
   Lightsail account page, then use the RDS *private* endpoint. The public-IP
   allow-rule above is the simpler path and fine for launch.)

> ⚠️ **Deferred, on the record:** the RDS password was once exposed in the legacy
> R files and has not been rotated (your call, 2026-08-14). Until it is, the
> `/32` allow-rule above is doing the real access control. Rotate it when you can
> (RDS → Modify → new password → update `.env` → `sudo systemctl restart paw`).

---

## 3. Server setup

SSH in (Lightsail browser SSH, or your key):

```bash
sudo apt update && sudo apt -y upgrade
sudo apt -y install python3.12 python3.12-venv python3-pip nginx git

# --- get the code (use your repo URL or scp the working tree up) ---
sudo mkdir -p /opt/paw && sudo chown $USER:$USER /opt/paw
git clone <YOUR_REPO_URL> /opt/paw        # or: rsync/scp your local tree to /opt/paw
cd /opt/paw

python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn                      # already in requirements, explicit for safety

# --- headless Chromium for the pitcher-report PDFs (Playwright) ---
python -m playwright install --with-deps chromium
```

> **Playwright: pin the package, and know where the browsers land.** Two traps
> took down PDF downloads on the Render interim host (2026-08-20); both apply
> here:
>
> - **Keep `playwright` pinned in `requirements.txt`** (currently
>   `playwright==1.61.0`). Playwright stamps its browser directory with a build
>   number tied to the package version — 1.61.0 installs
>   `chromium_headless_shell-1228`. An unpinned `playwright>=1.44` can resolve to
>   a newer package on some later rebuild that then looks for a build number the
>   cache never downloaded. **Bump the pin and re-run the
>   `playwright install --with-deps chromium` above together** — never one
>   without the other.
> - **Browsers install to `~/.cache/ms-playwright` by default.** On this
>   Lightsail box that is fine: the same `/home/ubuntu` exists when you install
>   and when gunicorn runs. On a host that builds in one container and runs the
>   app in another (managed platforms like Render, or a multi-stage image), that
>   cache does not survive the handoff — set **`PLAYWRIGHT_BROWSERS_PATH=0`**
>   in the environment used for **both** build and runtime. The special value `0`
>   installs the browsers into the `playwright` pip package directory inside
>   site-packages, which is part of the build output that ships to runtime, so
>   the install location and the lookup location always agree.
>
> **Symptom to recognize:** report downloads fail and the log shows
> `BrowserType.launch: Executable doesn't exist at …/chrome-headless-shell`
> followed by the boxed "Looks like Playwright was just installed or updated"
> banner. That is always a missing or mismatched browser install — not memory,
> not RDS. `/reports/*` returns **503 with the underlying cause in the response
> body** for exactly this reason, so read the body before guessing.

---

## 4. Secrets — the `.env` on the server

Create `/opt/paw/.env` (mode 600, never committed):

```bash
umask 077
cat > /opt/paw/.env <<'EOF'
# --- RDS analytics warehouse (same values you run locally) ---
MYSQL_USER=admin
MYSQL_PASSWORD=<the current RDS password>
MYSQL_HOST=lmubaseball.c36mi2uaumxg.us-east-2.rds.amazonaws.com
MYSQL_PORT=3306
MYSQL_DB=lmubaseball

# --- Flask session signing: MUST be a strong random value in production ---
SECRET_KEY=<paste the output of the openssl command below>

# APP_DATABASE_URL is optional; omit to use the local SQLite user-account DB
# at instance/paw_app.db (fine for this scale). Set it to a MySQL URL later if
# you want user accounts on RDS too.
EOF
chmod 600 /opt/paw/.env
```

Generate the `SECRET_KEY` (do NOT ship the `dev-only-change-me` default — it makes
session cookies forgeable):

```bash
openssl rand -hex 32
```

---

## 5. Create the two accounts

```bash
cd /opt/paw && source .venv/bin/activate
export FLASK_APP=wsgi:app
flask create-user --email coaches@lmu.edu --name "LMU Coaches" --role coach   --password '<coach-pw>'
flask create-user --email team@lmu.edu    --name "LMU Team"    --role player  --password '<player-pw>'
```

(The player account needs no `--trackman-id` — a shared team account has none.)
This also creates the SQLite user DB at `instance/paw_app.db` on first run.

---

## 6. Run gunicorn under systemd

Create `/etc/systemd/system/paw.service`:

```ini
[Unit]
Description=PAW (LMU Baseball) gunicorn
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/opt/paw
Environment=PAW_WARM_CACHE=1
ExecStart=/opt/paw/.venv/bin/gunicorn -c gunicorn.conf.py wsgi:app
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now paw
sudo systemctl status paw          # should be active (running)
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8050/   # expect 302 -> /login
journalctl -u paw -f               # live logs (Ctrl-C to stop)
```

---

## 7. nginx reverse proxy

Create `/etc/nginx/sites-available/paw`:

```nginx
server {
    listen 80;
    server_name paw.lmulions.com;      # or LIGHTSAIL_IP if no domain yet

    client_max_body_size 25m;          # PDF/zip downloads

    location / {
        proxy_pass http://127.0.0.1:8050;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 180s;       # match gunicorn timeout (report builds)
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/paw /etc/nginx/sites-enabled/paw
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

Visit `http://LIGHTSAIL_IP/` — you should get the login page.

---

## 8. HTTPS (needs a domain)

Point an A record for `paw.lmulions.com` → `LIGHTSAIL_IP`, then:

```bash
sudo apt -y install certbot python3-certbot-nginx
sudo certbot --nginx -d paw.lmulions.com      # auto-edits nginx, installs the cert, sets up renewal
```

certbot adds the `listen 443 ssl` block and an 80→443 redirect. Renewal is
automatic (systemd timer). Done — `https://paw.lmulions.com` is live.

> No domain yet? You can launch on `http://LIGHTSAIL_IP` for internal testing,
> but **do HTTPS before sharing with players** — login passwords over plain HTTP
> are exposed. A subdomain + certbot is ~15 minutes.

---

## 9. Verify

- `https://paw.lmulions.com` → login page, padlock shows valid cert.
- Log in as the coach account → velo board + Cauldron editable; all dashboards
  load; open one on your phone (viewport fix means no pinch-zoom).
- Log in as the player account → sees every player's data, **no** Edit/Save on
  the boards, coach notes render read-only.
- Download a pitcher report PDF (exercises the headless-Chromium path).

---

## 10. Day-2 operations

- **Deploy an update:** `cd /opt/paw && git pull && source .venv/bin/activate &&
  pip install -r requirements.txt && sudo systemctl restart paw`
- **Logs:** `journalctl -u paw -f` (app), `/var/log/nginx/` (proxy).
- **Back up the user DB:** `instance/paw_app.db` holds the accounts — copy it
  somewhere safe periodically (it's small).
- **(Optional) overnight report warm-cache:** once the fall-2026 Trackman ingest
  cadence is set, add a cron/systemd-timer that runs the report pre-build after
  ingest so next-morning downloads are instant (see Memory §SP5).

---

## Caveats / known trade-offs

- **User accounts are on SQLite** (`instance/paw_app.db`). Fine for ~30-50 users
  and infrequent logins; if you ever see write-lock contention, move accounts to
  RDS by setting `APP_DATABASE_URL` to a MySQL URL and re-running `create-user`.
- **Per-worker cache warm:** each of the 3 gunicorn workers warms independently
  at boot (a few seconds of DB reads ×3). Expected; keeps every worker fast.
- **RDS password not rotated** (deferred). The `/32` security-group rule is the
  active mitigation until you rotate.
- **Chromium footprint:** 2 GB is a headroom recommendation, not a hard floor —
  one report rendered on a 512 MB Render instance. Concurrent/sustained report
  builds were never load-tested, so keep the 2 GB plan on a shared host.
- **Playwright version ↔ browser build are coupled:** the `requirements.txt` pin
  and the installed browser must move together, and on hosts that don't preserve
  `~/.cache/ms-playwright` between build and runtime you need
  `PLAYWRIGHT_BROWSERS_PATH=0`. See §3.
