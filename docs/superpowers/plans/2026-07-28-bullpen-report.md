# Bullpen Report Page Implementation Plan (SP4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A standalone LMU-branded bullpen report (2 pages: summary + per-pitch detail) with a `/reports/bullpen` landing page, generated from the `BULLPEN` table.

**Architecture:** New `app/data/bullpen.py` (reads `BULLPEN`, normalizes Trackman PascalCase → snake_case, resolves LMU pitchers/sessions). New `app/reports/bullpen_report.py` assembler + `bullpen_report.html` template + `bullpen_plots.py` matplotlib charts. New routes on the existing `reports` blueprint + a hub card. Reuses the report engine (`pdf.html_to_pdf`, `plots._fig_to_uri`/`_color_for`, `_inline_fonts`, `_data_uri`).

**Tech Stack:** Flask blueprint, Jinja2, matplotlib (Agg), Playwright (via html_to_pdf), pandas, pytest.

## Global Constraints

- LMU scope: `PitcherTeam IN ('LOY_MAR','LOY_LIO')` (both LMU; confirmed live 2026-07-28). PROVISIONAL constant `LMU_BULLPEN_TEAMS`.
- `BULLPEN` is stale (ends 2025-04-14; feed dead, repopulated later from SFTP). The report reads the table directly — no report change needed when it is refreshed. Landing page shows a "Data through <max date>" banner.
- Pitcher identity key throughout = raw Trackman `PitcherId` (e.g. Geis 824645). Player self-only gate maps via `str(user.trackman_id) == str(pitcher_trackman_id)` OR sibling match through the warehouse (see Task 3).
- Normalize columns in the data layer only; the rest of the code sees snake_case.
- Run: `python -m pytest -q`. Commit per task. No `git stash/reset/checkout/clean`. Clear `instance/report_cache/` is not needed (bullpen cache key includes the session date + data max-date).

## File structure

- Create `app/data/bullpen.py` — data access + transforms.
- Create `app/reports/bullpen_plots.py` — velo-strip, movement, release, location matplotlib builders (bullpen-specific; snake_case columns).
- Create `app/reports/bullpen_report.py` — `build_bullpen_report(pitcher_trackman_id, date) -> bytes` + `_build_html` + cache.
- Create `app/reports/templates/bullpen_report.html` — 2-page Jinja template.
- Modify `app/reports/static/report.css` — bullpen page styles + `page-break`.
- Modify `app/reports/routes.py` — `/reports/bullpen` landing + `/reports/bullpen/<pid>/<date>.pdf`.
- Modify `app/auth/access.py` — `can_view_bullpen(user, pitcher_trackman_id)`.
- Create `app/templates/reports/bullpen_landing.html` — picker UI.
- Modify `app/templates/main/pitching_hub.html` — add a "Bullpen Reports" card.
- Tests: `tests/test_bullpen_data.py`, `tests/test_bullpen_report.py`, `tests/test_bullpen_landing.py`.

---

### Task 1: Data layer `app/data/bullpen.py`

**Files:**
- Create: `app/data/bullpen.py`
- Test: `tests/test_bullpen_data.py`

**Interfaces:**
- Produces:
  - `LMU_BULLPEN_TEAMS = ("LOY_MAR", "LOY_LIO")`
  - `lmu_bullpen_pitchers() -> pd.DataFrame` cols `pitcher_id`(raw Trackman, int), `pitcher`(name), `sessions`(int), newest-first.
  - `sessions_for(pitcher_trackman_id) -> pd.DataFrame` cols `date`(str YYYY-MM-DD), `pitches`(int), newest first.
  - `session_pitches(pitcher_trackman_id, date) -> pd.DataFrame` normalized snake_case cols: `pitch_no, tagged_pitch_type, rel_speed, spin_rate, spin_eff, tilt, ind_vert_break, horz_break, vert_break, rel_height, rel_side, extension, plate_loc_side, plate_loc_height` (ordered by pitch_no).
  - `summary_by_pitch_type(df) -> list[dict]` per type: `pitch, qty, velo_min, velo_max, velo_avg, spin_min, spin_max, spin_avg, ivb_avg, hb_avg, vert_avg, rel_h_avg, rel_side_avg, ext_avg` (rounded 1dp; None-safe).
  - `bullpen_data_max_date() -> str | None`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_bullpen_data.py`:
```python
from app.data import bullpen as B

