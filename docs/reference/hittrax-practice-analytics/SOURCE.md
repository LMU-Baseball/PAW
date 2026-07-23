# HitTrax Practice Analytics — reference snapshot

**Upstream:** https://github.com/BRADhaskell/lmu-baseball-practice-analytics  
**Captured:** 2026-07-23 into PAW so the upstream repo can return to private.

## What was ported into PAW
- UI tabs from `dashboard/app.py` → `app/dashboards/hitting_practice/`
- Loaders/metrics → `app/data/practice.py`
- Design: `docs/superpowers/specs/2026-07-23-hitting-practice-dashboard-design.md`

## Files kept here for offline reference
| File | Why |
|------|-----|
| `transformed_schema.sql` | `practice_plays` / `practice_sessions` / `player_stats_summary` |
| `raw_schema.sql` | Raw ingest tables |
| `pipeline-architecture.md` | FTPS → ELT → MySQL flow |
| `dashboard-README.md` | Upstream dashboard notes |
| `streamlit-app-core-excerpt.py` | Constants + SQL loaders + `trim_to_first_contact` |

## Key metric rules (also in `app/data/practice.py`)
- Contact: `result != -4`
- Trim warm-ups: drop pitches before first contact per player+session
- Strike zone (ft): x ∈ [-0.708, 0.708], y ∈ [1.5, 3.5]
- Swing Decision Score: in-zone (zones 1–9) contact% − chase (10–13) contact%
- Swing Decision window: 2026-03-31 → 2026-06-01
- Heatmap bins: 20×20 over x∈[-2,2], y∈[0.5,5]
