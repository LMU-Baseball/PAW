"""Login-protected HitTrax Practice dashboard (Flask + Dash)."""
from dash import Dash

from app.dashboards.hitting_practice.index import INDEX_STRING
from app.dashboards.hitting_practice import layout

__all__ = ["build_hitting_practice_dash", "INDEX_STRING"]


def build_hitting_practice_dash(server) -> Dash:
    dash_app = Dash(
        __name__,
        server=server,
        url_base_pathname="/dash/hitting-practice/",
        suppress_callback_exceptions=True,
        title="Practice (HitTrax) — The PAW",
    )
    dash_app.index_string = INDEX_STRING
    dash_app.layout = layout.serve_layout

    from app.dashboards.hitting_practice import callbacks
    callbacks.register_callbacks(dash_app)
    return dash_app
