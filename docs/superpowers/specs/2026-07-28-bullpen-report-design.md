# SP4 — Bullpen Reports Page (LMU-branded Trackman bullpen one-pager)

Date: 2026-07-28
Status: Approved design (brainstorm) — ready for plan.

## Purpose

A new standalone report page — parallel to the pitcher postgame reports — that
generates an **LMU-branded copy of the Trackman "Pitching practice" (bullpen)
report** (meeting Images #2 and #3) for a chosen pitcher + bullpen session.

## Data source + refresh model

- Source = the legacy **`BULLPEN`** table (raw Trackman practice export; verified
  2026-07-28: 6,032 rows, `PracticeType='Pitching'`, one row per pitch, all
  one-pager fields present).
- **Current coverage is stale** — data ends 2025-04-14 (the loader that fed it is
  dead). Per the user, the underlying files live on a **FileZilla SFTP server**,
  so `BULLPEN` can be repopulated from there later.
- **Design principle:** the report reads `BULLPEN` directly. Repopulating the
  table (SFTP pull → load) makes every report current with **no report code
  change**. Building that SFTP loader is a **separate data-engineering task,
  out of scope here** (documented as the refresh path).
- A visible **"Data through <max date>"** note on the landing page + report sets
  expectations while the table is stale.

### Key BULLPEN columns (→ report fields)

`TaggedPitchType`, `RelSpeed` (velo), `SpinRate`, `SpinAxis3dSpinEfficiency`
(spin eff %), `Tilt`, `InducedVertBreak` (IVB), `HorzBreak`, `VertBreak`,
`RelHeight`, `RelSide`, `Extension`, `PlateLocHeight`/`PlateLocSide` (location),
`Date`, `Time`, `PitchNo`, `Pitcher`, `PitcherId`, `PitchSession`
(`Live`/`Warmup`), `Team`.

### Pitcher identity / scoping

- `BULLPEN.PitcherId` (raw Trackman id, e.g. Geis = 824645) → warehouse
  `tm_player.player_id` via `tm_player_alias` (`source_system='trackman'`,
  `source_player_id` cast to CHAR). Geis resolves (→ player_id 55).
- LMU scoping = `Team IN ('LOY_MAR','LOY_LIO')` (both are LMU across Trackman
  naming eras; Geis is LOY_MAR). PROVISIONAL — confirm both codes are LMU;
  fall back to alias-resolvable pitchers if a code turns out non-LMU.
- A "session" = one `(PitcherId, Date)` group (optionally split by `PitchSession`
  — default: aggregate Live pitches; expose Warmup only if present). PROVISIONAL.

## Report layout (two pages, LMU-branded)

Reuses the existing report engine: `app/reports/pdf.py` (`html_to_pdf`),
`app/reports/plots.py` (matplotlib PNG data URIs), Jinja template + `report.css`,
LMU header assets (`lmu.png`, `lion-white.png`, crimson banner) — mirroring
`pitcher_postgame.py`. Trackman branding is replaced by LMU branding.

**Page 1 — Summary (Image #2):**
- Header: LMU logo, `Pitcher name`, `Pitching practice · <date>`, session total
  pitch count, white lion (mirror the one-pager header).
- **Avg velocity by pitch type** — horizontal strip/dot plot per pitch type
  (mph), matching the Trackman "Avg. velocity by pitch type" panel.
- **Pitches** — count per pitch type (a colored usage bar or small legend with
  totals + `Total: N`).
- **Movement** — HB (x) vs IVB (y) scatter, colored by pitch type (reuse the
  movement-map style from `plots.movement_map_uri`).
- **Release** — RelSide (x) vs RelHeight (y) scatter, colored by pitch type.
- **Location** — PlateLocSide vs PlateLocHeight scatter over a strike-zone box
  (reuse `plots` zone drawing).
- **Stats by pitch type** table — per `TaggedPitchType`: Qty, Pitch Speed
  min/max/avg, Total spin min/max/avg, IVB, HB avg (+max abs), Vert Mov, Rel
  height/side avg, Extension avg. Pitch-type names colored via
  `plots.color_for`.

**Page 2 — Pitches in session (Image #3):**
- One row per pitch (ordered by `PitchNo`): Pitch no. (colored dot by type),
  Pitch Speed, Total spin, Tilt, Ind. Vert Mov, Horz Mov, Extension, Release
  Height, Release Side, Spin efficiency %. A pitch-type color key at the top.

Two pages = one PDF (CSS `page-break-before` between the two `.pg` blocks, same
Letter sizing as the one-pager).

## Data layer — `app/data/bullpen.py`

- `lmu_bullpen_pitchers() -> DataFrame[PitcherId, Pitcher, player_id?]` — distinct
  LMU pitchers present in BULLPEN, newest-session first; alias-resolved name where
  possible.
- `sessions_for(pitcher_trackman_id) -> DataFrame[date, pitch_count, session_label]`
  — that pitcher's bullpen dates, newest first.
- `session_pitches(pitcher_trackman_id, date) -> DataFrame` — the per-pitch rows
  for one session (Page 2 source + Page 1 aggregates).
- `summary_by_pitch_type(df) -> list[dict]` — the Stats-by-pitch-type aggregates.
- `bullpen_data_max_date() -> date` — for the "data through" note.
- Column-name normalization: BULLPEN uses Trackman PascalCase; map to
  snake_case internally or read PascalCase directly (keep it isolated to this
  module).

## Delivery — routes + landing page

Mirror `app/reports/routes.py` + `templates/reports/pitching_landing.html`:

- `GET /reports/bullpen` — landing page: pitcher dropdown → session dropdown
  (dates) → "Download Report" (+ optional "Download All sessions" later). Shows
  the "data through <date>" banner. LMU-branded (base.html tokens).
- `GET /reports/bullpen/<pitcher_trackman_id>/<date>.pdf` — builds + streams the
  two-page PDF (`Content-Disposition: attachment`, `target=_blank`), reusing the
  disk cache pattern (`instance/report_cache/`, key includes pitcher+date+data
  version).
- Access gate: login required; coach = all LMU pitchers; player = self only
  (map `current_user.trackman_id` to the bullpen PitcherId via the alias, same
  self-only pattern as the pitcher report).
- Add a **Bullpen Reports** card to the pitching hub
  (`templates/main/pitching_hub.html`) next to Postgame Reports.

## Assembler — `app/reports/bullpen_report.py`

`build_bullpen_report(pitcher_trackman_id, date) -> bytes` mirroring
`build_pitcher_postgame`: load session data, build matplotlib chart URIs
(velo strip, movement, release, location) + tables, render the Jinja template,
`html_to_pdf`, cache. `ReportDataError` when the session is empty / not LMU /
not viewable.

## Testing

- `test_bullpen_data.py` (live DB): `lmu_bullpen_pitchers` non-empty + Geis
  present; `sessions_for(824645)` returns dated sessions; `session_pitches`
  returns per-pitch rows with the needed columns; `summary_by_pitch_type` shape.
- `test_bullpen_report.py`: `build_bullpen_report` for a Geis session returns
  valid PDF bytes (%PDF header); empty/non-LMU raises `ReportDataError`.
- `test_bullpen_landing.py`: `/reports/bullpen` 200 for coach; player self-only
  gate (403 on another pitcher); the "data through" banner renders.

## Provisional / coach-confirmable

- LMU team codes (`LOY_MAR` + `LOY_LIO`); session grouping (Live vs Warmup);
  which exact aggregate columns appear in the Stats-by-pitch-type table (match
  the Trackman sample as closely as the data allows).

## Out of scope

- The **SFTP pull + BULLPEN repopulation loader** (separate data task; the report
  is built to consume the table whenever it is refreshed).
- Game/postgame report changes (SP3), dashboard work (SP1/SP2), scheduling (SP5).
