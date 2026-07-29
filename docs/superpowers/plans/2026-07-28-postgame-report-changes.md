# Post-Game Report Changes Implementation Plan (SP3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace "Spread" with VAA, swap the Pitch Usage table for three donut charts, and add a contact-result shape key to the zone charts on the pitcher one-pager PDF.

**Architecture:** All matplotlib/in-process (no headless browser). `movement_summary` gains a `vaa` field; `plots.py` gains `pitch_usage_donuts_uri` (1×3 donuts) and shape-coded markers in `zone_chart_uri`; `_build_html` adds one chart URI; the template swaps a table for an `<img>` and one header cell.

**Tech Stack:** matplotlib (Agg), Jinja2, pandas, pytest.

## Global Constraints

- Keep panel titles "Pitch Usage" and "Movement Summary" in the template (a test asserts both tokens) and keep `data:image/png` count ≥ 3.
- `zone_chart_uri(df, batter_side, title)` signature UNCHANGED (tests call it positionally).
- Barrel = `pitch_call == "InPlay"` & `exit_speed >= 95` (simplified 95+ EV, matches SP2).
- After deploying, clear `instance/report_cache/` so cached PDFs rebuild (cache key is data-version, not code-version).
- Run: `python -m pytest -q`. Commit per task. No `git stash/reset/checkout/clean`.

---

### Task 1: "Spread" → VAA

**Files:**
- Modify: `app/data/pitching.py` (`movement_summary`)
- Modify: `app/reports/templates/pitcher_onepager.html` (Movement Summary header + cell)
- Test: `tests/test_report_metrics.py:86-91`

**Interfaces:**
- Produces: each `movement_summary` row has key `vaa` (float°, avg `vert_appr_angle`) and NO `spread`.

- [ ] **Step 1: Update the shape test (make it fail)**

In `tests/test_report_metrics.py` `test_movement_summary_shape`, change the key set:
```python
    assert set(rows[0]) >= {"pitch", "velo_avg", "velo_max", "ivb_avg", "ivb_rhh",
                          "ivb_lhh", "hb_avg", "hb_rhh", "hb_lhh", "vaa"}
    assert "spread" not in rows[0]
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_report_metrics.py::test_movement_summary_shape -q`
Expected: FAIL (`spread` still present, `vaa` absent).

- [ ] **Step 3: Replace spread with vaa in `movement_summary`**

In `app/data/pitching.py::movement_summary`, replace the spread computation and row field. Remove:
```python
        # PROVISIONAL "Spread": std dev of total break magnitude (movement
        # consistency), in inches.
        mag = np.sqrt(sub["induced_vert_break"] ** 2 + sub["horz_break"] ** 2)
        spread = float(mag.std(ddof=0)) if len(sub) > 1 else 0.0
```
and in the appended row dict replace `"spread": _r1(spread),` with:
```python
            # VAA — average vertical approach angle (degrees), warehouse
            # column vert_appr_angle. Replaces the old break-magnitude "Spread".
            "vaa": _r1(sub["vert_appr_angle"].mean()),
```

- [ ] **Step 4: Update the template**

In `app/reports/templates/pitcher_onepager.html`, Movement Summary table: change the header cell `<th>Spread</th>` → `<th>VAA</th>`, and the row cell `{{ r.spread if r.spread is not none else '—' }}` → `{{ r.vaa if r.vaa is not none else '—' }}`.

- [ ] **Step 5: Run tests to verify pass**

Run: `python -m pytest tests/test_report_metrics.py tests/test_report_engine.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/data/pitching.py app/reports/templates/pitcher_onepager.html tests/test_report_metrics.py
git commit -m "feat(report): replace Spread with VAA (avg vertical approach angle)"
```

---

### Task 2: Pitch Usage table → three donut charts

**Files:**
- Modify: `app/reports/plots.py` (add `Wedge` import, `_donut`, `_split_donut`, `pitch_usage_donuts_uri`)
- Modify: `app/reports/pitcher_postgame.py` (`_build_html` charts dict)
- Modify: `app/reports/templates/pitcher_onepager.html` (Pitch Usage panel body)
- Test: `tests/test_report_plots.py`, `tests/test_report_engine.py`

