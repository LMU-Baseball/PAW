"""Shared Dash shell: brand index_string, crimson header, constants, section helper.

A Dash page does not extend base.html, so the site's grey+palms background and
lion favicon live here (hardcoded — a Dash index_string cannot read base.html CSS
tokens; keep in sync with the site brand). See Memory §3c. This is the single
source for these values across ALL Dash dashboards (hitting, pitching, ...).
"""
from __future__ import annotations

from dash import html
from flask_login import current_user

CRIMSON = "#9A0021"
BANNER = "rgba(154,0,33,0.82)"
PHOTO_PLACEHOLDER = "/static/reports/lion.png"

_INDEX_STRING = """<!DOCTYPE html>
<html>
<head>
{%metas%}
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{%title%}</title>
<link rel="icon" type="image/png" href="/static/reports/lion.png">
{%css%}
<style>
  @font-face {
    font-family: "Teko"; font-weight: 400; font-display: swap;
    src: url("/static/reports/Teko-Regular.ttf") format("truetype");
  }
  @font-face {
    font-family: "Teko"; font-weight: 600; font-display: swap;
    src: url("/static/reports/Teko-SemiBold.ttf") format("truetype");
  }
  @font-face {
    font-family: "Teko"; font-weight: 700; font-display: swap;
    src: url("/static/reports/Teko-Bold.ttf") format("truetype");
  }
  @font-face {
    font-family: "Alfa Slab One"; font-weight: 400; font-display: swap;
    src: url("/static/brand/AlfaSlabOne-Regular.ttf") format("truetype");
  }
  @font-face {
    /* Kaushan Script (OFL), same file the Competitive Cauldron banner embeds
       into its SVG -- registered here as a normal page font too so any
       regular HTML text (not just an SVG wordmark) can use an aggressive
       cursive/script look, e.g. Built on the Bluff's page title. */
    font-family: "Cauldron Script"; font-weight: 400; font-display: swap;
    src: url("/static/brand/CauldronScript.ttf") format("truetype");
  }
  body {
    margin: 0; min-height: 100vh;
    background-color: #f5f5f5;
    background-image: url('/static/brand/palms-grey.png');
    background-repeat: no-repeat; background-position: center bottom;
    background-size: cover; background-attachment: fixed;
    font-family: 'Teko', sans-serif;
  }
  /* Dashboard shell (hitting/pitching/bullpen/catching/HitTrax practice):
     sidebar (player photo/KPIs) as one left column, filters and the
     tab/visuals area stacked in a right column -- as a grid (not flex) so
     phone can independently reorder title -> filters -> player info ->
     visuals below, rather than only being able to swap two flex items. See
     .paw-splash-grid below for the same technique on Built on the Bluff. */
  .paw-dash-row {
    display: grid;
    grid-template-areas: "sidebar filters" "sidebar content";
    align-items: start;
    gap: 16px;
    padding: 16px;
  }
  .paw-dash-sidebar { grid-area: sidebar; }
  .paw-dash-filters { grid-area: filters; }
  .paw-dash-content { grid-area: content; }
  /* Phone-only overrides (tablet/laptop/desktop untouched). Banner
     crest/title get a touch smaller so the branded headers don't overflow a
     narrow box. */
  @media (max-width: 720px) {
    /* Coach wants: title, then filters (what to pick), then player
       info/KPIs, then the visuals -- a phone showing the same order the
       page defaults to on the way down. */
    .paw-dash-row {
      grid-template-columns: 1fr !important;
      grid-template-areas: "filters" "sidebar" "content" !important;
    }
    /* A CSS Grid item defaults to min-width:auto -- it refuses to shrink
       below its content's natural width. A wide DataTable or chart inside
       .paw-dash-content (e.g. the bullpen Session Detail stats table, 14
       columns) was dragging the WHOLE grid row out past the viewport,
       which is what actually causes a phone to auto-zoom the entire page
       out to fit rather than just that one table -- overflowX:auto on the
       table itself doesn't help without this, since there was never a
       width constraint on its ancestors for that scrolling to kick in
       against. Mirrors the same fix already applied to .paw-video-media/
       .paw-video-table below. */
    .paw-dash-sidebar, .paw-dash-filters, .paw-dash-content { min-width: 0 !important; }
    .paw-banner-crest { height: 72px !important; }
    .paw-banner-title { font-size: 20px !important; letter-spacing: 4px !important; }
    /* Site header: let the user-info block drop to its own row instead of
       squeezing the wordmark into a mid-word wrap. */
    .paw-header { flex-wrap: wrap; height: auto !important; min-height: 64px;
                  row-gap: 4px; padding: 10px 14px !important; }
    .paw-header-user { width: 100%; text-align: right; font-size: 12px !important; }
    .paw-header-brand-text { font-size: 22px !important; }
    /* Video tab: clip above the pitch table instead of a forced side-by-side
       row that needs horizontal scrolling to see either one. */
    .paw-video-row { flex-direction: column !important; }
    .paw-video-media, .paw-video-table { min-width: 0 !important; width: 100%; }
    /* Chart pairs (movement+location, spray+radial, etc.): one full-width
       chart per row instead of two squeezed side by side -- scrolling to see
       the second one beats both being unreadable. */
    .paw-chart-row { flex-direction: column !important; }
    .paw-chart-row > * { min-width: 0 !important; }
    .paw-chart-grid { grid-template-columns: 1fr !important; }
    .paw-chart-grid > * { min-width: 0 !important; }
    /* Built on the Bluff's 3-area grid (profile/center/right -- see
       app.dashboards.splash_report.layout.render_from_data, 2026-09-14
       right-wall layout test): a phone gets an explicit single-column
       stacking order instead of the desktop's 3-column row, since a coach
       wants player photo/stats to lead, then the throwing checklists +
       scripts, then the skeleton visuals + Building the Engine + Gas
       Station. */
    .paw-splash-grid {
      grid-template-columns: 1fr !important;
      grid-template-areas: "profile" "center" "right" !important;
    }
    .paw-splash-grid > * { min-width: 0 !important; }
  }
  /* DataTable dropdown-presentation cells (Competitive Cauldron's Team/
     Captain columns, Built on the Bluff's script-type/pitch-design
     dropdowns): react-select's own bundled CSS sets `.Select { overflow:
     hidden }` unconditionally -- meant to clip the CLOSED control's own
     display value, but it also clips `.Select-menu-outer`, the open
     dropdown's popup, since that popup is an absolutely-positioned CHILD of
     this same `.Select` div. A dropdown cell near the bottom of a table (or
     the last row) then shows its "x"/caret as open but renders NONE of its
     option list -- 2026-09-27, Brad screenshot: "I cannot see the entire
     dropdown at the bottom." Scoped to `.is-open` only, so a CLOSED
     dropdown's own overflow-clipped display value is untouched. */
  .Select.is-open { overflow: visible !important; }
  /* Same clipping bug, a layer further out -- and a real CSS limitation, not
     just a missing override. dash_table's internal `.dash-spreadsheet-
     container` sets `overflow-x: auto` (for wide tables' own horizontal
     scrollbar) and, since 2026-09-27, ALSO tries setting `overflow-y:
     visible !important` itself the moment a dropdown opens (Dash's own
     attempted fix for this exact bug) -- but per the CSS Overflow spec, "if
     one of overflow-x/overflow-y is visible and the other is not, the
     visible one computes to auto instead" (https://developer.mozilla.org/
     en-US/docs/Web/CSS/overflow). Any overflow-x:auto element is therefore
     UNABLE to ever have a real visible overflow-y, no matter how strongly
     it's forced -- confirmed live: even `element.style.setProperty
     ('overflow-y','visible','important')` from devtools still computed to
     "auto" while overflow-x stayed "auto". The only way out is for THIS
     element to give up its own horizontal scrollbar (both axes visible, so
     nothing here clips a dropdown popup in either direction); a wide grid
     just overflows into the page's own horizontal scroll instead of a
     nested one -- see grid.py's matching style_table (overflowX now
     "visible" too, not "auto") for the outer `.dash-table-container` layer
     of the same fix. 2026-09-27, Brad screenshot: "I cannot see the entire
     dropdown at the bottom." */
  .dash-spreadsheet-container { overflow: visible !important; }
</style>
</head>
<body>
{%app_entry%}
<footer>{%config%}{%scripts%}{%renderer%}</footer>
</body>
</html>"""


