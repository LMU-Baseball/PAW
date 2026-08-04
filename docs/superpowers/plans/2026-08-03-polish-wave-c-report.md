# Polish Wave C — Report + Shared Visuals (SP5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Checkbox steps.

**Goal:** Pitcher-report additions (top-bar Total Pitches/Strike%/Max Velo, chart gridlines) + shared visuals applied to BOTH the report and the bullpen dashboard (nine-pocket on every strike zone app-wide, Fastball callouts, pitch-frequency stacked bar).

**Architecture:** Extend `app/data/pitching.py` (header metrics, fastball callout) + `app/reports/plots.py` (gridlines, pitch-freq bar builder) + `app/reports/templates/pitcher_onepager.html`. Add nine-pocket to the remaining dashboard zone charts (catching/hitting/practice — bullpen already done in Wave B). Add fastball callout + pitch-freq bar to the bullpen dashboard too.

**Tech Stack:** matplotlib (report), Plotly (dashboards), Jinja2, pandas, pytest.

## Global Constraints
- Python 3.12; `from __future__ import annotations`. Report colors via `app.reports.plots.color_for`.
- Nine-pocket = strike-zone box + a 3×3 interior grid. Report `plots._draw_zone` ALREADY draws it; reuse the same look for dashboard zone charts.
- Fastball callout = Avg Velo · Max Velo · Avg Spin for `Fastball` pitches; "—" when no Fastball.
- Pitch-frequency bar = one horizontal stacked bar, segment width ∝ pitch count, colored by type, count labeled, with the total.
- `flask` not on PATH → `python -m pytest`. Report tests may build a real PDF (slow, Playwright) — run the FOCUSED file test only; controller runs the full suite. `PYTHONIOENCODING=utf-8`. Clear `instance/report_cache/` is NOT needed for tests (they build fresh). After any report-code change the on-disk PDF cache is data-version-keyed — note in report but don't clear in tests.

---

### Task 1: Report top-bar — Total Pitches, Strike %, Max Velo

**Files:** Modify `app/data/pitching.py` (`header_stat_line`), `app/reports/templates/pitcher_onepager.html`; Test `tests/test_pitching.py` (append).

**Behavior:** `header_stat_line(df)` gains `strike_pct` (called+swinging strikes / pitches, 0–100 1dp) and `max_velo` (max `rel_speed`, 1dp, None-safe). Template header adds STRIKE% and MAX VELO spans (PITCHES already present = total pitches).

- [ ] **Step 1: Failing test** (append to `tests/test_pitching.py`):

```python
def test_header_stat_line_has_strike_and_maxvelo():
    import pandas as pd
    from app.data import pitching as P
    df = pd.DataFrame({
        "batter_side": ["Right", "Left"], "outs_on_play": [0, 1],
        "play_result": ["Out", "Single"], "runs_scored": [0, 0],
        "korbb": ["Undefined", "Undefined"], "pitch_of_pa": [1, 1],
        "pitch_call": ["StrikeCalled", "BallCalled"], "rel_speed": [90.0, 94.4],
        "balls": [0, 1], "strikes": [1, 0], "inning": [1, 1], "pa_of_inning": [1, 2]})
    line = P.header_stat_line(df)
    assert "strike_pct" in line and "max_velo" in line
    assert line["max_velo"] == 94.4
    assert 0 <= line["strike_pct"] <= 100
```

- [ ] **Step 2: Verify fail** — `python -m pytest tests/test_pitching.py -k "strike_and_maxvelo" -q`.

- [ ] **Step 3: Implement** — in `header_stat_line`, before the return, compute:

```python
    n = len(df)
    strikes = int(df["pitch_call"].isin(_STRIKE_CALLS).sum()) if n else 0
    mv = df["rel_speed"].dropna().max() if n and "rel_speed" in df.columns else None
```
and add to the returned dict:
```python
        "strike_pct": round(100.0 * strikes / n, 1) if n else 0.0,
        "max_velo": None if mv is None or pd.isna(mv) else round(float(mv), 1),
```
(`_STRIKE_CALLS` already exists in the module — used by `game_overall_line`.)

In `pitcher_onepager.html`, add two spans to `.hdr-line` after PITCHES:
```html
      <span><b>{{ line.strike_pct|round(0)|int }}%</b><i>STRIKE%</i></span>
      <span><b>{{ line.max_velo if line.max_velo is not none else '—' }}</b><i>MAX MPH</i></span>
```

