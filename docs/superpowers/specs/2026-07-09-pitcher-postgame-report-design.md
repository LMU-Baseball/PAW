# Pitcher Postgame Report — Design Spec

**Date:** 2026-07-09
**Status:** Approved design, pending spec review
**Replaces:** `runPitcherPostgameReport.R` (R Markdown → LaTeX pipeline)

## Goal

Produce a clean, branded, downloadable **pitcher postgame PDF** generated entirely in
the Python/Flask stack. The old R pipeline (R Markdown → LaTeX → PDF) was brittle
(hard-coded absolute paths like `/Users/shayeobeirne/Desktop/...`) and looked poor.
We start the presentation over while keeping the same report *sections*.

Two deliverables:

1. A **reusable HTML→PDF report engine** (`app/reports/`) that any future report
   (hitting, catching) can reuse.
2. A **report-only pitcher data layer** (`app/data/pitching.py`) that queries the
   modern Trackman warehouse and computes exactly what this report needs.

## Data source decision: modern Trackman warehouse (not legacy `GAMES`)

The report reads from the **modern warehouse**, populated by the live
Trackman → SFTP → ELT → AWS RDS pipeline, rather than the legacy `GAMES` table the R
apps used.

| Concern | Legacy `GAMES` | Warehouse (chosen) |
|---|---|---|
| Grain | pitch-level, 175 mixed cols | `fact_tm_game_pitch`: pitch-level, 92 typed snake_case cols |
| Dates | `Date` VARCHAR `"5/3/24"` | `dim_tm_game.game_date` proper `DATE` |
| Coverage | 2024 → May 2025 | Fall 2025 + Spring 2026 (current, going-forward) |
| Pitch types | tagged/auto only | tagged + auto + **`ml_pitch_type`** (ML-classified) |
| Helpers | none | pitcher views pre-compute several sections |
| Populated by | manual/legacy | the live ELT pipeline (auto) |

**Primary tables/views:**

- `fact_tm_game_pitch` — one row per pitch. Fields used: `game_id`, `pitcher_id`,
  `pitcher_name`, `pitcher_throws`, `batter_side`, `inning`, `balls`, `strikes`,
  `outs`, `pa_of_inning`, `pitch_of_pa`, `pitch_no`, `batters_faced`,
  `tagged_pitch_type` / `auto_pitch_type` / `ml_pitch_type`, `rel_speed`, `spin_rate`,
  `spin_axis`, `tilt`, `rel_height`, `rel_side`, `extension`, `induced_vert_break`,
  `horz_break`, `plate_loc_height`, `plate_loc_side`, `vert_appr_angle`,
  `horz_appr_angle`, `pitch_call`, `play_result`, `korbb`, `outs_on_play`,
  `runs_scored`, `izt_zone`, `zi`.
- `dim_tm_game` — game context: `game_id`, `game_date`, `season_label`, `game_type`,
  `home_team_id`, `away_team_id`, `stadium`.
- `tm_player` — `player_id` → `first_name`, `last_name`.
- `vw_game_pitchers` — `(game_id, player_id, display_name)`: pitcher list per game.
- `vw_pitcher_recent_outings` — per appearance: `appearance_avg/max/min_velo`,
  `pitch_count`, `appearance_rank`, home/away team names → **Last-5-Outings** table.
- `vw_pitcher_velo_trend` — per appearance velo + `velo_change` → **velo-trend** plot.

**Report keys:** warehouse `game_id` (int) + `pitcher_id` (bigint). Pitcher name and
game/opponent context resolve via `tm_player` / `dim_tm_game` / the pitcher views.

**Caveat (documented, accepted):** the warehouse holds current-season data only.
Reports for older 2024/2025 games are not supported by this source. That is acceptable
because postgame reports target current games flowing through the live pipeline.

## Report sections (same as the old report; curated layout)

