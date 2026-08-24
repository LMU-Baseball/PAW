# PAW — Deployment: head-coach meeting brief

**Purpose:** walk out of one meeting with everything needed to deploy PAW to a
permanent, team-owned home. Written 2026-08-23.

**Current state:** the app is **already live** at `https://paw-zj2c.onrender.com`
(Render free tier, deployed 2026-08-17) against the real AWS RDS warehouse. It is
functional today: login-gated, all six dashboards, pitcher/bullpen PDF reports,
durable coach notes + dev plans (`APP_DB_NAME=paw_app` schema on RDS), and the
data pipeline running nightly on GitHub Actions.

**So this meeting is not about getting the app working.** It is about moving it off
a personal free-tier account onto something the program owns, pays for, and keeps
after Brad hands it off.

---

> ⚠️ **SUPERSEDED 2026-08-23 — read §3b–§3f first.** The coach does **not** own an
> AWS account (their credential is an AWS *Builder ID*), so the "add me as an IAM
> user" ask below is impossible as written. The real ask is now §3e: create a
> program-owned AWS account and migrate the data into it. §1–§2 and §4–§6 still stand.

## 0. The one-sentence ask (superseded — see §3e)

> "I need to be added as a user on the LMU AWS account that already runs our
> baseball database, so I can put the app on a real server next to it — about
> $10/month on the bill we are already paying."

If the coach can grant or route only **one** thing, that is it. Everything else in
this doc has a workable default.

---

## 1. What database access does and does not cover

Brad already has full control *inside* the database (the RDS master user). That is
a different system from AWS account permissions, and one cannot be turned into the
other:

- **MySQL grants** — who can read/write tables. Already maxed out. No SQL
  statement can create a server or an AWS login.
- **AWS IAM** — who can launch a server, open a firewall port, attach a domain,
  see the bill. Granted only in the AWS console by an account admin.

There is no way to self-grant path #2 from path #1. Hence the meeting.

---

## 2. Two paths — bring both, so the meeting cannot end in a stall

### Path A — AWS (preferred: institutional ownership)

A small always-on Linux VM in the **same AWS account and region as the RDS
warehouse** (`us-east-2`), running the app behind HTTPS.

- **Cost:** AWS Lightsail 2 GB instance, **$10/mo**, on the existing AWS bill.
  (EC2 `t3.small`/`t3.medium` is the alternative, roughly $15–35/mo.)
- **Pros:** program owns it; one bill the athletics/ITS side already understands;
  lowest DB latency; lets us finally lock the RDS firewall down to one server IP.
- **Needs:** an IAM user for Brad. See §3.
- **Runbook already written:** `docs/DEPLOY.md` (Lightsail, step by step) and
  `docs/deploy-aws.md` (EC2/Docker variant).

### Path B — Render, paid, on a team-owned account (fallback)

Upgrade the existing working deployment to a **Render Starter instance, $7/mo**:
always-on (no 30–60s cold start), custom domain, HTTPS automatic.

- **Cost:** $7/mo.
- **Pros:** could be done the same day, zero AWS access required, already proven
  working with our exact stack including the Playwright PDF reports.
- **Cons:** a second vendor and a second bill; app sits in a different cloud from
  the database; requires transferring the Render account/billing to a program
  email so it survives a handoff.

**Recommendation:** ask for Path A. If the AWS access will take weeks to route
through university IT, do Path B *now* as the in-season home and migrate to AWS
when access lands. The app is portable — nothing about this decision is one-way.

---

## 3. The AWS access ask, in a form IT can act on

The coach probably is not the AWS admin. Whoever set up the
`lmubaseball.…us-east-2.rds.amazonaws.com` instance is. **Ask the coach who that
is and get a warm intro or a ticket filed** — that name is the single most
valuable thing in this meeting.

Hand over exactly this:

- **AWS account:** the one containing RDS MySQL `lmubaseball` in **us-east-2**.
  (Get the 12-digit account ID.)