- [ ] **Step 4: Verify pass** — focused test.

- [ ] **Step 5: Commit** — `git commit -m "feat(report): top-bar strike% + max velo"`.

---

### Task 2: Nine-pocket on the remaining dashboard zone charts

**Files:** Modify zone charts in `app/dashboards/catching/charts.py`, `app/dashboards/hitting/charts.py`, `app/dashboards/hitting_practice/charts.py`; Tests append to the matching `tests/test_*_dash.py`.

**Behavior:** Every strike-zone / plate-location chart that currently draws only the outer box (or no interior grid) gets the 3×3 nine-pocket interior grid, matching the bullpen `charts._add_zone` look (2 vertical + 2 horizontal interior lines at thirds, color `#bbb`, width ~0.8). Bullpen is already done (Wave B).

- [ ] **Step 1: Read + locate** — grep each file for the zone-drawing (`add_shape`/`Rectangle`/`add_hline`/zone box). Identify each zone chart function and its zone box coordinates (they vary: some use plate coords ×12 inches, some feet). For EACH, add the 3×3 interior grid spanning the existing box using that chart's own coordinates.

- [ ] **Step 2: Failing test** — for each dashboard with a zone chart, append a test asserting the zone chart figure now has the interior grid (e.g. `len(fig.layout.shapes) >= 5` for Plotly `add_shape` charts, or count line traces). Use each test file's existing chart-df fixture.

- [ ] **Step 3: Verify fail.**

