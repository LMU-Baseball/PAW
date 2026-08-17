# Vendor Biometrics Integration — Prep

**Status:** Planning. No sample data or format spec in hand yet. This doc records
the recommended approach and the exact list of things to get from the vendor so
that building is a fast, unblocked follow the moment a sample file arrives.

**What we're integrating:** biometric / biomechanics feedback for pitchers and
hitters from an outside vendor (per the program's paid vendor partnership; likely
the markerless-motion vendor previously noted as "Uplift"). The vendor **pushes**
data to us.

> **Do not build the tables/loader from guesses.** Biometric exports are highly
> vendor-specific (per-frame joint angles, kinematic-sequence values, session
> metadata, their own athlete IDs). The schema is dictated by their actual export
> format — designing it before we see a real file just creates rework. The
> unblocking artifact is **one sample export**, not more design.

---

## Recommended architecture: owned-inbox + staging

The vendor drops files into an inbox **we own**; our loader ingests on a
schedule. The vendor never connects to our database directly.

```
Vendor  ──push──▶  Inbox we own          ──loader──▶  Raw staging table   ──transform──▶  Clean tables
                   (S3 bucket or SFTP)                (payload stored              (only the fields we
                                                       untouched)                   use, keyed to players)
```

**Why this shape:**

- **No database exposure.** The vendor only writes to an inbox. Our code decides
  what is valid before anything is inserted. This is far safer than granting them
  a database user (see "Rejected alternatives").
- **It matches the existing codebase.** PAW already ingests external data this
  way — see the `warehouse → games` flow in `app/ingest/`. The new loader should
  follow the same pattern (staging/raw table first, then a transform step).
- **Raw-first is resilient.** Landing the untouched payload in a staging table
  means a change in their format never silently corrupts our clean tables — we
  re-run the transform, we don't re-fetch.

### The one tricky piece: athlete identity (crosswalk)

The vendor's athlete IDs will **not** match our Trackman player IDs. We'll need a
small crosswalk table mapping *their athlete → our player*. Flag this to the
vendor now and ask what identifier they attach to each session (name, jersey,
their own ID). Without it we can't join their biometrics to our game data.

---

## What is blocked vs. buildable

| Piece | Blocked on AWS? | Notes |
|---|---|---|
| Designing the raw + clean tables | ❌ No | Needs a **sample file**, not AWS |
| Writing + testing the loader/transform | ❌ No | Testable locally against a sample file |
| The athlete crosswalk table | ❌ No | Needs the vendor's identifier field |
| Standing up the inbox (S3 bucket / SFTP) | ✅ Yes | Needs the head coach's AWS account |
| Issuing the vendor credentials / IP allowlist | ✅ Yes | AWS + vendor coordination |
| Scheduling the ingest cron on the live server | ✅ Yes | After deploy |

**Bottom line:** the design and build wait on a **sample export**, not on AWS.
Only *going live* waits on AWS.

---

## Vendor-request checklist

Send this to the vendor. Getting #1 alone unblocks all the buildable work.

1. **A sample export file** — even one session (CSV or JSON). The single most
   important item.
2. **A data dictionary / field spec** — what each column/field means and its
   units.
3. **Delivery mechanism they support** — can they push files to an **S3 bucket**
   or **SFTP server we provide**? Or is data only available by calling **their
   API**? (This confirms the integration shape.)
4. **Cadence** — per session, nightly batch, or real-time?
5. **Athlete identifier** — what ID/label they attach to each session, so we can
   map it to our roster.
6. **Auth model** — API key, SFTP credentials, IP allowlist, signed URLs?
7. **Volume & retention** — rough rows/size per session, and how long they retain
   data on their side.

---

## Rejected alternatives (and why)

- **Vendor connects directly to our RDS with a granted DB user.** Exposes the
  database to an outside party and is the most AWS-blocked (their IPs into the RDS
  security group + a new limited user). Avoid unless the vendor cannot deliver any
  other way.
- **We expose a public POST endpoint in the Flask app for them to send to.** More
  to build and validate, and it only works once the app is deployed. Reasonable
  fallback if the vendor can *only* push over HTTP and cannot drop files — revisit
  then.

---

## Next steps

1. Send the vendor-request checklist above; get a **sample export**.
2. Confirm the delivery mechanism (S3/SFTP inbox we own is the target).
3. Once a sample lands: design the raw + clean tables and crosswalk, then build
   the loader/transform in `app/ingest/` following the existing pattern (TDD,
   tested against the sample file). None of that needs AWS.
4. In parallel, once AWS access is granted: provision the inbox + vendor
   credentials, then schedule the ingest.

**Storing the vendor's credentials:** whatever key/creds we receive go in `.env`
(never committed), alongside the existing `TM_SFTP_*` / `HT_FTPS_*` entries — see
`.env.example`.
