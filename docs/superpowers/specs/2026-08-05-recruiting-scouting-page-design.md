# Recruiting Scouting Page — Design / Jira Ticket

**Date:** 2026-08-05
**Status:** Spec — to be posted to Jira **unassigned, low priority** (intern project)
**Type:** Feature

---

## Summary

Add a coach-only **Coaching Development** section to the PAW home page whose first
tool is a **Recruiting** scouting database. It scrapes public college-baseball data
(team rosters + free NCAA season stats) into a searchable, filterable table so
coaches can find players matching a team need (e.g. "power-hitting first baseman",
"quick center fielder") instead of working from pen and paper.

## Background / context

College recruiting at LMU is largely manual. A searchable scouting database built
from public data is a low-cost competitive edge. This ticket is scoped for an intern
and is **explicitly a scouting database, NOT a live transfer-portal feed** — see
"Honest scope framing" below. That distinction was a deliberate decision, not an
oversight.

## Goal

A coach logs in, opens **Coaching Development → Recruiting**, and filters a pool of
~75–100 programs' players by position, class, physical attributes, and performance
stats to build a shortlist of targets that fit team needs.

---

## Honest scope framing (read before estimating)

- **This is a scouting database, not a portal tracker.** It surfaces *who exists and
  how they perform* from public sources. It does **not** indicate who has entered the
  NCAA Transfer Portal.
- **Why:** the official Transfer Portal is a closed NCAA compliance system (credentialed
  access only) with no public page to scrape. Paid aggregators (On3/247/D1Baseball) hold
  the public portal lists but gate them behind subscriptions and prohibit scraping in
  their ToS. We are deliberately **not** paying for a feed and **not** scraping paid
  aggregators.
- **Legal / etiquette (non-negotiable):** scrape only official/public sources (school
  roster pages, `stats.ncaa.org`). Respect `robots.txt`, rate-limit politely, run as a
  slow batch. Do **not** scrape paid aggregators.

---

## Scope — MVP

### 1. Navigation & access
- **Home page** (`app/templates/main/index.html`): add a 4th `card_grid` card
  **"Coaching Development"** → new route `main.coaching_development` (`/coaching-development`).
  Card is shown to coaches only (existing `{% if user.is_coach %}` pattern).
- **Hub page**: new `app/templates/main/coaching_development_hub.html` (clone of the
  existing `pitching_hub.html` / `hitting_hub.html` pattern, using the shared
  `partials/_module_card.html` `card_grid` macro). First card = **"Recruiting"** →
  `/dash/recruiting/`. Structured as a hub so future coaching-dev tools can be added.
- **Coach-only, enforced in two places** (defense in depth):
  - Hub route decorated with the existing `@role_required("coach")` (`app/auth/access.py`).
  - The Dash page re-checks `current_user.role == "coach"` server-side; a player hitting
    the URL directly gets a 403 / "coaches only" state.

### 2. Data pipeline — `flask ingest recruits`
Mirror the existing `flask ingest bullpen` CLI and `scripts/scrape_roster_media.py`
patterns (dry-run first, idempotent upsert).

- **Config-driven school list** — `app/data/recruiting_sources.py` (or JSON/YAML):
  entries of `{school, conference, roster_url, ncaa_stats_id}`, **grouped by conference**.
  Seed target **~75–100 programs**: power conferences (SEC, ACC, Big 12, Big Ten) +
  West-region footprint (WCC, Big West, Mountain West, Pac-12 remnants). Expanding
  coverage = editing config, **no code change**.
- **Roster scrape** — reuse the Sidearm/BeautifulSoup approach from
  `scrape_roster_media.py`: name, position, class year, height, weight, bats/throws,
  hometown, headshot URL.
