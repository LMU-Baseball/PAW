# Competitive Cauldron — Design Spec (2026-08-10)

A daily team competition for LMU pitchers, replacing the Google-Sheet "Cauldron."
Players are drafted into teams; they earn points by clearing per-metric
thresholds; coaches see/enter data, players see a team scoreboard. Reuses the
Top Gun velo board's machine (coach-edit grid + player visual + RDS storage +
role gate) with three new pieces: **teams**, **fixed threshold scoring**, and
**draft cycles**.

## Decisions locked (user, 2026-08-10)

- **Auto-score derivable metrics from Trackman** via the coach's thresholds +
  fixed point values; coaches enter only the subjective columns and can override.
- **Scoring is FIXED per metric:** clear threshold → `+points_met`; miss →
  `+points_missed` (negative). One pair per metric (not graduated).
- **Fall/preseason data:** auto-score from any Trackman-logged game data
  (including intrasquad/scrimmages that land in `GAMES`); when a day has no game
  data, coaches enter manually.
- **Manual columns:** Mod Command, Recovery Command, AH/Rehab. Everything else
  auto: Strike%, First-Pitch Strike, Early-&-Ahead, Pre-2K zone, 2K-Kill, K%,
  BB%, Off-Speed zone, count work (2/3, 1-1), Barrel.
- **Paw-only** (no Google Chat push). **Coaches assign teams manually** (no
  live-draft tool). Coach edits / player views; storage = new RDS tables.

## Non-goals

Velo board and Performance Council (separate specs). No Google Chat. No
automated snake-draft tool. No change to existing dashboards/reports.

---

## Data model — three new RDS tables (mirror `precalc.py` DDL + `velo_board.py`)

- **`cauldron_scoring`** — the rules config (coach-editable), one row per metric:
  `metric VARCHAR(32) PK, label VARCHAR(48), threshold FLOAT, direction ENUM('gte','lte'), points_met INT, points_missed INT, is_manual BOOL, min_sample INT, sort_order INT`.
  Seeded from the sheet's headers (thresholds) with placeholder points the coach
  edits. `direction` handles "higher is better" (Strike% gte 55) vs "lower is
  better" (BB% lte 6, Barrel lte X). `is_manual` marks the coach-judgment rows.
  `min_sample` suppresses scoring on too-few pitches/batters that day.
- **`cauldron_teams`** — `(player_id BIGINT, cycle_id VARCHAR(24), team VARCHAR(24), PK(player_id, cycle_id))`. Coach assigns each player a team per cycle. A cycle is a ~5-week block (id e.g. "2026-fall-c1"); new cycle = fresh assignments, totals reset, past cycles preserved.
- **`cauldron_daily`** — `(player_id BIGINT, play_date VARCHAR(10), metric VARCHAR(32), raw_value FLOAT, points INT, source ENUM('auto','manual'), updated_by INT, updated_at DATETIME, PK(player_id, play_date, metric))`. One row per player × day × metric. Upsert (`ON DUPLICATE KEY UPDATE`) so re-runs/overrides replace in place.

## Auto-scoring engine (`app/data/cauldron.py`)

`score_day(play_date) -> None` (and an on-demand `compute_player_day(pid, date)`):
1. For each rostered pitcher with `GAMES` pitch data on `play_date`, compute each
   auto metric's raw value from the pitch rows.
2. Look up `cauldron_scoring[metric]`; if `raw_value` meets `direction`/`threshold`
   and `pitch/batter count >= min_sample`, award `points_met`, else `points_missed`
   (skip entirely when below `min_sample`).
3. Upsert into `cauldron_daily` with `source='auto'` — but NEVER overwrite a row a
   coach set to `source='manual'` (coach override wins).
- Days with no game data for a pitcher → no auto rows; coach enters manually.
- Manual metrics (`is_manual`) are always coach-entered, never auto.

**Metric definitions.** Standard metrics compute from `GAMES` pitch data on
well-known definitions: Strike% (strikes/pitches via `PitchCall`), First-Pitch
Strike (strike on pitch 1 of PA), K% / BB% (per batter faced via `KorBB`),
Off-Speed zone% (in-zone rate on off-speed types), Barrel (barrels allowed rate
via exit velo/angle). The **non-standard** metrics — Early-&-Ahead, Pre-2K zone,
2K-Kill, count work (2/3, 1-1) — have coach-specific definitions that MUST be
confirmed with the coach/analyst before implementation; each becomes one
`compute_<metric>()` helper. Until confirmed, they are config-present but
computed as TODO-flagged stubs so the rest of the board ships.

## Coach view — team assignment + daily grid

- Coach-only (double-gated: grid hidden from players AND save callback re-checks
  `is_coach`, exactly as the velo board).
- **Team assignment:** a small control per player (dropdown Team 1..N) for the
  selected cycle, saved to `cauldron_teams`.
- **Daily grid:** Date + Cycle selectors; an editable `dash_table.DataTable`, one
  row per rostered pitcher, columns = the metrics. Auto cells pre-filled from
  `cauldron_daily` (computed on demand if missing), coach can override (sets
  `source='manual'`); manual columns open. A per-player **Total** and running
  cycle total. **Save** upserts the day into `cauldron_daily`.
- A "Recompute auto from Trackman" action re-runs `score_day` for the date
  (without clobbering manual overrides).

## Player view — Cauldron scoreboard

- Read-only, LMU-branded "Competitive Cauldron" header. Rows grouped by **team**
  (team header rows, players beneath), point cells green (met) / red (missed) per
  the sheet, per-player **Total**, and **team totals**, for the current cycle.
  Season + Cycle context shown (like the sheet's "2026 / Spring / Week").

## Access, storage, routing

- Reuse `app/auth/access.py` + `current_user.is_coach`; writes require coach and
  the save callback re-checks server-side. Reads (scoreboard) for any
  authenticated user.
- Storage in the existing RDS via `app.db.get_engine`/`query_df`; DDL via an
  `ensure_tables()` mirroring `velo_board.py`/`precalc.py`.
- New Dash dashboard `app/dashboards/cauldron/` at `/dash/cauldron/`, registered
  in `app/dashboards/__init__.py`, linked from the Pitching hub
  (`pitching_hub.html`).

## Coach-provided config still needed (populate `cauldron_scoring`)

For each metric: exact `threshold`, `direction`, `points_met`, `points_missed`,
`min_sample`, and — for Early-&-Ahead / Pre-2K zone / 2K-Kill / count work — the
precise computation formula. The velo board's placeholder-then-edit pattern
applies: seed sensible values, coach tunes in the grid.

## Testing

- Data layer (TDD): each standard auto metric computes correctly from a fixture
  pitch set; `score_day` awards `points_met`/`points_missed` per config and
  respects `min_sample`; coach `manual` rows are never overwritten by re-score;
  `cauldron_teams` assignment + cycle reset; team-total aggregation.
- Auth: coach can write teams + daily; player cannot (route + callback re-check).
- Render smoke: coach grid (editable, team dropdowns) for coach; player
  scoreboard grouped by team with totals; player never sees the grid.
- No Chat / no auto-draft anything.

## Rollout

Ship with the standard auto metrics + manual columns + team scoreboard; wire the
non-standard metric formulas once the coach confirms their definitions; tune
`cauldron_scoring` point values in-app.
