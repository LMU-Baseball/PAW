# Home Page Redesign + Brand Refresh — Design

Date: 2026-07-17
Branch: `feat/pitcher-postgame-report`
Status: approved design, pending spec review

## Problem

The home/landing page (`app/templates/main/index.html`) is a plain white card with a
role line and three bare bullet links (Hitting, Pitching Reports, Catching). It does
not reflect the polished "athletic/broadcast" look the rest of the app has adopted, and
it does not use LMU branding beyond the shared header.

The legacy R Shiny source (`src/app 1`..`app 4`, `app.R`) has **no unified home page** —
it was five separate dashboards. Each shared one signature look: a fixed crimson top
banner (`#9A0021`, 80px) with the app name in **Alfa Slab One** (e.g. "THE HITTER'S
PAW"), the LMU logo pinned top-left, and **Teko** body text. "Matching the R source"
therefore means adopting that *design language* on a real home page — which R never had.

New brand assets are now available (copied to `app/static/brand/`):
- `lions-arch.png` — "LIONS" arched wordmark, crimson with white+blue double outline, transparent bg.
- `palms.png` — subtle grey palm-tree silhouettes.
- `lmu-colors-reference.jpeg` — official LMU brand-color reference (not a display asset).

The reference confirms the **official** LMU colors, which differ slightly from what the
app currently uses:
- LMU Crimson = **#AB0C2F** (PMS 207) — app currently uses `#9A0021`.
- LMU Blue = **#0076A5** (PMS 2185) — app currently uses `#2864a8`.

## Decisions (confirmed with the user)

1. **Scope:** redesign the home page **and** refresh the shared header (`base.html`).
   Login and pitching-landing pages inherit the shared changes.
2. **Colors:** adopt the official colors **everywhere**, including the PDF report header
   (report crimson shifts `#9A0021` → `#AB0C2F`). Report *layout* is unchanged.
3. **Display font:** introduce **Alfa Slab One** (self-hosted) for the home-page marquee,
   Teko for everything else.
4. **Layout:** approach A — marquee hero + three module cards.

## Design

### 1. Design tokens & fonts (`base.html`)

Update the `:root` tokens:

```
--crimson:      #AB0C2F;   /* official LMU Crimson (PMS 207) */
--crimson-dark: #8a0a26;   /* hover / darker crimson */
--blue:         #0076A5;   /* official LMU Blue (PMS 2185) */
--blue-dark:    #005e84;   /* darker blue kept for text-on-light contrast */
--font-marquee: "Alfa Slab One", Georgia, serif;
```

- Add a `@font-face` for `"Alfa Slab One"` (weight 400) pointing at a self-hosted
  `AlfaSlabOne-Regular.ttf`. base.html deliberately avoids CDNs, so the file must be
  local. **Acquisition:** download from the Google Fonts repo during implementation;
  if unavailable offline, fall back to Teko Bold for the marquee and flag it.
- Update the focus-ring `box-shadow` rgba from `rgba(154,0,33,.15)` to the new crimson
  `rgba(171,12,47,.15)`.

### 2. Shared header

Keep the existing header layout (LMU logo + wordmark left; user · role · Log out right).
It re-colors automatically via the crimson token. The wordmark stays **Teko** so the
persistent bar remains compact; Alfa Slab One is reserved for the home hero marquee.

### 3. Home hero (`index.html`)

A full-width official-crimson hero card (rounded, matching the pitching-landing `.hero`
pattern) containing, stacked/centered:
- the **LIONS arched wordmark** (`lions-arch.png`),
- **"THE PAW"** in Alfa Slab One, white, large,
- a Teko tagline: "LMU Baseball Analytics",
- a **role-aware** welcome line:
  - coach: "Welcome, {name} — signed in as coach: view every LMU player & add notes."
  - player: "Welcome, {name} — signed in as player: your own postgame data."

The **palms silhouette** (`palms.png`) is a subtle, low-opacity (~0.12) decorative motif
anchored to the bottom of the light module-cards section (not on the crimson hero, since
the silhouettes are grey). Purely decorative; `aria-hidden`.

### 4. Module cards

A responsive row/grid of three cards below the hero, reusing the site card + hover-lift
style:
- **Hitting** → `/dash/hitting/` — "Swing decisions, batted ball, plate discipline."
- **Pitching Reports** → `url_for('reports.pitching_landing')` — "Postgame pitcher reports (PDF)."
- **Catching** → greyed "Coming soon" state, no link.

Each card: crimson title (Teko), a blue accent line/rule, short description, whole card
clickable where a destination exists. Catching is visibly disabled.

Page-specific CSS lives in an `index.html` `<style>` block (same pattern as
`pitching_landing.html`); shared tokens/classes come from `base.html`.

### 5. Report color swap ("official colors everywhere")

Hue-only change, no layout change:
- `app/reports/static/report.css`: every `#9A0021` → `#AB0C2F`; retune the blue chip
  shades around `#0076A5` while preserving text contrast on light backgrounds
  (`.chip.good` light-blue tint + `--blue-dark` text; `.chip.good-strong` solid blue,
  white text; `.chip.bad-strong` solid `#AB0C2F`, white text).
- Report templates (`pitcher_onepager.html` header, panel titles): crimson refs → `#AB0C2F`.
- `app/reports/plots.py`: chart title color, Fastball pitch color, and any `#9A0021`
  → `#AB0C2F`.
- Clear `instance/report_cache/` after so downloads rebuild with the new hue.

### 6. Assets

- `app/static/brand/lions-arch.png`, `palms.png` — already copied.
- `app/static/brand/AlfaSlabOne-Regular.ttf` — to be added (see acquisition note).
- `lmu-colors-reference.jpeg` — reference only; not rendered.

## Testing

- **Home page** (`tests/`): with the test client + a logged-in user, GET `/` and assert
  the hero marquee ("THE PAW"), the LIONS wordmark asset path, all three module labels,
  the correct module links (`/dash/hitting/`, pitching landing), and the role-aware line
  (coach vs player copy).
- **Shell** (`tests/test_shell.py`): update any assertions that pin the old crimson hex
  or header strings; keep the logo/wordmark checks.
- **Visual:** Playwright screenshot of the home page logged in as coach and as player;
  re-render one pitcher report to confirm the color swap reads correctly.
- Full suite must stay green (currently 108 passing).

## Out of scope / non-goals

- No new backend routes or data changes (`main.index` still just renders with `user`).
- No re-theming of the pitching-landing or login page layouts beyond what the shared
  token/header changes give them for free.
- No changes to report *content or layout* — only the crimson/blue hue.
- The additional report charts flagged earlier (season column, donuts, velo bar, zone
  scores, count charts) remain a separate coach question, not part of this work.

## Risks

- **Alfa Slab One acquisition** offline — mitigated by the Teko Bold fallback.
- **`palms.png` transparency** — if the PNG has a solid white background rather than
  transparency, it will be placed on the light `#f5f5f5` section (where grey-on-light
  reads as intended) rather than overlaid on a colored surface; verify at implementation.
- **Report hue shift** — coaches approved the report *layout*, not this exact hue; the
  shift from `#9A0021` to `#AB0C2F` is small and was explicitly requested ("everywhere").