GEIS = 824645  # raw Trackman PitcherId for Jake Geis in BULLPEN


def test_lmu_pitchers_include_geis():
    p = B.lmu_bullpen_pitchers()
    assert not p.empty
    assert GEIS in set(int(x) for x in p["pitcher_id"])
    assert {"pitcher_id", "pitcher", "sessions"} <= set(p.columns)


def test_sessions_and_pitches_for_geis():
    s = B.sessions_for(GEIS)
    assert not s.empty and {"date", "pitches"} <= set(s.columns)
    date = s.iloc[0]["date"]
    d = B.session_pitches(GEIS, date)
    assert not d.empty
    for col in ("pitch_no", "tagged_pitch_type", "rel_speed", "spin_rate",
                "tilt", "ind_vert_break", "horz_break", "rel_height",
                "rel_side", "extension", "plate_loc_side", "plate_loc_height"):
        assert col in d.columns


def test_summary_by_pitch_type_shape():
    s = B.sessions_for(GEIS)
    d = B.session_pitches(GEIS, s.iloc[0]["date"])
    rows = B.summary_by_pitch_type(d)
    assert rows and {"pitch", "qty", "velo_avg", "spin_avg"} <= set(rows[0])
    assert sum(r["qty"] for r in rows) == len(d)


def test_max_date_is_stale_2025():
    assert str(B.bullpen_data_max_date()).startswith("2025")
```

- [ ] **Step 2: Run to verify fail** — `python -m pytest tests/test_bullpen_data.py -q` → FAIL (module missing).

- [ ] **Step 3: Implement `app/data/bullpen.py`**

```python
"""Bullpen (Trackman pitching-practice) data access + transforms.

Source = the legacy `BULLPEN` table (raw Trackman practice export, PascalCase
columns). Stale (ends 2025-04-14; feed dead) — repopulated later from an SFTP
drop; this module reads whatever the table currently holds. LMU-only.
"""
from __future__ import annotations

import pandas as pd

from app.db import query_df

LMU_BULLPEN_TEAMS = ("LOY_MAR", "LOY_LIO")

# BULLPEN PascalCase -> our snake_case.
_COLMAP = {
    "PitchNo": "pitch_no", "TaggedPitchType": "tagged_pitch_type",
    "RelSpeed": "rel_speed", "SpinRate": "spin_rate",
    "SpinAxis3dSpinEfficiency": "spin_eff", "Tilt": "tilt",
    "InducedVertBreak": "ind_vert_break", "HorzBreak": "horz_break",
    "VertBreak": "vert_break", "RelHeight": "rel_height", "RelSide": "rel_side",
    "Extension": "extension", "PlateLocSide": "plate_loc_side",
    "PlateLocHeight": "plate_loc_height",
}


def _teams_clause(prefix=""):
    marks = ", ".join(f":t{i}" for i in range(len(LMU_BULLPEN_TEAMS)))
    params = {f"t{i}": v for i, v in enumerate(LMU_BULLPEN_TEAMS)}
    return f"{prefix}PitcherTeam IN ({marks})", params


def lmu_bullpen_pitchers() -> pd.DataFrame:
    clause, params = _teams_clause()
    return query_df(
        f"""
        SELECT PitcherId AS pitcher_id, MAX(Pitcher) AS pitcher,
               COUNT(DISTINCT Date) AS sessions, MAX(Date) AS last_date
          FROM BULLPEN
         WHERE {clause} AND PitcherId IS NOT NULL
         GROUP BY PitcherId
         ORDER BY last_date DESC, pitcher
        """,
        params,
    )


def sessions_for(pitcher_trackman_id: int) -> pd.DataFrame:
    df = query_df(
        """
        SELECT DATE(Date) AS date, COUNT(*) AS pitches
          FROM BULLPEN
         WHERE PitcherId = :pid
         GROUP BY DATE(Date)
         ORDER BY date DESC
        """,
        {"pid": int(pitcher_trackman_id)},
    )
    if not df.empty:
        df["date"] = df["date"].astype(str)
    return df


def session_pitches(pitcher_trackman_id: int, date) -> pd.DataFrame:
    df = query_df(
        """
        SELECT * FROM BULLPEN
         WHERE PitcherId = :pid AND DATE(Date) = :d
         ORDER BY PitchNo
        """,
        {"pid": int(pitcher_trackman_id), "d": str(date)},
    )
    if df.empty:
        return pd.DataFrame(columns=list(_COLMAP.values()))
    keep = {k: v for k, v in _COLMAP.items() if k in df.columns}
    out = df[list(keep)].rename(columns=keep)
    return out.reset_index(drop=True)