- **Request:** an IAM user for `bradley.haskell@…`, console access + MFA.
- **Least-privilege permission set (Lightsail path — the smaller ask):**
  - `AmazonLightsailFullAccess`
  - permission to edit the **RDS security group** inbound rules (so the DB can be
    locked to the new server's IP) — or have IT make that one rule change for us
  - *(optional, only if we use a custom domain in AWS)* Route 53 + ACM
- **EC2 path instead?** Then: EC2 instance + security-group + Elastic IP
  management, scoped to `us-east-2`. Bigger ask, more review — prefer Lightsail.
- **Continuity:** ask that a **second** person (coach, staff, or IT) also hold
  admin, so access does not die with one student account.

---

## 3b. FINDING (2026-08-23): we do not actually know who owns the AWS account

Investigated during meeting prep. **Do not walk in assuming the coach's account is
the right one** — the evidence points elsewhere.

**What we verified by querying the warehouse directly (read-only):**

- The `lmubaseball` schema's **oldest table was created 2024-08-28** (`ZONES`, then
  `STANDINGS`, `PAW_LOGS`, `NOTES` over the next two days — the legacy R app's
  tables). The RDS instance is ~2 years old and predates this project.
- **Exactly one human DB credential exists on the instance: `admin`.** No
  per-person users. Every person and every script that has ever touched this
  warehouse shares that one password.
- Our connection registered as `admin@<Brad's home IP>` over the public internet →
  **port 3306 is broadly open**, not restricted to known hosts.
- Size: **3.7 GB total, but 3.4 GB is the `NCAA` table** (2.98M rows, national
  data). LMU's own irreplaceable data (`GAMES`, `VIDEO`, `BULLPEN`, `PRACTICE_*`,
  `POSITIONING`, `NOTES`) is only **~370 MB**.

**What the failed sign-in attempts do and do not prove:**

- The **"Sign in with your AWS Builder ID"** page is *not* an AWS account login. A
  Builder ID is a free personal developer profile (Amazon Q, Skill Builder,
  re:Post, CodeCatalyst) with no resources, no billing, and no console access to
  RDS or EC2. Reaching that page proves nothing about account ownership.
- **IAM users never sign in with an email address.** IAM sign-in needs the 12-digit
  account ID or alias + an IAM *user name* + password. Entering an email there
  always fails, account or no account. That error was a red herring.
- The **root-user** error does mean something narrower: no AWS account has that
  *exact* email as its root address. The account may still exist under a different
  address.

**Leading hypothesis:** the account belongs to whoever built the original R
dashboards around Aug 2024 — possibly a former student's personal account.
Alternatives: the coach's account under a different root email, or an
ITS-managed account inside an LMU AWS organization (in which case this is an IT
ticket and SSO, not a coach favor).

**How to settle it — cheapest first:**

1. **Ask the coach who built the original R dashboards in fall 2024.** Probably
   decisive on its own.
2. **Have the coach sign in themselves** at `signin.aws.amazon.com` → Root user →
   their email, while you watch. If it works, read the account ID from the
   top-right menu, then open RDS — and **switch the region to US East (Ohio)
   us-east-2 first.** The console defaults elsewhere; checking us-east-1 shows an
   empty list and invites the wrong conclusion.
3. **Have them search their inbox** for "Amazon Web Services", "AWS Invoice", or
   "Welcome to Amazon Web Services". Invoices carry the 12-digit account ID and
   confirm the root address.

Do **not** sign in as the coach using their credentials, even with permission.
Have them drive.

### The risk to raise regardless of the answer

Two years of LMU Trackman data live in an AWS account nobody at the program can
currently prove they control, behind a single shared password that was once
committed in plaintext to the R scripts and has never been rotated. If that
account belongs to a graduated student, the warehouse is one lapsed credit card
away from deletion, with no one able to prevent or reverse it.

**Mitigation that needs nobody's permission: take a full local backup now.** We
have the DB credentials and the irreplaceable portion is only ~370 MB.

