# Design: Hitting Practice Dashboard (HitTrax) — Slice 1

**Date:** 2026-07-23
**Branch:** `cursor/hitting-practice-dashboard-1c83`
**Status:** Approved for implementation
**Source of truth:** `BRADhaskell/lmu-baseball-practice-analytics` Streamlit app
(`dashboard/app.py`)

---

## 1. Motivation

The Hitting hub already has a disabled **Practice Dashboard (HitTrax)** card. The
Streamlit practice analytics app is the coach-facing UI for HitTrax ELT tables
(`practice_plays`, `practice_sessions`, `player_stats_summary`). This slice ports
that experience into PAW as a Dash module, using the shared shell / hub pattern.

**Not** a 4th tab on the Trackman game-stats dashboard — practice uses date/session
filters (not game pickers) and different tables. Hub card → dedicated Dash app.

## 2. Goal

1. Enable Hitting hub card → `/dash/hitting-practice/`
2. Ship a Dash dashboard with the Streamlit tab set:
   - **Pitch Zones** — catcher’s-view contact heatmap
   - **Swing Frequency** — contact rate / Swing Decision Score / EV·distance by pitch
   - **Contact Overview** — team/player KPIs + hit-type mix + EV leaders
   - **Session Tables** — player summary + session log
3. Reuse PAW brand shell; keep HitTrax metric logic from `app.py`

## 3. Architecture

```
app/data/practice.py                 warehouse loaders + transforms
app/dashboards/hitting_practice/
  __init__.py                        build @ /dash/hitting-practice/
  index.py                           shell.index_string()
  layout.py                          filters + 4 tabs
  selectors.py                       role-aware player options
  callbacks.py
  charts.py                          heatmap, bars, dual-axis
  tables.py
  tabs/{pitch_zones,swing_frequency,contact_overview,session_tables}.py
```

**DB:** same analytics MySQL (`MYSQL_*`) as Trackman — HitTrax ELT writes
`practice_*` tables into the same RDS (`lmubaseball`).

**Role gating:** coach sees all players; player locked to rows whose `player_name`
fuzzy-matches `current_user.name` (best-effort; HitTrax ids ≠ Trackman ids).

## 4. Filters (selector row — mirrors Streamlit sidebar)

- Exclude test accounts (default on)
- Date quick-select: Past Week / Month / 3 Months / Year / Custom (default = Swing
  Decision window start `2026-03-31` → today when custom)
- Player dropdown (`All Players` + names)
- Session: All | Swing Decision | `{type} — {tag}` labels

## 5. Metric rules (ported)

- Contact: `result != -4` (NULL treated as contact when present)
- `trim_to_first_contact` per player+session
- In-zone geometry: px ∈ [-0.708, 0.708], py ∈ [1.5, 3.5] ft
- Swing Decision Score: in-zone (zones 1–9) contact% − chase (10–13) contact%
- Heatmap: 20×20 bins, X∈[-2,2], Y∈[0.5,5]; strike-zone rectangle overlay
- Session type map from Streamlit `SESSION_TYPE_MAP`

## 6. Deferred

- PDF / CSV download buttons
- Exact Streamlit “Show Misses” / color-metric toggles beyond Contact Rate
- Player Trackman↔HitTrax id join
- Looker Studio parity extras from prototypes app2/app3

## 7. Success

- Hub card live; coach can filter and see all four tabs
- Synthetic transform tests green; live-DB fixtures skip if tables missing