- [ ] **Step 4: Implement** — add the interior grid lines to each identified zone chart. If a shared helper is cleaner, add a small `_zone_grid(fig, x0, x1, y0, y1)` in the respective charts.py (do NOT cross-import bullpen's private helper). Keep each chart's existing box.

- [ ] **Step 5: Verify pass** — each file's focused test.

- [ ] **Step 6: Commit** — `git commit -m "feat(dashboards): nine-pocket grid on all zone charts"`.

> If a dashboard has NO zone/plate chart, skip it and note so in the report. The requirement is "every strike zone that exists" gets the nine-pocket.

---

### Task 3: Report chart gridlines

**Files:** Modify `app/reports/plots.py`; Test `tests/test_report_plots.py` (create or append — a light smoke that the builders still return a data URI).

**Behavior:** Add light gridlines to the report's matplotlib charts to aid reading — especially horizontal gridlines. Apply to `movement_map_uri` (currently only 0-axes) and keep the zone charts' existing 3×3. Use `ax.grid(True, color="#eee", lw=0.6, zorder=0)` (and `ax.set_axisbelow(True)`), horizontal emphasis where the chart is value-vs-category.

- [ ] **Step 1: Failing/smoke test** — append a test asserting `movement_map_uri(df)` returns a `data:image/png` URI without error on a small df (the gridline change shouldn't break rendering). If a report-plots test file doesn't exist, create `tests/test_report_plots.py` with a minimal df fixture (columns `horz_break`, `induced_vert_break`, `tagged_pitch_type`/`auto_pitch_type`, `rel_speed`).

- [ ] **Step 2: Verify fail/smoke.**

- [ ] **Step 3: Implement** — in `movement_map_uri` (and any other value-axis report chart), add `ax.set_axisbelow(True); ax.grid(True, which="major", color="#eee", lw=0.6)` before plotting. Keep aspect/limits. Don't touch the zone charts' existing grid.

- [ ] **Step 4: Verify pass.**

- [ ] **Step 5: Commit** — `git commit -m "feat(report): gridlines on movement chart for readability"`.

---

### Task 4: Fastball callout (report + bullpen dashboard)

**Files:** Modify `app/data/pitching.py` (`fastball_callout`), `app/reports/templates/pitcher_onepager.html`, `app/reports/pitcher_postgame.py` (pass the callout into the template context), `app/dashboards/bullpen/tabs/session_detail.py` (render callout under the summary table); Tests append to `tests/test_pitching.py` + `tests/test_bullpen_dash.py`.

**Interface produced:** `fastball_callout(df, pt_col="tagged_pitch_type") -> dict{avg_velo, max_velo, avg_spin}` (each None-safe, rounded 1dp velo / int spin).

- [ ] **Step 1: Failing tests**:

`tests/test_pitching.py`:
```python
def test_fastball_callout():
    import pandas as pd
    from app.data import pitching as P
    df = pd.DataFrame({"tagged_pitch_type": ["Fastball", "Fastball", "Slider"],
                       "rel_speed": [90.0, 92.0, 80.0], "spin_rate": [2200.0, 2300.0, 2400.0]})
    c = P.fastball_callout(df)
    assert c["avg_velo"] == 91.0 and c["max_velo"] == 92.0 and c["avg_spin"] == 2250
    empty = P.fastball_callout(pd.DataFrame({"tagged_pitch_type": ["Slider"],
                                             "rel_speed": [80.0], "spin_rate": [2400.0]}))
    assert empty == {"avg_velo": None, "max_velo": None, "avg_spin": None}
```

`tests/test_bullpen_dash.py`:
```python
def test_session_detail_has_fastball_callout_live():
    from app.dashboards.bullpen.tabs import session_detail
    from app.data import bullpen as B
    s = B.session_options(GEIS, "2025-09-01", "2026-05-13")
    if s.empty:
        import pytest; pytest.skip("no sessions")
    out = str(session_detail.render(GEIS, s.iloc[0]["date"]))
    assert "Fastball" in out and ("Avg Velo" in out or "Avg" in out)
```

- [ ] **Step 2: Verify fail.**

- [ ] **Step 3: Implement**

In `app/data/pitching.py`:
```python
def fastball_callout(df, pt_col="tagged_pitch_type") -> dict:
    """Fastball Avg Velo / Max Velo / Avg Spin for a pitch df."""
    none = {"avg_velo": None, "max_velo": None, "avg_spin": None}
    if df is None or df.empty or pt_col not in df.columns:
        return none
    fb = df[df[pt_col] == "Fastball"]
    v, s = fb["rel_speed"].dropna(), fb["spin_rate"].dropna() if "spin_rate" in fb else None
    if v.empty:
        return none
    return {"avg_velo": round(float(v.mean()), 1), "max_velo": round(float(v.max()), 1),
            "avg_spin": (int(round(float(s.mean()))) if s is not None and not s.empty else None)}
```

Report: in `pitcher_postgame.py::_build_html`, compute `fb = P.fastball_callout(df, pt_col=...)` (use whichever pitch-type column the report df uses — check; likely via `P.pitch_type(df)` → pass a df with that column or add a `pt_col`) and pass `fastball=fb` to the template render. In `pitcher_onepager.html`, add under the Movement Summary panel:
```html
      {% if fastball.avg_velo is not none %}
      <div class="fb-callout"><b>Fastball</b> — Avg Velo {{ fastball.avg_velo }} · Max {{ fastball.max_velo }} · Avg Spin {{ fastball.avg_spin }}</div>
      {% endif %}
```
Add a small `.fb-callout` CSS rule in `app/reports/static/report.css` (muted, small).

Bullpen dashboard: in `session_detail.render`, after the summary table, add:
```python
    from app.data import pitching as P
    fb = P.fastball_callout(df, pt_col="tagged_pitch_type")
    callout = html.Div()
    if fb["avg_velo"] is not None:
        callout = html.Div([html.B("Fastball"),
            f" — Avg Velo {fb['avg_velo']} · Max {fb['max_velo']} · Avg Spin {fb['avg_spin']}"],
            style={"padding": "6px 4px", "color": "#555", "fontSize": "15px"})
```
and include `callout` in the returned layout (below the summary table).

- [ ] **Step 4: Verify pass** — focused files.

- [ ] **Step 5: Commit** — `git commit -m "feat(report+bullpen): fastball callout (avg/max velo, avg spin)"`.

---

### Task 5: Pitch-frequency stacked bar (report + bullpen dashboard)

**Files:** Modify `app/reports/plots.py` (matplotlib builder), `app/reports/pitcher_postgame.py` + `pitcher_onepager.html` (wire it), `app/dashboards/bullpen/charts.py` (Plotly builder) + `app/dashboards/bullpen/tabs/session_detail.py` (render it); Tests append.

**Interfaces produced:** `plots.pitch_freq_bar_uri(counts)` (matplotlib PNG data URI) and `charts.pitch_freq_bar(df)` (Plotly Figure). `counts` = list of `(pitch_type, n)` sorted desc.

- [ ] **Step 1: Failing tests**:

`tests/test_report_plots.py`:
```python
def test_pitch_freq_bar_uri():
    from app.reports import plots
    uri = plots.pitch_freq_bar_uri([("Fastball", 6), ("Slider", 3), ("ChangeUp", 2)])
    assert uri.startswith("data:image/png")
    assert plots.pitch_freq_bar_uri([]).startswith("data:image/png")
```

`tests/test_bullpen_dash.py`:
```python
def test_pitch_freq_bar_plotly():
    import pandas as pd
    from app.dashboards.bullpen import charts
    df = pd.DataFrame({"tagged_pitch_type": ["Fastball", "Fastball", "Slider"]})
    fig = charts.pitch_freq_bar(df)
    assert fig is not None and len(fig.data) >= 1
```

- [ ] **Step 2: Verify fail.**

- [ ] **Step 3: Implement**

`plots.py`:
```python
def pitch_freq_bar_uri(counts) -> str:
    """Horizontal stacked bar of pitch-type mix (width ∝ count), labeled."""
    fig, ax = plt.subplots(figsize=(6.4, 0.7))
    total = sum(n for _, n in counts) or 1
    left = 0
    for pt, n in counts:
        w = n / total
        ax.barh(0, w, left=left, color=_color_for(pt), edgecolor="white")
        if w > 0.06:
            ax.text(left + w / 2, 0, str(n), ha="center", va="center",
                    fontsize=8, color="white", fontweight="bold")
        left += w
    ax.set_xlim(0, 1); ax.set_ylim(-0.5, 0.5); ax.axis("off")
    ax.set_title(f"Pitch Frequency (Total {total if counts else 0})",
                 fontsize=9, color="#9A0021", fontweight="bold", loc="left")
    return _fig_to_uri(fig)
```

`charts.py` (bullpen):
```python
def pitch_freq_bar(df):
    if df is None or df.empty:
        return _empty()
    vc = df["tagged_pitch_type"].value_counts()
    total = int(vc.sum())
    fig = go.Figure()
    for pt, n in vc.items():
        fig.add_trace(go.Bar(y=["mix"], x=[int(n)], name=str(pt), orientation="h",
            marker_color=color_for(pt), text=[int(n)], textposition="inside",
            hovertemplate=f"{pt}: {int(n)}<extra></extra>"))
    fig.update_layout(barmode="stack", **_BASE)
    fig.update_layout(title=f"Pitch Frequency (Total {total})", showlegend=True,
                      height=140, yaxis_visible=False)
    return fig
```

Wire: report — in `pitcher_postgame.py::_build_html` compute the usage counts (reuse `P.pitch_usage_table(df)` → `[(r["pitch"], r["count"])...]` or a `value_counts` on the pitch-type column) and pass `charts["pitch_freq"]=plots.pitch_freq_bar_uri(counts)`; add `<img src="{{ charts.pitch_freq }}">` in a header-adjacent panel of `pitcher_onepager.html`. Bullpen — in `session_detail.render`, add `dcc.Graph(figure=charts.pitch_freq_bar(df))` above the charts grid.

- [ ] **Step 4: Verify pass** — focused files.

- [ ] **Step 5: Commit** — `git commit -m "feat(report+bullpen): pitch-frequency stacked bar"`.

---

## Self-Review
- **SP5 coverage:** top-bar metrics (T1), nine-pocket app-wide (T2 dashboards + report already has it + bullpen done Wave B), gridlines (T3), fastball callout report+dashboard (T4), pitch-freq bar report+dashboard (T5). ✅
- **Placeholder scan:** T2 says "grep + locate each zone chart" — deliberate discovery step; the transform (add 3×3 interior grid) is concrete. T4/T5 wiring says "check the report df's pitch-type column" — the report uses `P.pitch_type(df)`; implementer confirms the exact column at edit time.
- **Type consistency:** `fastball_callout(df, pt_col)` (T4) returns {avg_velo,max_velo,avg_spin}, consumed by report template + bullpen session_detail. `pitch_freq_bar_uri(counts)` / `pitch_freq_bar(df)` (T5) signatures match their call sites. `header_stat_line` new keys (T1) consumed by the template.
- **Risk:** report changes are data-version-cached on disk; tests build fresh so unaffected. Live report PDF build is slow (Playwright) — tests target the data/builder units, not a full PDF build.
