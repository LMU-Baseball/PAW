"""Assemble the pitcher postgame PDF from warehouse data + the report engine."""
from __future__ import annotations

import base64
import os
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.data import pitching as P
from app.reports.pdf import html_to_pdf
from app.reports import plots
from app.reports.report_goals import apply_goals

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
    """Render the one-page pitcher report to an HTML string (no PDF step)."""
    df = P.game_pitches(game_id, pitcher_id)
    if df.empty:
        raise ReportDataError(f"No pitches for game_id={game_id}, pitcher_id={pitcher_id}")

    # Postgame reports are for LMU pitchers only. Opponents are already hidden
    # from the picker; this guards the direct-URL path too.
    teams = set(df["pitcher_team"].dropna())
    if teams and P.LMU_PITCHER_TEAM not in teams:
        raise ReportDataError(
            f"pitcher_id={pitcher_id} in game_id={game_id} is not an LMU pitcher "
            f"(team {teams}); reports are LMU-only")

    context = P.game_context(game_id)
    # Handedness from the pitcher's throwing side; fall back to RHP.
    hand = "RHP"
    if "pitcher_throws" in df.columns:
        side = str(df["pitcher_throws"].dropna().iloc[0]) if df["pitcher_throws"].notna().any() else ""
        hand = "LHP" if side.lower().startswith("l") else "RHP"

    charts = {
        "zone_rhh": plots.zone_chart_uri(df, "Right", "vRHH Zone"),
        "movement": plots.movement_map_uri(df, "Movement Map"),
        "zone_lhh": plots.zone_chart_uri(df, "Left", "vLHH Zone"),
        "pitch_usage_donuts": plots.pitch_usage_donuts_uri(df),
    }

    usage = P.pitch_usage_table(df)
    movement = P.movement_summary(df)
    df = df.copy()
    df["_pt"] = P.pitch_type(df)
    fastball = P.fastball_callout(df, pt_col="_pt")
    # Color key for the tables. The charts dropped their legends (they hid data),
    # so the colored pitch-type names in the tables ARE the legend.
    pitch_colors = {r["pitch"]: plots.color_for(r["pitch"])
                    for r in (*usage, *movement)}

    css = _inline_fonts((_STATIC / "report.css").read_text(encoding="utf-8"))
    assets = {
        "lmu_png": _data_uri(_ASSETS_DIR / "lmu.png", "image/png"),
        "lion_png": _data_uri(_ASSETS_DIR / "lion-white.png", "image/png"),
    }

    return _env.get_template("pitcher_onepager.html").render(
        pitcher=P.pitcher_name(pitcher_id),
        hand=hand,
        context=context,
        line=P.header_stat_line(df),
        process=apply_goals(P.process_metrics(df)),
        outcome=apply_goals(P.outcome_metrics(df)),
        usage=usage,
        movement=movement,
        pitch_colors=pitch_colors,
        charts=charts,
        fastball=fastball,
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