def _r1(x):
    return None if x is None or pd.isna(x) else round(float(x), 1)


def summary_by_pitch_type(df: pd.DataFrame) -> list[dict]:
    if df is None or df.empty:
        return []
    rows = []
    for pt, sub in df.groupby("tagged_pitch_type"):
        rows.append({
            "pitch": pt, "qty": int(len(sub)),
            "velo_min": _r1(sub["rel_speed"].min()),
            "velo_max": _r1(sub["rel_speed"].max()),
            "velo_avg": _r1(sub["rel_speed"].mean()),
            "spin_min": _r1(sub["spin_rate"].min()),
            "spin_max": _r1(sub["spin_rate"].max()),
            "spin_avg": _r1(sub["spin_rate"].mean()),
            "ivb_avg": _r1(sub["ind_vert_break"].mean()),
            "hb_avg": _r1(sub["horz_break"].mean()),
            "vert_avg": _r1(sub["vert_break"].mean()),
            "rel_h_avg": _r1(sub["rel_height"].mean()),
            "rel_side_avg": _r1(sub["rel_side"].mean()),
            "ext_avg": _r1(sub["extension"].mean()),
            "_c": len(sub),
        })
    rows.sort(key=lambda r: r["_c"], reverse=True)
    for r in rows:
        del r["_c"]
    return rows


def bullpen_data_max_date():
    df = query_df("SELECT MAX(DATE(Date)) AS d FROM BULLPEN")
    v = df.iloc[0]["d"] if not df.empty else None
    return None if v is None or pd.isna(v) else str(v)
```

- [ ] **Step 4: Run to verify pass** — `python -m pytest tests/test_bullpen_data.py -q` → PASS.

- [ ] **Step 5: Commit** — `git add app/data/bullpen.py tests/test_bullpen_data.py && git commit -m "feat(bullpen): data layer over BULLPEN table (LMU pitchers/sessions/summary)"`

---

### Task 2: Charts + report assembler + template

**Files:**
- Create: `app/reports/bullpen_plots.py`, `app/reports/bullpen_report.py`, `app/reports/templates/bullpen_report.html`
- Modify: `app/reports/static/report.css`
- Test: `tests/test_bullpen_report.py`

**Interfaces:**
- Consumes: `app.data.bullpen` (Task 1), `app.reports.plots` (`_fig_to_uri`, `_color_for`, `_draw_zone`), `app.reports.pdf.html_to_pdf`, `app.reports.pitcher_postgame` (`_inline_fonts`, `_data_uri`, `ReportDataError`, `_ASSETS_DIR`, `_STATIC`).
- Produces:
  - `bullpen_plots.velo_strip_uri(df)`, `movement_uri(df)`, `release_uri(df)`, `location_uri(df)` → PNG data URIs (color = pitch type).
  - `bullpen_report.build_bullpen_report(pitcher_trackman_id, date) -> bytes`; `ReportDataError` re-exported.

- [ ] **Step 1: Write failing tests**

Create `tests/test_bullpen_report.py`:
```python
import pytest
from app.data import bullpen as B
from app.reports import bullpen_plots as BP
from app.reports.bullpen_report import build_bullpen_report, ReportDataError

GEIS = 824645


def _session():
    s = B.sessions_for(GEIS)
    return GEIS, s.iloc[0]["date"]


def test_bullpen_charts_return_png():
    pid, date = _session()
    df = B.session_pitches(pid, date)
    for fn in (BP.velo_strip_uri, BP.movement_uri, BP.release_uri, BP.location_uri):
        assert fn(df).startswith("data:image/png;base64,")


def test_build_bullpen_report_valid_pdf():
    pid, date = _session()
    pdf = build_bullpen_report(pid, date)
    assert pdf[:5] == b"%PDF-" and len(pdf) > 5000


def test_build_raises_on_empty_session():
    with pytest.raises(ReportDataError):
        build_bullpen_report(GEIS, "1999-01-01")
```

- [ ] **Step 2: Run to verify fail** — modules missing.

- [ ] **Step 3: Implement `app/reports/bullpen_plots.py`**

```python
"""matplotlib chart builders for the bullpen report (snake_case bullpen cols)."""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from app.reports.plots import _fig_to_uri, _color_for, _draw_zone