**Add to the meeting agenda:** *"Who set this database up, and does the program
control the account it lives in?"* — that question outranks everything else in
this doc, because if the answer is "a student who graduated," the priority shifts
from deploying to **migrating the warehouse into a program-owned account.**

### 3c. The unidentified account also holds ~600 GB of game video (found 2026-08-23)

The database is not the only thing at stake. `lmubaseball.video_clips` points every
clip at **S3 bucket `lmubsbvideo` in us-east-2** — almost certainly the same
account as the RDS instance.

- **38,055 clips**, games 2026-03-08 → 2026-05-15 (the 2026 season), uploaded
  2026-03-12 → 2026-05-16.
- Sampled 8 clips at random: **avg ~16 MB** → **~600 GB estimated bucket size**
  (order-of-magnitude; the sample ranged 6–21 MB).
- This is what the pitching dashboard's **Outing Video** tab plays. Losing the
  bucket breaks that feature outright.
- **The bucket is publicly readable** — every HEAD request returned 200 with no
  credentials. Minor exposure (it is game video), but open egress is a cost-abuse
  vector. Do **not** lock it down before we have custody: the app reads those
  public URLs directly, so restricting it now breaks video.

**The bill is a clue — follow the money.** RDS + ~600 GB of S3 + video egress puts
that account at roughly **$40-70/month**. Nobody overlooks a $50/mo personal
charge for two years. So either LMU is already paying it (a department card on a
personal account), or the former director knows they are paying it. **Ask the
coach whether the athletics budget shows an "AWS" / "Amazon Web Services" line
item and who approves it** — that can identify the account with no login attempts
at all.

**The leverage this gives us:** we can rebuild everything in a program-owned
account *without the former director's cooperation* — we hold full DB credentials,
and the video bucket is public, so ~600 GB of clips is copyable with nothing but
the public URLs. What we would want from them is goodwill, not access.

### 3d. RESOLVED (2026-08-23): the coach's credentials are for an AWS Builder ID, not an account

Every piece of evidence fits one story:

| Clue | Reading |
|---|---|
| RDS master password contains **2024** | Minted at the 2024-08-28 instance creation — the original director's |
| The sign-in credential Brad holds contains **2025** | Created a year later, by someone else |
| Builder ID page **accepts** the coach's `@lmu.edu` address | A Builder ID exists for that address |
| Root sign-in: **"no AWS account exists"** | No AWS account has that email as root |

**Conclusion:** sometime in 2025 someone went through an AWS sign-up under the
coach's email, landed in a **Builder ID** path (free, and easy to hit by accident
via Amazon Q / Skill Builder / re:Post links), and came away believing an AWS
account had been created. A Builder ID looks like an AWS login — AWS branding, an
email, a password — but owns no resources, has no billing, and grants no console
access.

**So there are two separate things, and neither is usable as-is:**

1. A **Builder ID** under the coach's email (2025) — a free developer profile.
   Useless for deployment.
2. The **real AWS account** holding the RDS warehouse + the `lmubsbvideo` bucket
   (2024) — owner unidentified, most likely a former Director of Data Analytics.

**Confirm in 60 seconds:** have the coach sign in at the Builder ID page with the
2025 password. Success lands in a bare profile with no account ID, no billing, no
RDS — proof positive. Have the coach drive; it is their identity.

**This is the single most important correction to the plan: the coach cannot grant
IAM access, because the coach does not own an AWS account.**

### 3e. Revised primary plan — create a program-owned account and migrate into it

Because the coach has nothing to grant, "add me as an IAM user" is off the table.
The plan becomes:

**Primary: stand up a genuine program-owned AWS account and migrate the data in.**

- Coach's role shrinks to two things: **create a real AWS account** (program email,
  department payment method) and **authorize Brad to move the program's data into
  it**.
- Brad can then execute nearly all of it unaided: full DB credentials are in hand,
  and the ~600 GB video bucket is public, so both the warehouse and the clips are
  copyable without anyone's cooperation.
