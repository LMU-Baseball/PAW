"""Minimal login-protected Hitting dashboard (placeholder).

Wires one live data element (the logged-in context + a game/player selector) to
prove the auth + data layers reach Dash. The full visual build comes later.
"""
from dash import Dash, html
from flask_login import current_user


def build_hitting_dash(server) -> Dash:
    dash_app = Dash(
        __name__,
        server=server,
        url_base_pathname="/dash/hitting/",
        suppress_callback_exceptions=True,
        title="Hitting — The PAW",
    )

    # Dash renders its own HTML shell (it does not extend base.html), so mirror
    # the site's lion favicon + full-page light-crimson palms background here.
    dash_app.index_string = """<!DOCTYPE html>
<html>
<head>
{%metas%}
<title>{%title%}</title>
<link rel="icon" type="image/png" href="/static/reports/lion.png">
{%css%}
<style>
  body {
    margin: 0; min-height: 100vh;
    background-color: #f5dfe3;
    background-image: url('/static/brand/palms-crimson.png');
    background-repeat: no-repeat; background-position: center bottom;
    background-size: cover; background-attachment: fixed;
  }
</style>
</head>
<body>
{%app_entry%}
<footer>{%config%}{%scripts%}{%renderer%}</footer>
</body>
</html>"""

    def serve_layout():
        # Rendered per request, so current_user reflects the logged-in user.
        if not current_user.is_authenticated:
            return html.Div("Please log in.")
        role = current_user.role
        scope = ("You can view every LMU hitter."
                 if current_user.is_coach
                 else f"You can view your own data (Trackman id {current_user.trackman_id}).")
        return html.Div(
            style={"fontFamily": "sans-serif", "padding": "24px"},
            children=[
                html.H2("Hitting Dashboard"),
                html.P(f"Signed in as {current_user.name} ({role}). {scope}"),
                html.P("Analytics backend is ready; visualizations are under "
                       "construction (pending brand assets)."),
                html.A("← Back to home", href="/"),
            ],
        )

    dash_app.layout = serve_layout
    return dash_app