def _by_type(df):
    return [(pt, sub) for pt, sub in df.groupby("tagged_pitch_type")]


def velo_strip_uri(df) -> str:
    fig, ax = plt.subplots(figsize=(3.4, 3.5))
    types = list(df.groupby("tagged_pitch_type").groups)
    for i, (pt, sub) in enumerate(_by_type(df)):
        y = len(types) - i
        ax.scatter(sub["rel_speed"], [y] * len(sub), s=40,
                   color=_color_for(pt), alpha=0.8, edgecolor="white", linewidth=0.4)
        m = sub["rel_speed"].mean()
        ax.annotate(f"{m:.0f}", (m, y + 0.18), ha="center", fontsize=8, color="#222")
    ax.set_yticks(range(1, len(types) + 1))
    ax.set_yticklabels(list(reversed(types)), fontsize=8)
    ax.set_xlabel("mph", fontsize=8)
    ax.set_title("Avg. velocity by pitch type", fontsize=11, color="#9A0021", fontweight="bold")
    ax.grid(axis="x", color="#eee")
    return _fig_to_uri(fig)


def movement_uri(df) -> str:
    fig, ax = plt.subplots(figsize=(3.4, 3.5))
    ax.axhline(0, color="#ccc", lw=0.8); ax.axvline(0, color="#ccc", lw=0.8)
    for pt, sub in _by_type(df):
        ax.scatter(sub["horz_break"], sub["ind_vert_break"], s=55,
                   color=_color_for(pt), alpha=0.8, edgecolor="white", linewidth=0.5)
    ax.set_aspect("equal"); ax.set_xlabel("HB (in)", fontsize=8); ax.set_ylabel("IVB (in)", fontsize=8)
    ax.set_title("Movement", fontsize=11, color="#9A0021", fontweight="bold")
    return _fig_to_uri(fig)


def release_uri(df) -> str:
    fig, ax = plt.subplots(figsize=(3.4, 3.5))
    for pt, sub in _by_type(df):
        ax.scatter(sub["rel_side"], sub["rel_height"], s=55,
                   color=_color_for(pt), alpha=0.8, edgecolor="white", linewidth=0.5)
    ax.set_xlabel("Rel side (ft)", fontsize=8); ax.set_ylabel("Rel height (ft)", fontsize=8)
    ax.set_title("Release", fontsize=11, color="#9A0021", fontweight="bold")
    return _fig_to_uri(fig)


def location_uri(df) -> str:
    fig, ax = plt.subplots(figsize=(3.1, 3.5))
    _draw_zone(ax)
    for pt, sub in _by_type(df):
        ax.scatter(sub["plate_loc_side"], sub["plate_loc_height"], s=46,
                   color=_color_for(pt), alpha=0.9, edgecolor="white", linewidth=0.5, zorder=3)
    ax.set_xlim(-2.5, 2.5); ax.set_ylim(0, 5); ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    ax.set_title("Location", fontsize=11, color="#9A0021", fontweight="bold")
    return _fig_to_uri(fig)
```
(All are empty-safe: `groupby` over an empty df yields no groups, and `_draw_zone` still draws the box.)

- [ ] **Step 4: Implement `app/reports/bullpen_report.py`**

```python
"""Assemble the LMU bullpen report PDF (2 pages) from BULLPEN data."""
from __future__ import annotations

import os
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.data import bullpen as B
from app.reports import bullpen_plots as BP
from app.reports import plots
from app.reports.pdf import html_to_pdf
from app.reports.pitcher_postgame import (ReportDataError, _inline_fonts,
                                          _data_uri, _ASSETS_DIR)

_DIR = Path(__file__).resolve().parent
_STATIC = _DIR / "static"
_CACHE_DIR = Path(os.environ.get(
    "PAW_REPORT_CACHE_DIR", str(_DIR.parents[1] / "instance" / "report_cache")))
_env = Environment(
    loader=FileSystemLoader(str(_DIR / "templates")),
    autoescape=select_autoescape(["html"]),
)


