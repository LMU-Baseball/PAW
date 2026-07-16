"""Assemble the pitcher postgame PDF from warehouse data + the report engine."""
from __future__ import annotations

import base64
import os
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.data import pitching as P
from app.reports.charts import fig_to_data_uri, rendering_session
from app.reports.pdf import html_to_pdf

_DIR = Path(__file__).resolve().parent
_STATIC = _DIR / "static"
# On-disk PDF cache. A report is ~identical for a given (game_id, pitcher_id)
# until the pitcher gets new data (which shifts the season velo-trend), so the
# cache key includes a data-version token. Override the location with
# PAW_REPORT_CACHE_DIR (tests point this at a tmp dir).
_CACHE_DIR = Path(os.environ.get(
    "PAW_REPORT_CACHE_DIR", str(_DIR.parents[1] / "instance" / "report_cache")))
# report.css lives in app/reports/static/, but the shared static assets it
# references (Teko-*.ttf, lmu.png) live in app/static/reports/.
_ASSETS_DIR = _DIR.parents[0] / "static" / "reports"
_env = Environment(
    loader=FileSystemLoader(str(_DIR / "templates")),
    autoescape=select_autoescape(["html"]),
)

_FONT_URL_RE = re.compile(r"url\((['\"]?)([^'\")]+\.ttf)\1\)")


class ReportDataError(Exception):
    """Raised when there is no data to build a report for the given keys."""


def _data_uri(path: Path, mime: str) -> str:
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _inline_fonts(css_text: str) -> str:
    """Replace @font-face url('Teko-*.ttf') with embedded data: URIs.

    html_to_pdf() renders via Page.set_content(), whose document does not
    have a file:// origin -- Chromium refuses ("Not allowed to load local
    resource") to fetch file:// subresources from it, base_url/<base> tag
    notwithstanding. Verified empirically: with a file:// base_url, both the
    .ttf files and a file:// logo URI failed to load and PDF text fell back
    to Arial. Data URIs sidestep the restriction entirely since there is no
    network/file fetch involved.
    """
    def repl(m: re.Match) -> str:
        return f"url({_data_uri(_ASSETS_DIR / m.group(2), 'font/ttf')})"
    return _FONT_URL_RE.sub(repl, css_text)


def _build_html(game_id: int, pitcher_id: int) -> str:
    """Render the report template to an HTML string (no PDF/Playwright step).

    Split out from build_pitcher_postgame so the assembled Jinja context can
    be exercised in tests without launching headless Chromium.
    """
    df = P.game_pitches(game_id, pitcher_id)
    if df.empty:
        raise ReportDataError(f"No pitches for game_id={game_id}, pitcher_id={pitcher_id}")

    context = P.game_context(game_id)
    recent = P.recent_outings(pitcher_id, game_id, n=5)
    trend = P.velo_trend(pitcher_id)

    # Render every chart inside one headless-Chrome session (see charts.py) so
    # the ~9 figures don't each cold-start Chrome (~30s -> ~5s for the batch).
    with rendering_session():
        charts = {
            "velo_inning": fig_to_data_uri(P.fig_velo_by_inning(df)),
            "velo_pitch": fig_to_data_uri(P.fig_velo_by_pitch(df)),
            "movement": fig_to_data_uri(P.fig_movement(df)),
            "location": fig_to_data_uri(P.fig_location(df)),
            "velo_trend": fig_to_data_uri(P.fig_velo_trend(trend)),
            "location_split": fig_to_data_uri(P.fig_location_split(df)),
            "heatmap_overall": fig_to_data_uri(P.fig_heatmap_overall(df)),
        }
        heatmaps = [(label, fig_to_data_uri(fig))
                    for label, fig in P.fig_heatmaps_by_pitch_type(df)]

    # Each side's `usage` is a DataFrame from pitch_usage(); the template
    # iterates it as records, so convert here (mirrors every other table).
    splits = {
        side: {"overall": v["overall"], "usage": v["usage"].to_dict("records")}
        for side, v in P.splits_by_batter_side(df).items()
    }

    css = _inline_fonts((_STATIC / "report.css").read_text(encoding="utf-8"))
    assets = {"lmu_png": _data_uri(_ASSETS_DIR / "lmu.png", "image/png")}

    return _env.get_template("pitcher_postgame.html").render(
        pitcher=P.pitcher_name(pitcher_id),
        context=context,
        overall=P.game_overall_line(df),
        characteristics=P.pitch_characteristics(df).to_dict("records"),
        usage=P.pitch_usage(df).to_dict("records"),
        zone=P.zone_location(df).to_dict("records"),
        splits=splits,
        averages=P.averages_last5(recent).to_dict("records"),
        charts=charts,
        heatmaps=heatmaps,
        css=css,
        assets=assets,
    )


def _cache_path(game_id: int, pitcher_id: int, version: str) -> Path:
    safe = re.sub(r"[^0-9A-Za-z._-]", "_", version)
    return _CACHE_DIR / f"pitcher_{pitcher_id}_game_{game_id}_{safe}.pdf"


def build_pitcher_postgame(game_id: int, pitcher_id: int) -> bytes:
    # Serve a cached PDF when one exists for this exact data version. The
    # version token advances when the pitcher gets new data, so a cached report
    # can never show a stale season velo-trend — it just rebuilds.
    version = P.report_data_version(pitcher_id)
    cache_file = _cache_path(game_id, pitcher_id, version)
    if cache_file.exists():
        return cache_file.read_bytes()

    html = _build_html(game_id, pitcher_id)
    # No base_url needed: fonts and the logo are inlined as data: URIs
    # (see _inline_fonts docstring), and chart images already are too.
    pdf = html_to_pdf(html)

    try:  # cache is best-effort; a write failure must not fail the download
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(pdf)
    except OSError:
        pass
    return pdf
