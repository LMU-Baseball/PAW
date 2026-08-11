"""Assemble the LMU bullpen report PDF (2 pages) from BULLPEN data."""
from __future__ import annotations

import os
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.data import bullpen as B
from app.data import pitching as P
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

__all__ = ["build_bullpen_report", "ReportDataError"]


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
    counts = list(df["tagged_pitch_type"].value_counts().items())
    charts = {
        "velo": BP.velo_strip_uri(df), "movement": BP.movement_uri(df),
        "release": BP.release_uri(df), "location": BP.location_uri(df),
        "pitch_freq": plots.pitch_freq_donut_uri(counts),
    }
    mv = df["rel_speed"].dropna()
    max_velo = round(float(mv.max()), 1) if not mv.empty else None
    strike_pct = B.strike_pct(df)
    fastball = P.fastball_callout(df, pt_col="tagged_pitch_type")
    css = _inline_fonts((_STATIC / "report.css").read_text(encoding="utf-8"))
    assets = {"lmu_png": _data_uri(_ASSETS_DIR / "lmu.png", "image/png"),
              "lion_png": _data_uri(_ASSETS_DIR / "lion-white.png", "image/png")}
    return _env.get_template("bullpen_report.html").render(
        pitcher=name, date=str(date), total=len(df),
        strike_pct=strike_pct, max_velo=max_velo, fastball=fastball,
        summary=summary, pitches=df.to_dict("records"),
        pitch_colors=pitch_colors, charts=charts, css=css, assets=assets)


# Bump when the bullpen report layout/content changes so cached PDFs (keyed by
# DATA max-date) don't keep serving the old design. See MEMORY §3j.
_CODE_VERSION = "2026-08-layout-v3-onepage"


def _cache_path(pid: int, date, maxd) -> Path:
    safe = re.sub(r"[^0-9A-Za-z._-]", "_", f"{pid}_{date}_{maxd}_{_CODE_VERSION}")
    return _CACHE_DIR / f"bullpen_{safe}.pdf"


def build_bullpen_report(pitcher_trackman_id: int, date) -> bytes:
    maxd = B.bullpen_data_max_date()
    cache_file = _cache_path(int(pitcher_trackman_id), date, maxd)
    if cache_file.exists():
        return cache_file.read_bytes()
    pdf = html_to_pdf(_build_html(pitcher_trackman_id, date))
    try:  # cache is best-effort; a write failure must not fail the download
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(pdf)
    except OSError:
        pass
    return pdf