def _build_html(pitcher_trackman_id: int, date) -> str:
    df = B.session_pitches(pitcher_trackman_id, date)
    if df.empty:
        raise ReportDataError(
            f"No bullpen pitches for pitcher {pitcher_trackman_id} on {date}")
    pit = B.lmu_bullpen_pitchers()
    row = pit[pit["pitcher_id"] == int(pitcher_trackman_id)]
    name = str(row.iloc[0]["pitcher"]) if not row.empty else str(pitcher_trackman_id)

    summary = B.summary_by_pitch_type(df)
    pitch_colors = {r["pitch"]: plots.color_for(r["pitch"]) for r in summary}
    charts = {
        "velo": BP.velo_strip_uri(df), "movement": BP.movement_uri(df),
        "release": BP.release_uri(df), "location": BP.location_uri(df),
    }
    css = _inline_fonts((_STATIC / "report.css").read_text(encoding="utf-8"))
    assets = {"lmu_png": _data_uri(_ASSETS_DIR / "lmu.png", "image/png"),
              "lion_png": _data_uri(_ASSETS_DIR / "lion-white.png", "image/png")}
    return _env.get_template("bullpen_report.html").render(
        pitcher=name, date=str(date), total=len(df),
        summary=summary, pitches=df.to_dict("records"),
        pitch_colors=pitch_colors, charts=charts, css=css, assets=assets)


def _cache_path(pid: int, date, maxd) -> Path:
    safe = re.sub(r"[^0-9A-Za-z._-]", "_", f"{pid}_{date}_{maxd}")
    return _CACHE_DIR / f"bullpen_{safe}.pdf"


def build_bullpen_report(pitcher_trackman_id: int, date) -> bytes:
    maxd = B.bullpen_data_max_date()
    cache_file = _cache_path(int(pitcher_trackman_id), date, maxd)
    if cache_file.exists():
        return cache_file.read_bytes()
    pdf = html_to_pdf(_build_html(pitcher_trackman_id, date))
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(pdf)
    except OSError:
        pass
    return pdf
```

- [ ] **Step 5: Implement `app/reports/templates/bullpen_report.html`**

```html
<!doctype html>
<html><head><meta charset="utf-8"><style>{{ css|safe }}</style></head>
<body>
<div class="pg">
  <div class="hdr">
    <img class="hdr-lmu" src="{{ assets.lmu_png }}" alt="LMU">
    <div class="hdr-id">
      <div class="hdr-name">{{ pitcher }}</div>
      <div class="hdr-game">Bullpen &nbsp;|&nbsp; {{ date }}</div>
    </div>
    <div class="hdr-line"><span><b>{{ total }}</b><i>PITCHES</i></span></div>
    <img class="hdr-lion" src="{{ assets.lion_png }}" alt="">
  </div>
  <div class="grid3">
    <div class="panel plot"><img src="{{ charts.velo }}" alt="Velocity"></div>
    <div class="panel plot"><img src="{{ charts.movement }}" alt="Movement"></div>
    <div class="panel plot"><img src="{{ charts.location }}" alt="Location"></div>
  </div>
  <div class="grid2">
    <div class="panel plot"><img src="{{ charts.release }}" alt="Release"></div>
    <div class="panel">
      <div class="panel-t">Stats by pitch type</div>
      <table>
        <tr><th class="l">Pitch</th><th>Qty</th><th>Velo (avg)</th><th>Spin (avg)</th>
            <th>IVB</th><th>HB</th><th>Ext</th></tr>
        {% for r in summary %}
        <tr><td class="l pt" style="color: {{ pitch_colors.get(r.pitch, '#111') }};">{{ r.pitch }}</td>
            <td>{{ r.qty }}</td>
            <td>{{ r.velo_avg if r.velo_avg is not none else '—' }}</td>
            <td>{{ r.spin_avg if r.spin_avg is not none else '—' }}</td>
            <td>{{ r.ivb_avg if r.ivb_avg is not none else '—' }}</td>
            <td>{{ r.hb_avg if r.hb_avg is not none else '—' }}</td>
            <td>{{ r.ext_avg if r.ext_avg is not none else '—' }}</td></tr>
        {% endfor %}
      </table>
    </div>
  </div>
</div>