1. **Header** — LMU logo (`lmu.png`), pitcher name, handedness, opponent + game date +
   game type (from `dim_tm_game` / recent-outings view), and **final score**. The score
   is derived from the warehouse: sum `fact_tm_game_pitch.runs_scored` grouped by
   `top_bottom` (Top = away batting, Bottom = home batting) over all pitches of the game,
   then map home/away to LMU-vs-opponent. Scraping the LMU baseball site is a documented
   fallback only if the derived total proves unreliable.
2. **Game Overall** — appearance line: pitches, batters faced, K, BB, strike%, whiff%,
   in-zone%, chase%, first-pitch-strike%, runs. Derived from `fact_tm_game_pitch`
   (`pitch_call`, `play_result`, `korbb`, `runs_scored`).
3. **Pitch Characteristics** — per pitch type: count, usage%, avg & max velo, spin rate,
   spin axis/tilt, induced vert break, horz break, rel height/side, extension.
4. **Pitch Usage** — usage counts overall, by count situation (balls–strikes buckets),
   and vs LHH/RHH.
5. **Velo plots** — velo by inning; velo across the outing (by `pitch_no`).
6. **Zone Location table** — in-zone%, chase%, strike% by zone (`izt_zone` / `zi`).
7. **Movement plot** — `horz_break` vs `induced_vert_break`, colored by pitch type.
8. **Location plot** — `plate_loc_side` vs `plate_loc_height` with strike-zone box,
   colored by pitch type.
9. **Last-5-Outings** — averages table (from `vw_pitcher_recent_outings`) + velo-trend
   plot (from `vw_pitcher_velo_trend`).
10. **LHH/RHH split** — Game Overall + Usage tables split by `batter_side`; location
    plots split by batter side.
11. **Heatmaps** — overall pitch-location density + per-pitch-type density, using
    Plotly 2D density (no `scipy` dependency).

## Architecture & components

### 1. Report engine — `app/reports/` (reusable, module-agnostic)

- **`pdf.py`** — `html_to_pdf(html: str, base_url: str | None = None) -> bytes`.
  Headless Chromium via Playwright (sync API); `page.set_content(html)` then
  `page.pdf(print_background=True, format="Letter", margin=...)`. This is the single
  piece every future report reuses. Chromium launched once per call; a module-level
  lazy browser/context is acceptable if startup cost matters.
- **`charts.py`** — `fig_to_data_uri(fig) -> str`: Plotly figure → PNG bytes via kaleido
  → base64 `data:image/png;base64,...`. Keeps the HTML fully self-contained (the fix for
  the old absolute-path problem).
- **`templates/pitcher_postgame.html`** + **`report.css`** — Jinja template. Teko
  `@font-face` and `lmu.png` referenced from bundled static assets. Print CSS controls
  `@page` size/margins and section page-breaks (`break-inside: avoid`).

### 2. Pitcher data layer — `app/data/pitching.py`

Mirrors the shape of `app/data/hitting.py` (queries via `app.db.query_df`, transforms in
pandas). Report-only subset:

- **Queries:** `game_context(game_id)` (incl. `final_score(game_id)`: runs summed by
  `top_bottom`), `game_pitches(game_id, pitcher_id)`,
  `recent_outings(pitcher_id, game_id)` (from `vw_pitcher_recent_outings`),
  `velo_trend(pitcher_id)` (from `vw_pitcher_velo_trend`),
  `pitchers_for_game(game_id)` (from `vw_game_pitchers`).
- **Transforms (pandas):** `game_overall_line`, `pitch_characteristics`, `pitch_usage`,
  `zone_location`, `usage_by_count`, `splits_by_batter_side`, `averages_last5`.
  Percentages returned NUMERIC (not preformatted strings), consistent with `hitting.py`.
- **Figure builders (Plotly):** `fig_velo_by_inning`, `fig_velo_by_pitch`,
  `fig_movement`, `fig_location`, `fig_velo_trend`, `fig_location_split`,
  `fig_heatmap_overall`, `fig_heatmaps_by_pitch_type`.