- **Stats enrichment** — pull public season stats from `stats.ncaa.org` and match to
  roster players **by normalized name within the same school** (school-scoping makes the
  fuzzy match far safer than global matching; reuse the normalization/`(last, first-initial)`
  fallback logic already in `roster_media`). Hitters: AVG/OBP/SLG/HR/SB/etc.; pitchers:
  ERA/K9/BB9/etc. Unmatched players keep roster data with blank stats.
- **Robustness** — non-Sidearm layouts and stat pages we can't parse are
  **logged-and-skipped**, never crash the batch. Coverage gaps are recorded and visible,
  not silent.
- **Storage** — new `recruits` table in the app DB (`instance/paw_app.db`; SQLAlchemy
  model registered before `db.create_all()` like `DevPlan`/`GameNote`). One row per
  player; `scraped_at` timestamp; idempotent upsert on `(school, normalized_name)` so
  re-runs refresh cleanly.
- **Cadence** — run manually / weekly (recruiting data does not change hourly). Wire into
  the deploy scheduler later alongside the SP5 warm-reports plan.

### 3. The Recruiting page — `/dash/recruiting/`
- New `app/dashboards/recruiting/` package on the shared `shell` (`index_string`,
  `header` with a back-link to the Coaching Development hub), mirroring the other Dash
  apps (`index`/`layout`/`callbacks`/`tables`).
- **Composable filter bar** (MVP; no archetype presets): position multi-select · class
  year · bats/throws · height range · weight range · school/conference · stat-range
  controls (HR, SLG, AVG, SB for hitters; ERA, K/9 for pitchers) · free-text name search.
- **Results DataTable** — sortable columns (name, school, position, class, key stats,
  physicals), headshot where available.
- Filtering is **in-memory** over the loaded table (hundreds–low-thousands of rows;
  sub-second, no caching needed — consistent with the other PAW dashboards).

### 4. Testing (repo convention)
- Unit tests for the scrape parsers against **saved HTML fixtures** (do not hit the network
  in tests).
- Unit tests for the name-matcher and the filter logic.
- A render-smoke test for the Dash page.
- A `role_required` test proving a **player gets 403** on the hub and the dashboard.

---

## Out of scope / Phase 2
- **Player detail / profile card** on row click (MVP = filterable table only).
- **Archetype presets** ("Power 1B", "Speedy CF") — one-click filter pre-fills; cheap to
  add once composable filters exist.
- Transfer-portal status flags; paid data sources; parsers for non-Sidearm roster sites;
  "fit vs LMU team needs" scoring; expanding the seed to all ~300 D1 programs.

---

## Acceptance criteria
1. A **coach** sees a "Coaching Development" card on the home page; a **player** does not.
2. The card opens a hub whose first item is "Recruiting"; opening it loads
   `/dash/recruiting/`.
3. A **player** navigating directly to the hub URL or `/dash/recruiting/` receives a 403 /
   coaches-only state.
4. `flask ingest recruits --dry-run` reports what it would scrape without writing;
   `flask ingest recruits` populates/refreshes the `recruits` table idempotently.
5. The scraper covers the seeded conferences, rate-limits, respects `robots.txt`, and
   logs-and-skips unparseable sources without aborting the run.
6. The page filters the pool by at least: position, class, bats/throws, physical range,
   school/conference, and a hitter and a pitcher stat range; results are sortable.
7. Tests pass, including the parser-fixture, filter, and player-403 tests.

## Risks / notes
- **Data completeness** varies by school (non-Sidearm sites, missing stat matches) —
  acceptable for MVP; gaps are logged.
- **Name-matching** roster↔stats is fuzzy even school-scoped; unmatched = blank stats,
  not a wrong match.
- **Source fragility** — public sites change markup; the config + log-and-skip design
  contains breakage to individual schools.

## Rough effort
Intern-sized, low priority. Suggested breakdown: nav/hub/gate (S) · scrape+ingest CLI (M/L,
the bulk) · Dash page + filters (M) · tests (S). Ship nav + a small seed first to prove the
pipeline end-to-end, then expand the config.