<div class="pg pg-break">
  <div class="panel-t">Pitches in session</div>
  <table class="detail">
    <tr><th class="l">#</th><th>Type</th><th>Velo</th><th>Spin</th><th>Tilt</th>
        <th>IVB</th><th>HB</th><th>Ext</th><th>Rel H</th><th>Rel Side</th><th>Spin Eff</th></tr>
    {% for p in pitches %}
    <tr><td class="l">{{ p.pitch_no }}</td>
        <td class="pt" style="color: {{ pitch_colors.get(p.tagged_pitch_type, '#111') }};">{{ p.tagged_pitch_type }}</td>
        <td>{{ '%.1f'|format(p.rel_speed) if p.rel_speed is not none else '—' }}</td>
        <td>{{ '%.0f'|format(p.spin_rate) if p.spin_rate is not none else '—' }}</td>
        <td>{{ p.tilt or '—' }}</td>
        <td>{{ '%.1f'|format(p.ind_vert_break) if p.ind_vert_break is not none else '—' }}</td>
        <td>{{ '%.1f'|format(p.horz_break) if p.horz_break is not none else '—' }}</td>
        <td>{{ '%.1f'|format(p.extension) if p.extension is not none else '—' }}</td>
        <td>{{ '%.1f'|format(p.rel_height) if p.rel_height is not none else '—' }}</td>
        <td>{{ '%.1f'|format(p.rel_side) if p.rel_side is not none else '—' }}</td>
        <td>{{ '%.0f'|format(p.spin_eff) if p.spin_eff is not none else '—' }}</td></tr>
    {% endfor %}
  </table>
