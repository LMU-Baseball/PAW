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


def test_bullpen_report_html_has_new_elements():
    from app.reports import bullpen_report as BR
    pid, date = _session()
    html = BR._build_html(pid, date)
    # SP5 additions now on the bullpen report: header metrics, freq donut, callout.
    assert "STRIKE%" in html and "MAX MPH" in html
    assert 'alt="Pitch Frequency"' in html  # pitch-frequency donut image
    assert "fb-callout" in html        # fastball callout (GEIS throws a fastball)


def test_bullpen_report_layout_is_three_two_col_rows():
    """Page 1 restructure: stats table + donut, location + velo, movement + release."""
    from app.reports import bullpen_report as BR
    pid, date = _session()
    html = BR._build_html(pid, date)
    assert html.count('class="grid2"') == 3
    assert "freq-bar" not in html
    assert 'class="grid3"' not in html
    stats_idx = html.index("Stats by pitch type")
    location_idx = html.index('alt="Location"')
    velo_idx = html.index('alt="Velocity"')
    movement_idx = html.index('alt="Movement"')
    release_idx = html.index('alt="Release"')
    assert stats_idx < location_idx < velo_idx < movement_idx < release_idx


def test_bullpen_cache_key_includes_code_version():
    from app.reports import bullpen_report as BR
    p = BR._cache_path(824645, "2026-05-13", "2026-05-13")
    assert BR._CODE_VERSION in p.name
