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
    # SP5 additions now on the bullpen report: header metrics, freq bar, callout.
    assert "STRIKE%" in html and "MAX MPH" in html
    assert "freq-bar" in html          # pitch-frequency stacked bar image
    assert "fb-callout" in html        # fastball callout (GEIS throws a fastball)


def test_bullpen_cache_key_includes_code_version():
    from app.reports import bullpen_report as BR
    p = BR._cache_path(824645, "2026-05-13", "2026-05-13")
    assert BR._CODE_VERSION in p.name
