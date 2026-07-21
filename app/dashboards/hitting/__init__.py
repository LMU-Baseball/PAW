"""Login-protected Hitting dashboard (Flask + Dash).

Package layout:
  index.py       the Dash HTML shell (background + favicon)
  selectors.py   role-aware hitter/game options + batter resolution
  charts.py      Plotly figures (strike-zone scatter, all-PAs facet)
  tables.py      Dash DataTable builders
  tabs/          per-tab render() functions (pure: df -> components)
  callbacks.py   selection -> data stores -> tab content
"""
from dash import Dash

from app.dashboards.hitting.index import INDEX_STRING
from app.dashboards.hitting import layout

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
    dash_app.layout = layout.serve_layout
    return dash_app
