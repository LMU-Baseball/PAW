import importlib
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"


def test_report_dependencies_importable():
    assert importlib.util.find_spec("playwright.sync_api") is not None
    assert importlib.util.find_spec("kaleido") is not None


def test_report_assets_present():
    reports = APP / "static" / "reports"
    assert (reports / "lmu.png").exists()
    assert (reports / "Teko-Regular.ttf").exists()


def test_html_to_pdf_returns_pdf_bytes():
    from app.reports.pdf import html_to_pdf
    out = html_to_pdf("<html><body><h1>Hello PAW</h1></body></html>")
    assert isinstance(out, bytes)
    assert out[:5] == b"%PDF-"
    assert len(out) > 1000


def test_with_base_injects_into_existing_head():
    from app.reports.pdf import _with_base
    out = _with_base(
        "<html><head><title>x</title></head><body>hi</body></html>",
        "https://example.com/assets/",
    )
    assert '<base href="https://example.com/assets/">' in out
    # Injected inside <head>, before the title, not in the body.
    head = out[out.index("<head") : out.index("</head>")]
    assert '<base href="https://example.com/assets/">' in head


def test_with_base_ignores_header_tag_in_body():
    from app.reports.pdf import _with_base
    # No real <head>; a <header> element lives in the body. The base tag must
    # NOT be injected after <header> -- a synthetic <head> is created instead.
    out = _with_base(
        "<html><body><header>Report</header><p>hi</p></body></html>",
        "https://example.com/assets/",
    )
    assert '<base href="https://example.com/assets/">' in out
    # The base/head must appear before the <header> element, not inside it.
    assert out.index("<base") < out.index("<header>")
    assert "<head>" in out


def test_with_base_escapes_url():
    from app.reports.pdf import _with_base
    out = _with_base("<html><head></head><body></body></html>", 'x"><script>')
    assert '"><script>' not in out
    assert "&quot;&gt;&lt;script&gt;" in out


def test_with_base_noop_when_none():
    from app.reports.pdf import _with_base
    html = "<html><head></head><body>hi</body></html>"
    assert _with_base(html, None) == html


def test_fig_to_data_uri_embeds_png():
    import base64
    import plotly.graph_objects as go
    from app.reports.charts import fig_to_data_uri

    fig = go.Figure(go.Scatter(x=[1, 2, 3], y=[3, 1, 2]))
    uri = fig_to_data_uri(fig, width=300, height=200)
    assert uri.startswith("data:image/png;base64,")
    raw = base64.b64decode(uri.split(",", 1)[1])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