**Interfaces:**
- Consumes: `P.pitch_usage_table(df)` (fields `pitch`, `usage_pct`, `twok_usage_pct`, `vrhh`, `vlhh`), `plots._color_for`.
- Produces: `plots.pitch_usage_donuts_uri(df) -> str` (one PNG data URI, 1×3 donuts: Overall / 2K / Splits). Render context key `charts.pitch_usage_donuts`.

- [ ] **Step 1: Write the failing plots test**

Add to `tests/test_report_plots.py`:
```python
def test_pitch_usage_donuts_returns_png():
    _is_png_uri(plots.pitch_usage_donuts_uri(_df()))


def test_pitch_usage_donuts_empty_safe():
    _is_png_uri(plots.pitch_usage_donuts_uri(_df().iloc[0:0]))
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_report_plots.py::test_pitch_usage_donuts_returns_png -q`
Expected: FAIL (`pitch_usage_donuts_uri` not defined).

- [ ] **Step 3: Implement the donuts in plots.py**

Change the patches import at the top:
```python
from matplotlib.patches import Ellipse, Wedge
```
Add the builders (near the other `*_uri` functions):
```python
def _donut(ax, values, colors, center_label) -> None:
    pairs = [(v, c) for v, c in zip(values, colors) if v and v > 0]
    ax.set_aspect("equal")
    if pairs:
        vals, cols = [p[0] for p in pairs], [p[1] for p in pairs]
        ax.pie(vals, colors=cols, startangle=90, counterclock=False,
               wedgeprops=dict(width=0.42, edgecolor="white", linewidth=1),
               autopct=lambda p: f"{p:.0f}%" if p >= 6 else "",
               pctdistance=0.78, textprops=dict(fontsize=7, color="#222"))
    else:
        ax.text(0.5, 0.5, "—", ha="center", va="center", transform=ax.transAxes)
    ax.text(0, 0, center_label, ha="center", va="center",
            fontsize=10, fontweight="bold", color="#0076A5")


def _split_donut(ax, vlhh, vrhh, colors) -> None:
    ax.set_xlim(-1.25, 1.25); ax.set_ylim(-1.25, 1.25)
    ax.set_aspect("equal"); ax.axis("off")
    r_out, r_in = 1.0, 0.58

    def _half(vals, start, end):
        tot = sum(v for v in vals if v) or 1
        a = start
        for v, c in zip(vals, colors):
            if not v:
                continue
            sweep = (end - start) * v / tot
            ax.add_patch(Wedge((0, 0), r_out, a, a + sweep, width=r_out - r_in,
                               facecolor=c, edgecolor="white", linewidth=1))
            a += sweep
    _half(vlhh, 90, 270)    # left half = vLHH
    _half(vrhh, -90, 90)    # right half = vRHH
    ax.text(0, 0.05, "Splits", ha="center", va="center",
            fontsize=10, fontweight="bold", color="#0076A5")
    ax.text(0, -0.16, "vLHH | vRHH", ha="center", va="center",
            fontsize=6, color="#555")


def pitch_usage_donuts_uri(df) -> str:
    """Overall / 2K / Splits(vLHH|vRHH) usage donuts as one PNG data URI."""
    from app.data.pitching import pitch_usage_table
    rows = pitch_usage_table(df)
    fig, axes = plt.subplots(1, 3, figsize=(9.2, 3.2))
    if not rows:
        for ax, lbl in zip(axes, ("Overall", "2K", "Splits")):
            ax.axis("off")
            ax.text(0.5, 0.5, "—", ha="center", va="center", transform=ax.transAxes)
        return _fig_to_uri(fig)
    colors = [_color_for(r["pitch"]) for r in rows]
    _donut(axes[0], [r["usage_pct"] for r in rows], colors, "Overall")
    _donut(axes[1], [r["twok_usage_pct"] for r in rows], colors, "2K")
    _split_donut(axes[2], [r["vlhh"] for r in rows], [r["vrhh"] for r in rows], colors)
    return _fig_to_uri(fig)
```