def index_string() -> str:
    return _INDEX_STRING


def header(back_href: str | None = None, back_label: str | None = None) -> html.Div:
    """Site header (matches base.html): logo -> home, wordmark, optional back-link,
    user + logout."""
    brand_children = [
        html.Img(src="/static/reports/lmu.png",
                 style={"height": "40px", "width": "auto", "display": "block"}),
        html.Span("The Paw", className="paw-header-brand-text", style={
            "fontFamily": "Teko, sans-serif", "fontWeight": "700", "fontSize": "30px",
            "lineHeight": "1", "letterSpacing": "1px", "textTransform": "uppercase",
            "color": "#fff", "whiteSpace": "nowrap"}),
    ]
    brand = html.A(brand_children, href="/",
                   style={"display": "flex", "alignItems": "center", "gap": "12px",
                          "textDecoration": "none"})
    left = [brand]
    if back_href:
        left.append(html.A(back_label or "← Back", href=back_href, style={
            "color": "#fff", "textDecoration": "underline", "fontSize": "14px",
            "marginLeft": "18px"}))
    right = html.Span()
    if current_user.is_authenticated:
        # Change-password link is coach-only (the player login is shared).
        pw_link = ([html.A("Change password", href="/change-password",
                           style={"color": "#fff", "textDecoration": "underline"}),
                    " · "] if getattr(current_user, "is_coach", False) else [])
        right = html.Span([
            f"{current_user.name} · {current_user.role} · ",
            *pw_link,
            # Unlike base.html's .logout-btn (which uses color: inherit because
            # its sibling links also inherit), this header sets literal #fff
            # on both "Change password" and "Log out" -- keep them matching.
            html.Form(
                [html.Button("Log out", type="submit", style={
                    "textDecoration": "underline",
                    "background": "none", "border": "none", "padding": "0",
                    "cursor": "pointer", "font": "inherit", "color": "#fff",
                })],
                action="/logout", method="POST",
                style={"display": "inline"},
            ),
        ], className="paw-header-user", style={"fontSize": "14px", "color": "rgba(255,255,255,.85)"})
    return html.Div([html.Div(left, style={"display": "flex", "alignItems": "center"}),
                     right], className="paw-header", style={
        "background": BANNER, "color": "#fff", "padding": "0 20px", "height": "64px",
        "display": "flex", "alignItems": "center", "justifyContent": "space-between",
        "boxShadow": "0 2px 8px rgba(0,0,0,.15)"})


