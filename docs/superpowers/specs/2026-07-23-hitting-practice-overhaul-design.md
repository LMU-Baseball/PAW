# Design: Hitting-Practice (HitTrax) Dashboard Overhaul (Sub-project C)

**Date:** 2026-07-23
**Branch:** `feat/hitting-practice-overhaul` (off `feat/catching-enhancements` — sub-project A; last in the stack)
**Status:** Approved for implementation (user, 2026-07-23)
**Part of:** the 3-sub-project enhancement set (B done, A done → **C (this)**).

---

## 1. Motivation

Coach feedback on the HitTrax practice dashboard (from screenshots):
- Too much white space; no player identity like the other dashboards.
- The Pitch Zones strike-zone box is white → invisible; only contact% is available (want EV and distance too).
- Swing Frequency / Swing Decision numbers should live in a sidebar; the tab should lead with a swing-decision **trend**; the EV/distance chart needs a **zone selector**.
- Contact Overview isn't useful; replace it with a **spray chart** + a **contact-type bar**.

## 2. Goals

1. Left **sidebar** with player photo + name + the Swing Frequency and Swing Decision Score tiles.
2. Pitch Zones: **black** strike-zone box + a **metric toggle** (Contact % / Avg EV / Avg Distance) recoloring the heatmap.
3. Swing Frequency tab: lead with a **swing-decision-score trend** (per session/date), then the EV/Distance chart with a **multi-zone chip selector**.
4. Replace Contact Overview with a **spray chart** + a **contact-type descending bar** (rename tab "Batted Ball").

## 3. Confirmed decisions (brainstorming)

- **Spray chart** = Plotly-drawn field (foul lines + outfield arc + infield diamond) with batted-ball landing points colored by hit type. **No sector shading/percentages.** No background image (none exists).
- **Sidebar for "All Players"** = lion placeholder image + "All Players" + **team-aggregate** Swing/SDS tiles. Sidebar is always present.
- Metric toggle values: **Contact %, Avg EV, Avg Distance**.
- Zone selector = chips for the zones present (1–13), all active by default, filtering the EV/Distance chart only.

## 4. Non-goals / Deferred

- Diamond-Charts-style spray sectors/percentages.
- CSV/PDF export; "Show Misses" toggle (still deferred).
- Trackman↔HitTrax id join (photo match is best-effort by name; lion fallback).
- Session Tables tab unchanged.

## 5. Data availability (verified)

`practice_plays` (17,978 rows, all populated): `horizontal_angle` (spray dir, neg=left), `distance_feet`, `exit_velocity`, `hit_type` (0 none/miss, 1 GB, 2 LD, 3 FB), `result`, `zone_section` (1–13). `player_stats_summary`/`practice_sessions` carry per-player rollups. `instance/roster_media.json` entries include `name` (41 entries) → name-based photo match feasible.

## 6. Architecture / components

In-place within `app/dashboards/hitting_practice/` + `app/data/{practice.py,roster_media.py}`.

### 6a. Data layer
- **`roster_media.player_media_by_name(name) -> {'jersey','photo_url'}`** (NEW): normalize `name` via the existing `_norm_name`, match against roster entries' `name` (with the `_name_parts` last+first-initial fallback); blanks when unmatched. Reuses the module's matchers; no new scrape.
- **`practice.load_plays`**: add `horizontal_angle` to the SELECT (needed for spray). Backward-compatible (extra column).
- **`practice.swing_decision_trend(pitch_df) -> pd.DataFrame[play_date, in_zone_pct, chase_pct, score]`** (NEW): group the filtered pitch-coord df by `play_date`; per date compute `swing_decision_score` (in-zone 1–9 contact% − chase 10–13 contact%) reusing the existing logic; only dates with data; sorted. PROVISIONAL, docstring'd.
- **`practice.heatmap_metric(df, metric)`** (NEW, generalizes `heatmap_contact_rate`): `metric ∈ {"contact","ev","distance"}` → returns `(z, xedges, yedges)` where z is per-bin mean of contact% / exit_velocity / distance_feet. Keep `heatmap_contact_rate` as `heatmap_metric(df,"contact")` (or thin wrapper) so existing callers/tests stand.
- **`practice.spray_points(plays_df) -> pd.DataFrame[x, y, hit_type_label]`** (NEW): from `horizontal_angle`+`distance_feet`: `x = distance*sin(radians(angle))`, `y = distance*cos(radians(angle))`; label via `HIT_TYPE_MAP`. **Batted balls only** — keep `hit_type ∈ {1,2,3}` (Ground/Line/Fly); drop misses/fouls (hit_type 0/None) and rows missing angle/distance. Provisional.