- Migration shape: dump/restore `lmubaseball` (~370 MB excl. `NCAA`, or 3.7 GB
  with it) into a new RDS instance; copy `lmubsbvideo` into a program-owned bucket
  and update `video_clips.s3_url`; re-point `MYSQL_HOST`. The app needs no code
  changes beyond environment variables.

**Secondary (nice-to-have, no longer on the critical path): find the former
director and attempt a clean account transfer.** Changing the root email and
payment method on the *existing* account is less work than a migration and
preserves the current RDS hostname — but it depends on an alum's goodwill, so it
must not be a blocker. See §3f for how to approach it.

### 3f. If and when you contact the former director

**Do not reach out first.** Sequence:

1. **Back up what is recoverable, before anyone is told anything.** Not out of
   suspicion — but once someone learns an old AWS account holds the team's data,
   realistic outcomes include tidying it, closing it, or halting payment, and AWS
   deletes resources after sustained payment failure. Get a copy while the
   question is still private.
2. **Establish facts through the coach:** who the director was, when they left,
   which email they used, and whether the athletics budget carries that charge.
3. **Then decide whether outreach is needed at all.**

**If it is: the request comes from the coach, or with the coach cc'd.** This is a
program-to-alum matter about institutional data custody, not a student emailing a
stranger for a password. And the ask is *not* "give me access." It is:

- **(a) Account transfer — best.** Change the root email + payment method on the
  existing account over to the program. Nothing moves, zero downtime, the RDS
  hostname never changes, the app keeps running untouched. Viable only if the
  account holds nothing personal of theirs.
- **(b) Migrate to a program-owned account.** Cross-account RDS snapshot share (or
  a plain dump) + an S3 bucket copy. Minimal cooperation needed — and none for the
  video, since it is public.
- **(c) Just an IAM user.** Solves this week's deploy, leaves the custody problem
  fully intact. Stopgap only.

**Reframe the coach ask accordingly.** It is no longer "$10/mo for a web server."
It is: *"the program needs to take custody of ~600 GB of game video and two years
of Trackman data that currently live in an account none of us control."*

---

## 4. Decisions only the coach/program can make

Walk in with these as questions; walk out with answers.

1. **Ownership and budget.** Who pays the ~$10/mo, and on which existing account?
   Who is the app's institutional owner when Brad hands it off?
2. **The URL.** Does the coach want a school-branded address like
   `paw.lmulions.com`? That domain is athletics-web/Sidearm controlled, so it
   needs a DNS record from that team — get the contact. Otherwise we buy a plain
   domain (~$15/yr) and control it ourselves. *Default if undecided: buy our own,
   ship, rename later.*
3. **Who gets in.** Built and tested model: **one shared coach login** (can edit
   everything) + **one shared player login** (sees all data, read-only). Confirm
   that is still right, who is allowed to know the coach password, and whether
   individual per-person logins are wanted later (that is a follow-on build).
4. **RDS password rotation — needs a decision, deferred since 2026-08-14.** The
   database master password was hardcoded in the legacy R scripts, so it should be
   considered exposed. Rotating it is the right move, but it will break *every*
   other consumer of those credentials. **Ask: who and what else connects to this
   database?** (Old R apps, other interns, Sean, any vendor.) We rotate once we
   have that list.
5. **Data policy / ITS review.** Is there any FERPA or athletics-IT policy concern
   with student-athlete performance data on a login-gated site that is not
   university-managed? Get this *named* now — it is the likeliest thing to surface
   late and stop a launch. Ask whether ITS needs to sign off, and who.
6. **In-season support.** Who does a coach call when it breaks during a game
   weekend, and what downtime is tolerable?

### 4b. Content sign-offs to grab while in the room

Unrelated to hosting, but they have been waiting on the coach and are cheap to
settle face-to-face:

- **Cauldron scoring:** the 4 non-standard metrics (`early_ahead`, `pre2k_zone`,
  `twok_kill`, `count_work`) currently use **provisional formulas Claude wrote**,
  with placeholder point values. Get the coach's real definitions and ± point
  values, or explicit sign-off on the provisional ones.
