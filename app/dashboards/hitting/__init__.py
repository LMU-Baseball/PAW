"""Login-protected Hitting dashboard (Flask + Dash).

Package layout:
  index.py       the Dash HTML shell (background + favicon)
  selectors.py   role-aware hitter/game options + batter resolution
  charts.py      Plotly figures (strike-zone scatter, all-PAs facet)
  tables.py      Dash DataTable builders
  tabs/          per-tab render() functions (pure: df -> components)
  callbacks.py   selection -> data stores -> tab content
"""
from dash import Dash, html
from flask_login import current_user

from app.dashboards.hitting.index import INDEX_STRING

__all__ = ["build_hitting_dash", "INDEX_STRING"]


def build_hitting_dash(server) -> Dash:
    dash_app = Dash(
        __name__,
        server=server,
        url_base_pathname="/dash/hitting/",
        suppress_callback_exceptions=True,
        title="Hitting — The PAW",
    )
    dash_app.index_string = INDEX_STRING

    def serve_layout():
        # Placeholder until Task 9 wires the real shell.
        if not current_user.is_authenticated:
            return html.Div("Please log in.")
        return html.Div(
            style={"padding": "24px"},
            children=[html.H2("Hitting Dashboard"),
                      html.A("← Back to home", href="/")],
        )

    dash_app.layout = serve_layout
    return dash_app