### 6b. Charts (`app/dashboards/hitting_practice/charts.py`)
- `pitch_zone_heatmap(df, metric="contact")`: strike-zone box line **`color="black"`**; colorbar title + colorscale per metric (contact% 0–100 YlOrRd; EV/distance sequential with data-driven range); title reflects the metric.
- `swing_decision_trend_fig(trend_df)` (NEW): line+markers of `score` over `play_date` (crimson), zero baseline; Teko; transparent paper/near-white plot. Empty/one-point safe.
- `spray_chart_fig(spray_df)` (NEW): field outline via Plotly shapes (two foul lines from origin, an outfield arc, infield diamond), equal aspect (`scaleanchor`), landing points colored by hit type (GB/LD/FB via a fixed color map). Empty-safe (draws the field).
- `contact_type_bar(counts_df)` (NEW, replaces `hit_type_donut`): **vertical bar sorted descending by count**; categories Miss/Foul, Ground Ball, Line Drive, Fly Ball (crimson bars). (Unlike the spray chart, the bar includes Miss/Foul so it accounts for all plays.)
- `ev_distance_by_pitch(df)`: unchanged chart, but now receives a zone-filtered df from the callback.

### 6c. Layout (`layout.py`)
- Wrap the page in a flex: left **`html.Div(id="prac-sidebar")`** (photo + name + Swing Freq tiles + Swing Decision Score tiles), right = the existing filters + tabs + `prac-tab-content`.
- Pitch Zones tab: add a **metric toggle** (`dcc.RadioItems` id `pz-metric`, options Contact %/Avg EV/Avg Distance, default Contact %).
- Swing Frequency tab: **remove** the Swing Freq + Swing Decision Score tiles (moved to sidebar); content = swing-decision trend graph, then a **zone chip row** (id prefix `sfz`) + the EV/Distance graph (`sf-ev-body`).
- Rename the **Contact Overview** tab → **Batted Ball** (tab `value="batted"`); content = spray chart + contact-type bar.
- Session Tables tab unchanged.

### 6d. Callbacks (`callbacks.py`)
- **`prac-sidebar`** callback: Input `prac-filters` (+ player) → load that player's filtered plays/pitch df → render photo (via `player_media_by_name`, lion placeholder for All Players/unmatched) + name + Swing Freq tiles (`contact_summary`) + Swing Decision tiles (`swing_decision_score`). Team-aggregate when player == "All Players".
- **`pz-metric`** → re-render the Pitch Zones heatmap with the chosen metric (Input pz-metric + pitch-data).
- **Zone chips** (`sfz-*`): toggle store + style callbacks mirroring the pitching chip pattern; a body callback filters the EV/Distance df to selected `zone_section` and re-renders `sf-ev-body`.
- **Batted Ball render**: from the filtered plays df → `spray_chart_fig(spray_points(plays))` + `contact_type_bar(hit_type_counts(plays))`.
- `_render` routing updated for the renamed tab; the removed Contact Overview leaders/KPIs deleted.

## 7. Testing

- `roster_media`: `player_media_by_name` matches a known roster name; unmatched → blanks.
- `practice`: `swing_decision_trend` on a synthetic multi-date df (per-date score); `heatmap_metric` returns EV/distance grids (mean per bin); `spray_points` maps angle/distance → x/y with correct sign (negative angle → negative x = left field); `load_plays` includes `horizontal_angle` (live-DB).
- `charts`: `swing_decision_trend_fig`, `spray_chart_fig`, `contact_type_bar` build on empty + populated; `pitch_zone_heatmap(df,"ev")` builds and the zone box line color is black.
- dash: sidebar renders for a player and for "All Players"; Batted Ball tab has 2 graphs; zone chips present; metric toggle present. Live-DB smoke per existing convention.
- Full suite green.

## 8. Success criteria

- Sidebar shows photo+name (or lion + "All Players") with Swing Freq + Swing Decision tiles.
- Pitch Zones: black zone box; toggling Contact/EV/Distance recolors the heatmap.
- Swing Frequency tab leads with the swing-decision trend; EV/Distance chart filters by the zone chips.
- Batted Ball tab shows a proportionate spray chart (points colored by hit type) + a descending contact-type bar; Contact Overview is gone.
- Full suite green; date-range + other tabs unaffected.

## 9. Branch / sequencing

Base `feat/catching-enhancements` (A). New branch `feat/hitting-practice-overhaul`. Final in the stack; after it, merge the whole chain (rebuild → B → A → C) in order.