Pitch-type field: use **`tagged_pitch_type`** (the human-tagged type the staff trusts).
`auto_pitch_type` is a fallback only when the tag is null.

### 3. Assembler — `app/reports/pitcher_postgame.py`

`build_pitcher_postgame(game_id: int, pitcher_id: int) -> bytes`:
queries → transforms → figures → base64 → render Jinja context → `html_to_pdf` → PDF
bytes. Raises a typed `ReportDataError` when the pitcher/game has no pitches (the
Python equivalent of the R `req(pitcher())` guard).

### 4. Delivery — `app/reports/routes.py` (Flask blueprint)

- `GET /reports/pitcher/<int:game_id>/<int:pitcher_id>.pdf`
- `@login_required` + role gate via existing `app/auth/access.py`
  (`can_view_player` / `role_required`).
- Returns `Response(pdf_bytes, mimetype="application/pdf")` with
  `Content-Disposition` (inline by default; `?download=1` forces attachment).
- Replaces the old `runjs("window.open(...)")` hack. The future pitcher Dash UI links a
  "Download Game Report" button/anchor to this route.
- Blueprint registered in `app/__init__.py:create_app`.

### 5. Static assets

Relocate the shared branding assets from `Re_ PAW scripts/www/www/` into
`app/static/reports/`: Teko fonts (`Teko-*.ttf`), `lmu.png`, `lmu-bsb.png`. Referenced by
`report.css` `@font-face` and the template header. `__MACOSX/` junk is ignored.

## Data flow

```
GET /reports/pitcher/<game_id>/<pitcher_id>.pdf   (login + role gated)
  -> build_pitcher_postgame(game_id, pitcher_id)
       -> app/data/pitching.py queries         (fact_tm_game_pitch, dim_tm_game, views)
       -> pandas transforms                     (overall, characteristics, usage, splits)
       -> Plotly figures -> kaleido PNG -> base64 data URIs
       -> Jinja render (pitcher_postgame.html + report.css + static fonts/logo)
       -> app/reports/pdf.py html_to_pdf()      (Playwright headless Chromium)
  -> Response(pdf_bytes, application/pdf)
```

## Error handling

- No pitches for `(game_id, pitcher_id)` → `ReportDataError` → route returns `404` with a
  friendly message.
- DB errors propagate from `query_df`; route returns `500` and logs.
- Playwright launch/render failure → logged with context; route returns `500`.
- Missing/null pitch-type values handled by the fallback chain above.

## Testing

- **`tests/test_pitching.py`** — invariant tests for transforms against the live
  warehouse (counts ≥ 0, usage% sums ≈ 100, velo within sane bounds, split rows
  reconcile to totals), matching the `tests/test_hitting.py` style.
- **`tests/test_pitcher_report.py`** — smoke test: build a PDF for a known
  `(game_id, pitcher_id)` (e.g. Avery Laine, a Spring 2026 game) and assert the result
  is non-empty and starts with `%PDF`. Marked/skipped gracefully if Chromium isn't
  installed in CI.
- Chart builders unit-tested for "returns a Figure with expected trace count" without
  needing kaleido.

## Dependencies (added to `requirements.txt`)

- `playwright` (+ one-time `playwright install chromium`)
- `kaleido` (Plotly static image export)

No `scipy` — heatmaps use Plotly's built-in 2D density.

## Out of scope (YAGNI)

- The full pitcher Dash UI (only the report + its data are built here).
- Historical (pre-Fall-2025) game support.
- Video, catcher, and hitting reports (the engine is reusable for them later).

## Open implementation questions (resolved during build, not blockers)

1. `tagged_pitch_type` null rate → confirm `auto_pitch_type` fallback is rarely needed.
2. Whether to cache the Chromium browser process across requests vs launch-per-request
   (start simple: launch-per-request; optimize if slow).
3. Sanity-check derived final scores (summed `runs_scored`) against a few known games;
   fall back to LMU-site scraping only if they don't reconcile.