- [ ] **Step 4: Run the plots tests to verify pass**

Run: `python -m pytest tests/test_report_plots.py -q`
Expected: PASS.

- [ ] **Step 5: Add the chart to `_build_html` and swap the template panel**

In `app/reports/pitcher_postgame.py::_build_html`, extend the `charts` dict:
```python
    charts = {
        "zone_rhh": plots.zone_chart_uri(df, "Right", "vRHH Zone"),
        "movement": plots.movement_map_uri(df, "Movement Map"),
        "zone_lhh": plots.zone_chart_uri(df, "Left", "vLHH Zone"),
        "pitch_usage_donuts": plots.pitch_usage_donuts_uri(df),
    }
```
In `pitcher_onepager.html`, replace the Pitch Usage panel's `<table>...</table>` (the whole table block, keeping the `<div class="panel-t">Pitch Usage</div>`) with:
```html
      <img class="usage-donuts" src="{{ charts.pitch_usage_donuts }}" alt="Pitch Usage">
```
Add to `app/reports/static/report.css`:
```css
.usage-donuts { width: 100%; height: auto; display: block; }
```

- [ ] **Step 6: Run the report tests to verify pass**

Run: `python -m pytest tests/test_report_engine.py tests/test_report_plots.py -q`
Expected: PASS (`test_build_html_renders_onepager_sections` still finds "Pitch Usage", "Movement Summary", and ≥3 png URIs — now 4 charts + logos).

- [ ] **Step 7: Commit**

```bash
git add app/reports/plots.py app/reports/pitcher_postgame.py app/reports/templates/pitcher_onepager.html app/reports/static/report.css tests/test_report_plots.py
git commit -m "feat(report): pitch usage donuts (Overall/2K/Splits) replace the usage table"
```

---

### Task 3: Contact-result shape key on the zone charts

**Files:**
- Modify: `app/reports/plots.py` (`zone_chart_uri` markers + `_contact_classes` helper + `Line2D` legend)
- Test: `tests/test_report_plots.py`

**Interfaces:**
- Produces: `plots._contact_classes(df) -> pd.Series` (values `"Whiff"`/`"Barrel"`/`"In Play"`/NaN). `zone_chart_uri` signature unchanged.

- [ ] **Step 1: Write the failing helper test**

Add to `tests/test_report_plots.py`:
```python
def test_contact_classes_mapping():
    import pandas as pd
    df = pd.DataFrame({
        "pitch_call": ["StrikeSwinging", "InPlay", "InPlay", "BallCalled"],
        "exit_speed": [None, 97.0, 80.0, None]})
    cc = list(plots._contact_classes(df))
    assert cc[0] == "Whiff"
    assert cc[1] == "Barrel"     # InPlay & 95+
    assert cc[2] == "In Play"    # InPlay & <95
    assert pd.isna(cc[3])        # take -> plain dot
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_report_plots.py::test_contact_classes_mapping -q`
Expected: FAIL (`_contact_classes` not defined).

- [ ] **Step 3: Implement the shape-coded markers**