- **Barrel%:** the dashboard uses 95+ EV; the PDF report uses an LD/FB barrel
  definition. Pick one.
- **Top Gun "LIONS" header art:** it is a Paramount-style trademark lockup. Low
  risk for an internal login-gated tool, but it is the program's call, not ours.

---

## 5. Deployment plan (AWS path) — what happens after access lands

Full detail lives in `docs/DEPLOY.md`. Shape of it:

| Phase | Work | Needs AWS access? |
|---|---|---|
| 0 | Pre-flight: confirm `main` deployable, generate a strong `SECRET_KEY`, reuse the existing `paw_app` RDS schema for accounts | No — can do now |
| 1 | Provision Lightsail: us-east-2, Ubuntu 22.04, 2 GB ($10) plan, static IP, firewall 22/80/443 | **Yes** |
| 2 | RDS security group: allow `3306` from the server IP `/32` only | **Yes** |
| 3 | Server setup: python3.12 + venv + `requirements.txt`, `playwright install --with-deps chromium` (pinned `1.61.0`), `.env` at mode 600 | No (SSH only) |
| 4 | `systemd` unit `paw.service` + nginx reverse proxy → gunicorn on loopback :8050 | No |
| 5 | DNS record + Let's Encrypt HTTPS via certbot | Only if DNS is in AWS |
| 6 | Smoke tests (below) | No |
| 7 | Cutover: keep Render live a week as fallback, then retire | No |
| 8 | Day-2: documented `git pull` + restart procedure, `paw_app` backups, log rotation, `report_cache` pruning | No |

**Effort estimate:** with access in hand, phases 1–6 are roughly a half-day of
focused work. The hard part is access, DNS, and the policy question — not the
server.

**Known traps already documented, so we do not re-learn them:**

- Pin `playwright==1.61.0` and re-run the browser install **together** — a version
  drift is what broke every PDF download on Render (2026-08-20).
- Set `APP_DB_NAME=paw_app` so accounts, coach notes, and dev plans persist across
  restarts instead of vanishing with an ephemeral SQLite file.
- Never paste an env var with a literal `…` in it (cost us a DNS debug cycle), and
  never load the DB password through `source .env` in bash — the `$#` in it gets
  silently mangled.

**Definition of done — test from a phone, off campus Wi-Fi:** login page loads with
a valid cert → coach login works → all six dashboards load real data → player login
is read-only → one pitcher PDF downloads → reboot the server and confirm accounts
still exist → confirm RDS is no longer open to the whole internet.

---

## 6. Leave-the-meeting checklist

- [ ] **Who set up the database in Aug 2024, and does the program control that account?** (see §3b)
- [ ] A local backup of the warehouse taken BEFORE the meeting or any outreach (§3b, §3f)
- [ ] Coach confirms the 2025 credential is a Builder ID, not an account (§3d)
- [ ] Does the athletics budget show an AWS line item, and who approves it? (§3c)
- [ ] Plan for the ~600 GB `lmubsbvideo` S3 bucket, not just the database (§3c)
- [ ] **Coach agrees to create a real program-owned AWS account** (§3e) — replaces the old "add me as an IAM user" ask, which is impossible
- [ ] Name + email of the AWS account admin (or a filed IT ticket number)
- [ ] AWS account ID confirmed, `us-east-2`
- [ ] IAM user created, or a committed date for it
- [ ] ~$10/mo approved, and on whose account
- [ ] Second admin named for continuity
- [ ] Hostname decision + DNS contact if school-branded
- [ ] Coach + player launch credentials agreed
- [ ] List of everything else using the RDS password (for rotation)
- [ ] Data-policy answer, or the ITS contact who gives it
- [ ] In-season support expectations
- [ ] Cauldron formulas + point values, Barrel% definition, logo call
- [ ] Fallback agreed: if AWS access stalls, Path B ($7/mo Render) is approved
