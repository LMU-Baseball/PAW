# Roster Photo/Jersey Scrape — Design

**Date:** 2026-07-20
**Branch:** `feat/pitcher-postgame-report`
**Status:** Approved (brainstorming) → implement

## Goal

Fill the hitting sidebar's **photo** and **jersey number** (currently a lion
placeholder + no jersey) by scraping the LMU baseball roster page, mapping players
to their Trackman `batter_tm_id`, and storing the result as a small JSON file the
dashboard reads.

## Context

- LMU roster: `https://lmulions.com/sports/baseball/roster` (Sidearm platform;
  `schools.id 194`). Confirmed reachable from Python (`urllib`, 1.2 MB static HTML).
- The page has **45 `li.sidearm-roster-player` cards**, each with a
  `.sidearm-roster-player-jersey-number` and an `<img>` whose CloudFront `src`
  encodes the player name (e.g. `.../Matt_Moreno.jpg?width=80&quality=90`).
- `roster_players` (analytics DB) already holds the current roster (name/class/
  position) but **no photo/jersey** — and it's owned by a separate scraper, so we
  do NOT write there.
- The warehouse fact table gives `(batter_tm_id, batter_name)` for LMU hitters,
  where `batter_name` is `"Last, First"`.

## Components

### 1. `scripts/scrape_roster_media.py` (standalone; run manually, schedulable later)
- Fetch the roster HTML (`urllib` + browser UA).
- Parse with BeautifulSoup (already a dependency, 4.13.4): for each
  `li.sidearm-roster-player` extract **jersey** (`.sidearm-roster-player-jersey-number`),
  **photo_url** (card `<img>` `src`), and **name** (prefer the name anchor; fall
  back to the img filename `First_Last` → "First Last").
- Upscale the photo: rewrite `?width=80` → `?width=360` for a crisp sidebar image.
- Load `(batter_tm_id, batter_name)` for LMU from `fact_tm_game_pitch`; **match by
  normalized name** — `_norm("Carmona, Jose") == _norm("Jose Carmona Jr.")` →
  `"jose carmona"` (lowercase, strip punctuation, drop suffixes Jr./Sr./II/III/IV,
  order-insensitive by sorting name tokens). Write an entry for **every**
  `batter_tm_id` whose name matches (covers canonical + split-sibling ids).
- Write `instance/roster_media.json`:
  `{"<batter_tm_id>": {"jersey": "34", "photo_url": "...", "name": "Zach Wadas"}}`.
  Idempotent (overwrites). Print a summary: scraped N, matched M, list unmatched
  roster names + unmatched hitters (so gaps are visible, never silent).

### 2. `app/data/roster_media.py`
- `load_roster_media() -> dict` — read `instance/roster_media.json` (module-cached;
  returns `{}` if the file is missing). Path via the Flask instance dir when in an
  app context, else `instance/roster_media.json` relative to repo root.
- `player_media(batter_tm_id) -> dict` — `{"jersey": ..., "photo_url": ...}` for the
  id, or `{"jersey": "", "photo_url": ""}` if absent.
- `_norm_name(s) -> str` — the shared normalizer (used by the script + tests).

### 3. Wire-in — `app/data/hitting_wh.py::wh_player_profile`
- Merge `player_media(batter_tm_id)` into the returned dict: set `photo` =
  `photo_url` and `jersey` when present (today both are `""`). Everything else
  unchanged. The sidebar already renders `photo` (lion fallback) + a `#jersey`
  chip, so they appear automatically; missing/unmatched → current placeholder.

## Testing

- `_norm_name` (pure): "Carmona, Jose" ↔ "Jose Carmona Jr." match; distinct names
  don't; suffix/punctuation/case handled.
- `player_media` / `load_roster_media`: with a temp JSON file (monkeypatch the path)
  — returns the entry; missing file → `{}` / blanks; unknown id → blanks.
- `wh_player_profile` merge: monkeypatch `player_media` to return jersey/photo and
  assert the profile carries them.
- **Live run**: execute the script, confirm `roster_media.json` is written with a
  high match rate, and the sidebar shows real photos + jerseys (Playwright).
  (The network fetch+parse is verified by the live run — consistent with the repo's
  live-DB, unguarded test convention.)

## Decisions / notes

- **Storage = JSON in gitignored `instance/`** (app-owned; no DB schema change; does
  not touch the analytics DB or the other roster scraper).
- **No new dependency** — BeautifulSoup is already installed.
- **Parser resilience**: if a card lacks jersey or img, skip that field (don't
  crash); name-match failures are reported, not fatal.
- **Refresh**: manual `python scripts/scrape_roster_media.py` for now; a scheduled
  run can be added later (ties into the §9 pipeline-health follow-up).
- **Provisional name-match**: exact-normalized match only (no fuzzy). Unmatched
  players keep the placeholder; the run summary lists them for manual follow-up.