At the top of `plots.py` add:
```python
from matplotlib.lines import Line2D
```
Add near `zone_chart_uri`:
```python
# Contact-result shape key (color still encodes pitch type):
#   Whiff = circle, Barrel (InPlay & 95+ EV) = X, In Play = square.
_CONTACT_MARKERS = [("Whiff", "o"), ("Barrel", "X"), ("In Play", "s")]


def _contact_classes(df):
    """Per-pitch contact class Series: Whiff / Barrel / In Play / NaN (take)."""
    import pandas as pd
    call = df["pitch_call"]
    ev = df["exit_speed"] if "exit_speed" in df.columns else pd.Series(index=df.index, dtype=float)
    cc = pd.Series(index=df.index, dtype=object)
    cc[call == "StrikeSwinging"] = "Whiff"
    inplay = call == "InPlay"
    cc[inplay & (ev >= 95)] = "Barrel"
    cc[inplay & ~(ev >= 95)] = "In Play"
    return cc
```
Rewrite the scatter section of `zone_chart_uri` (the `if not d.empty:` block that currently loops `groupby("_pt")`):
```python
    if not d.empty:
        d["_pt"] = pitch_type(d)
        d["_cc"] = _contact_classes(d)
        # plain small dots for non-contact pitches (takes/balls/called/foul)
        base = d[d["_cc"].isna()]
        for pt, sub in base.groupby("_pt"):
            ax.scatter(sub["plate_loc_side"], sub["plate_loc_height"], s=20,
                       color=_color_for(pt), edgecolor="white", linewidth=0.3,
                       alpha=0.5, zorder=2, marker=".")
        # shaped markers for contact events (color = pitch type)
        for cc, marker in _CONTACT_MARKERS:
            ev_sub = d[d["_cc"] == cc]
            for pt, sub in ev_sub.groupby("_pt"):
                ax.scatter(sub["plate_loc_side"], sub["plate_loc_height"], s=52,
                           color=_color_for(pt), edgecolor="white", linewidth=0.5,
                           alpha=0.95, zorder=3, marker=marker)
    # shape-only key below the plot (does not overlap the zone)
    handles = [Line2D([0], [0], marker=m, color="none", markerfacecolor="#444",
                      markeredgecolor="#444", markersize=6, label=lbl)
               for lbl, m in _CONTACT_MARKERS]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.02),
              ncol=3, frameon=False, fontsize=6, handletextpad=0.2,
              columnspacing=0.8)
```
(Delete the old `for pt, sub in d.groupby("_pt"): ax.scatter(... s=46 ...)` loop and the "No legend" comment.)

- [ ] **Step 4: Run the plots tests to verify pass**

Run: `python -m pytest tests/test_report_plots.py -q`
Expected: PASS (`test_zone_chart_returns_png`, `test_plots_empty_input_safe`, and the new mapping test).

- [ ] **Step 5: Full suite + a real PDF smoke**

Run: `python -m pytest -q`
Expected: PASS (baseline 351 + new tests).
Then a real build smoke:
Run: `PYTHONIOENCODING=utf-8 python -c "from app import create_app; app=create_app();\nfrom app.reports.pitcher_postgame import build_pitcher_postgame;\nimport os; os.environ.setdefault('PAW_REPORT_CACHE_DIR', r'C:/Users/Brad/AppData/Local/Temp/claude/.../scratchpad/rc');\nwith app.app_context():\n pdf=build_pitcher_postgame(166,1); open('scratch_report.pdf','wb').write(pdf); print('PDF bytes', len(pdf))"`
Expected: prints a positive byte count (valid PDF). Clear the real cache dir if needed so it rebuilds.

- [ ] **Step 6: Commit**

```bash
git add app/reports/plots.py tests/test_report_plots.py
git commit -m "feat(report): contact-result shape key on zone charts (whiff/barrel/in-play)"
```

---

## Self-Review

**Spec coverage:** Spread→VAA (Task 1). Usage table→3 donuts Overall/2K/Splits (Task 2). Contact key whiff○/barrel✕/inplay▢ (Task 3).

**Placeholder scan:** none (all code inline). The Step-5 smoke command's cache path is illustrative — use the session scratchpad path or omit the env override to use the default `instance/report_cache/`.

**Type consistency:** `pitch_usage_donuts_uri(df)`/`_contact_classes(df)` names match their test + assembler usage. `movement_summary` row key `vaa` matches the template `r.vaa` and the test. `zone_chart_uri` signature unchanged. Charts dict key `pitch_usage_donuts` matches the template `charts.pitch_usage_donuts`.

**Provisional flags carried:** strike% column is dropped from the report (was in the usage table; the donuts don't show it) — acceptable per "convert the usage table to the visual"; note for coach. Contact key shows ALL pitches (takes as faint dots) — flag if coach wants contact-only.
