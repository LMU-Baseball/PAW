# Landing Page Styling — Design

**Date:** 2026-07-16
**Branch:** `feat/pitcher-postgame-report`
**Status:** Approved (design), pending implementation plan

## Goal

Give the PAW app a branded, "athletic/broadcast" visual identity (direction **B**).
Today the app is functional but unstyled: a plain crimson bar with the text
"THE PAW", system-ui font, and simple white cards with a `<select>` dropdown and a
bulleted list of pitcher links. This pass makes the **shared shell** and the
**pitching-report landing page** look like a real sports app.

This is a **presentational-only** change. No routes, data helpers, template
variables, or behavior change. The existing pitching-landing route tests must keep
passing untouched.

## Scope

**In scope (2 files):**
1. `app/templates/base.html` — the shared shell (header, fonts, design tokens,
   shared `.card`/`.btn`/`.flash` styling).
2. `app/templates/reports/pitching_landing.html` — hero banner, styled picker card,
   matchup header, pitcher row cards.

**Out of scope (deferred):** login page, home/index hero, hitting dashboard, the PDF
report itself. The home page (`app/templates/main/index.html`) inherits the shell
improvements automatically but gets no bespoke styling in this pass.

## Visual Identity (decided earlier)

- **Crimson** `#9A0021` (primary), **crimson-dark** (hover, ~`#7a001a`).
- **Blue accent** `#2864a8` (matches the logo's blue outline).
- **Light bg** `#f5f5f5`, **ink** `#1a1a1a`.
- **Font:** Teko for display (headings, logo text, buttons); system-ui for body copy
  (Teko is condensed and hard to read at paragraph size).
- **Assets** stay in `app/static/reports/` (decision (a) — no file moves), served by
  Flask at `/static/reports/...`:
  - `lmu.png` — transparent LMU wordmark (crimson fill, blue outline) → header bar.
  - `lmu-bsb.png` — crimson "LMU BASEBALL" block → hero banner.
  - `Teko-Regular.ttf` (400), `Teko-Medium.ttf` (500), `Teko-SemiBold.ttf` (600),
    `Teko-Bold.ttf` (700).

## Part 1 — Shared shell (`base.html`)

### Fonts
Add a local `@font-face` block loading the four Teko weights from
`/static/reports/Teko-*.ttf`. **No Google Fonts CDN** (offline / CSP). Use
`font-display: swap`. A `--font-display` variable holds the Teko stack; body keeps
system-ui.

### Design tokens
Promote the palette to CSS custom properties in `:root`:
`--crimson`, `--crimson-dark`, `--blue`, `--bg`, `--ink`, `--radius`, `--shadow`,
`--font-display`. All existing and new styles reference these.

### Header bar
- Crimson `#9A0021` bar, ~64px tall, flex row, space-between.
- **Left:** `lmu.png` wordmark (~40px tall) + "THE PAW" in Teko Bold, uppercase,
  letter-spaced. The whole left cluster links to home (`url_for('main.index')` or `/`).
- **Right:** existing `current_user.name · role · Log out`, restyled — white text,
  smaller, a faded divider/opacity; unchanged markup/logic.

### Shared components (restyled, same class names)
- `.card` — white, `--radius`, `--shadow`, subtle border, comfortable padding.
- `.btn` — crimson bg, white, Teko, uppercase-ish, `--radius`; hover →
  `--crimson-dark`, subtle lift. Used by the shell and inherited everywhere.
- `.flash.error` / `.flash.info` — keep current semantics, align to tokens.
- Form controls (`label`, `input`, `select`) — consistent border/radius and a
  crimson focus ring.

Because these are shared, every page (including home) picks up the polish for free
and the pitching page inherits most of its look.

## Part 2 — Pitching-report page (`pitching_landing.html`)

### Hero banner
Full-width crimson band at the top of the content area:
- `lmu-bsb.png` "LMU BASEBALL" block image.
- "PITCHING REPORTS" heading in Teko.
- One-line subtitle ("Pick a game, then download a pitcher's postgame report.").
- Rounded corners, shared shadow. Sits above the picker card.

### Step 1 — Game picker card
The existing `<select>` + "Show pitchers" button, restyled to the shared form/button
styles (Teko label, crimson focus ring). **Functionally identical** — still a GET
form to `reports.pitching_landing`, no JS.

### Pitcher results (replaces the bulleted list)
Shown only when `game_id` is set (unchanged condition):
- **Matchup header** for the selected game — "AWAY @ HOME" in Teko, with a date
  badge and a small pill for season label / game type. Falls back to "Selected game"
  when `selected_game` is absent (current behavior).
- **Pitcher row cards** — one per pitcher: `display_name` in Teko on the left, a
  crimson **"Download Report ↓"** button on the right linking to
  `reports.pitcher_pdf`. Hover lift/shadow. Responsive: on narrow screens the button
  wraps below the name (`flex-wrap`).
- **Empty state** — styled muted "No pitchers found for this game." message.

## Non-goals / constraints

- No JavaScript. Server-rendered only.
- No new dependencies.
- No changes to routes, data helpers, or template context variables.
- Inline `<style>` in the templates is acceptable (matches current pattern); no build
  step / external CSS bundler introduced.
- Existing tests (`tests/test_pitching_landing.py`, full suite 73 passing) must keep
  passing without modification — they assert on content/links, not styling.

## Verification

- `python run.py` → http://127.0.0.1:8050 (use 127.0.0.1, not localhost).
- Log in as coach (`coach@lmu.edu` / `paw2026`), visit `/reports/pitching`.
- Confirm: header shows logo + Teko wordmark; Teko is actually loading (not a
  fallback); hero banner renders `lmu-bsb.png`; picking a game shows the matchup
  header + pitcher row cards with working download buttons.
- Iterate CSS live on the running app (faster than mockups).
- `pytest` — full suite still 73 passing.