</div>
</body></html>
```

- [ ] **Step 6: Add bullpen CSS**

Append to `app/reports/static/report.css`:
```css
.pg-break { page-break-before: always; }
table.detail { width: 100%; border-collapse: collapse; font-size: 10px; }
table.detail th, table.detail td { padding: 2px 4px; text-align: center; border-bottom: 1px solid #eee; }
table.detail th.l, table.detail td.l { text-align: left; }
```

- [ ] **Step 7: Run tests to verify pass** — `python -m pytest tests/test_bullpen_report.py -q` → PASS (valid PDFs; empty raises).

- [ ] **Step 8: Commit** — `git add app/reports/bullpen_plots.py app/reports/bullpen_report.py app/reports/templates/bullpen_report.html app/reports/static/report.css tests/test_bullpen_report.py && git commit -m "feat(bullpen): 2-page report assembler + charts + template"`

---

### Task 3: Routes + access gate + landing page + hub card

**Files:**
- Modify: `app/auth/access.py` (`can_view_bullpen`)
- Modify: `app/reports/routes.py` (landing + pdf routes)
- Create: `app/templates/reports/bullpen_landing.html`
- Modify: `app/templates/main/pitching_hub.html` (card)
- Test: `tests/test_bullpen_landing.py`

**Interfaces:**
- Consumes: `app.data.bullpen`, `app.reports.bullpen_report`.
- Produces: `can_view_bullpen(user, pitcher_trackman_id) -> bool`; routes `reports.bullpen_landing` (`/reports/bullpen`), `reports.bullpen_pdf` (`/reports/bullpen/<int:pid>/<date>.pdf`).

- [ ] **Step 1: Write failing tests**

Create `tests/test_bullpen_landing.py` (mirror `tests/test_pitching_landing.py`'s client/login fixtures — reuse its helpers/imports):
```python
def test_bullpen_landing_ok_for_coach(coach_client):
    r = coach_client.get("/reports/bullpen")
    assert r.status_code == 200
    assert b"Bullpen" in r.data
    assert b"through" in r.data.lower() or b"Data" in r.data  # stale-data banner


def test_bullpen_pdf_player_self_only(player_client):
    # a player requesting some other pitcher's bullpen -> 403
    r = player_client.get("/reports/bullpen/999999/2025-02-06.pdf")
    assert r.status_code in (403, 404)
```
(Use whatever coach/player client fixtures `tests/test_pitching_landing.py` already defines; copy that setup.)

- [ ] **Step 2: Run to verify fail.**

- [ ] **Step 3: Add `can_view_bullpen` to `app/auth/access.py`**

```python
def can_view_bullpen(user, pitcher_trackman_id) -> bool:
    """Coaches see all bullpens; a player sees only their own (raw Trackman id)."""
    if not getattr(user, "is_authenticated", False):
        return False
    if user.role == "coach":
        return True
    return user.trackman_id is not None and str(user.trackman_id) == str(pitcher_trackman_id)
```

- [ ] **Step 4: Add routes to `app/reports/routes.py`**

```python
from app.auth.access import can_view_pitcher_report, can_view_bullpen
from app.data import bullpen as BULL
from app.reports.bullpen_report import build_bullpen_report


@report_bp.route("/bullpen")
@login_required
def bullpen_landing():
    pitchers = BULL.lmu_bullpen_pitchers()
    pid = request.args.get("pitcher_id", type=int)
    sessions = None
    selected = None
    if pid is not None:
        match = pitchers[pitchers["pitcher_id"] == pid]
        if not match.empty:
            selected = match.iloc[0].to_dict()
        sessions = BULL.sessions_for(pid).to_dict("records")
    return render_template(
        "reports/bullpen_landing.html",
        pitchers=pitchers.to_dict("records"), pitcher_id=pid,
        selected=selected, sessions=sessions,
        data_max_date=BULL.bullpen_data_max_date())


@report_bp.route("/bullpen/<int:pitcher_id>/<date>.pdf")
@login_required
def bullpen_pdf(pitcher_id: int, date: str):
    if not can_view_bullpen(current_user, pitcher_id):
        abort(403)
    try:
        pdf = build_bullpen_report(pitcher_id, date)
    except ReportDataError:
        abort(404)
    return Response(
        pdf, mimetype="application/pdf",
        headers={"Content-Disposition":
                 f'attachment; filename="bullpen_{pitcher_id}_{_safe(date)}.pdf"'})
```
Also import `ReportDataError` from `app.reports.bullpen_report` (or reuse the one already imported from `pitcher_postgame` — same class re-exported; import once, avoid a name clash).

- [ ] **Step 5: Create `app/templates/reports/bullpen_landing.html`**

Mirror `pitching_landing.html`'s structure (extends `base.html`, crimson hero, `.filter-bar`, back-link to `/pitching`). Include:
- a "Data through {{ data_max_date }} — bullpen feed pending refresh" note;
- a pitcher `<select>` (GET `?pitcher_id=`), each option `{{ p.pitcher }} ({{ p.sessions }})`;
- when `sessions`, a list of session rows each linking to `/reports/bullpen/{{ pitcher_id }}/{{ s.date }}.pdf` (`target=_blank`), showing `{{ s.date }} · {{ s.pitches }} pitches`;
- styled empty state.

- [ ] **Step 6: Add a hub card**

In `app/templates/main/pitching_hub.html` card list, add after Postgame Reports:
```python
  {"title": "Bullpen Reports", "desc": "Trackman bullpen one-pagers (LMU-branded).", "href": "/reports/bullpen"},
```

- [ ] **Step 7: Run tests + full suite** — `python -m pytest tests/test_bullpen_landing.py -q` then `python -m pytest -q`. Expected PASS.

- [ ] **Step 8: Live smoke** — `python run.py` (kill by port owner first), log in as coach → `/reports/bullpen` → pick Geis → a session → PDF downloads (2 pages). Also verify the pitching hub shows the new card.

- [ ] **Step 9: Commit** — `git add app/auth/access.py app/reports/routes.py app/templates/reports/bullpen_landing.html app/templates/main/pitching_hub.html tests/test_bullpen_landing.py && git commit -m "feat(bullpen): landing page + pdf route + self-only gate + hub card"`

---

## Self-Review

**Spec coverage:** BULLPEN source + normalization + LMU scope (Task 1). 2-page report summary + per-pitch detail, LMU-branded (Task 2). Landing page + pdf route + self-only gate + "data through" banner + hub card (Task 3). SFTP repopulation noted as out-of-scope (Global Constraints). Report reads table directly so refresh needs no code change (Global Constraints).

**Placeholder scan:** Task 3 Step 5 (landing template) and Step 1 (client fixtures) reference `pitching_landing.html`/`test_pitching_landing.py` patterns to copy — the implementer must read those two files first and mirror them (they are concrete, existing files, not placeholders). All Python/chart/template code is inline.

**Type consistency:** `session_pitches` snake_case cols match `bullpen_plots` and the template `p.*` fields and `summary_by_pitch_type` inputs. `build_bullpen_report(pid, date)` signature matches the route + tests. `can_view_bullpen` matches the route gate. Raw Trackman `PitcherId` is the identity key end-to-end (data, route, gate, tests). `lmu_bullpen_pitchers` cols (`pitcher_id/pitcher/sessions`) match landing template + assembler.

**Provisional flags:** LMU team codes (`LOY_MAR`+`LOY_LIO`); session = one `(PitcherId, Date)` (Live+Warmup pooled — not split); the Stats-by-pitch-type columns are a reasonable subset of the Trackman sample. Confirm on the live smoke + with the coach.
