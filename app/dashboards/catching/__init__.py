"""Login-protected Catching game-stats dashboard (Flask + Dash)."""
from dash import Dash

from app.dashboards.catching.index import INDEX_STRING
from app.dashboards.catching import layout

__all__ = ["build_catching_dash", "INDEX_STRING"]


def build_catching_dash(server) -> Dash:
    dash_app = Dash(
        __name__,
        server=server,
        url_base_pathname="/dash/catching/",
        suppress_callback_exceptions=True,
        compress=True,
        title="Catching — The PAW",
    )
    dash_app.index_string = INDEX_STRING
    dash_app.layout = layout.serve_layout

    from app.dashboards.catching import callbacks
    callbacks.register_callbacks(dash_app)
    return dash_app