def section(title: str) -> html.H3:
    return html.H3(title, style={"color": CRIMSON})


BLUE = "#0076A5"  # site brand blue (base.html --blue)


def _btn_style(bg: str) -> dict:
    return {"backgroundColor": bg, "color": "#fff", "border": "none",
            "borderRadius": "4px", "padding": "10px 26px", "fontWeight": "bold",
            "fontSize": "15px", "cursor": "pointer", "textTransform": "uppercase",
            "letterSpacing": "1px"}


def edit_save_buttons(edit_id: str, save_id: str, status_id: str,
                      extra: list | None = None) -> html.Div:
    """A centered row of coach controls: an "Edit" button (unlocks the grid),
    a "Save" button (persists + re-locks), any `extra` buttons, and a status
    line beneath. Shared by the velo board and cauldron so both read the same.
    The Edit/Save wiring (toggling the grid's `editable`) lives in each board's
    callbacks."""
    row = [
        html.Button("Edit", id=edit_id, n_clicks=0, style=_btn_style(BLUE)),
        html.Button("Save", id=save_id, n_clicks=0, style=_btn_style(CRIMSON)),
    ]
    if extra:
        row.extend(extra)
    return html.Div([
        html.Div(row, style={"display": "flex", "justifyContent": "center",
                             "gap": "12px", "flexWrap": "wrap"}),
        html.Div(id=status_id, style={"color": CRIMSON, "fontSize": "14px",
                                      "fontWeight": "bold", "marginTop": "8px"}),
    ], style={"padding": "14px 16px 20px", "textAlign": "center"})
