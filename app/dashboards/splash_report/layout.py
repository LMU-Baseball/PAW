"""Built on the Bluff page shell: filters, sidebar, and the whole editable body.

Data is loaded ONCE per (player, season, cycle) into a `dcc.Store`
(`load_data` / `render_from_data`, wired up in `callbacks.py`) instead of on
every render -- toggling Edit used to re-run every read behind the page
(profile, KPIs, plan, engine metrics, gas station, scripts, script rows,
pen results) just to change how the SAME data is drawn, which was most of
why the Edit button felt slow. Edit now flips a client-side flag and
re-renders straight from the cached Store -- no new query at all.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
from dash import dcc, html
from flask_login import current_user

from app.data import pitching_caps, seasons, splash_report as SR
from app.dashboards import date_range as dr  # noqa: F401  (kept for parity w/ other shells)
from app.dashboards.pitching import selectors
from app.dashboards.shell import BLUE, CRIMSON, PHOTO_PLACEHOLDER, header, edit_save_buttons
from app.dashboards.splash_report import body_visual, charts, tables

# A crimson-tinted wash + thin top accent instead of a flat white box (2026-
# 09-10 planning session: "add color and gradients... similar to the Velo
# Board style") -- gradient stays translucent (same ballpark alpha as the
# old flat rgba) so the page's palm background still reads through between
# and across cards, it's just no longer a plain white panel. Padding/margin
# trimmed from the original 12px/16px to cut down the whitespace between
# cards ("eliminating as much white space as possible").

_CARD = {"background": "linear-gradient(160deg, rgba(255,255,255,0.92) 0%, "
                       "rgba(255,255,255,0.85) 55%, rgba(154,0,33,0.10) 100%)",
         "borderRadius": "8px", "borderTop": f"3px solid {CRIMSON}",
         "padding": "10px 12px", "marginBottom": "10px"}


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


# Round 1 of "add more colors... blue... make every box have a different
# look" (2026-09-11 feedback, explicitly a first pass to react to) -- five
# translucent corner-wash variants mixing CRIMSON and the site's BLUE
# (`shell.BLUE`). Still translucent (palm background shows through) and
# still light enough for dark text to stay legible; only `background` and
# `borderTop` vary, everything else in `_CARD` (radius/padding/margin)
# stays constant across variants.
_CARD_VARIANTS = [
    {"background": f"linear-gradient(160deg, rgba(255,255,255,0.92) 0%, "
                   f"rgba(255,255,255,0.85) 55%, {_rgba(CRIMSON, 0.14)} 100%)",
     "borderTop": f"3px solid {CRIMSON}"},
    {"background": f"linear-gradient(200deg, rgba(255,255,255,0.92) 0%, "
                   f"rgba(255,255,255,0.85) 55%, {_rgba(BLUE, 0.18)} 100%)",
     "borderTop": f"3px solid {BLUE}"},
    {"background": f"linear-gradient(15deg, {_rgba(CRIMSON, 0.12)} 0%, "
                   f"rgba(255,255,255,0.88) 45%, {_rgba(BLUE, 0.12)} 100%)",
     "borderTop": f"3px solid {CRIMSON}"},
    {"background": f"linear-gradient(340deg, rgba(255,255,255,0.92) 0%, "
                   f"rgba(255,255,255,0.85) 55%, {_rgba(BLUE, 0.16)} 100%)",
     "borderTop": f"3px solid {CRIMSON}"},
    {"background": f"linear-gradient(110deg, {_rgba(BLUE, 0.11)} 0%, "
                   f"rgba(255,255,255,0.88) 50%, {_rgba(CRIMSON, 0.16)} 100%)",
     "borderTop": f"3px solid {BLUE}"},
]

# Explicit per-card assignment (not a hash) so adjacent cards in the actual
# page layout never land on the same variant by coincidence -- checked by
# hand against checklists_grid's 3-row x 2-col arrangement and the sidebar's
# stacked cards. Matched by prefix since a couple of titles carry an
# interpolated suffix (e.g. "Bullpen Scripts · 6 Scripts"). Anything not
# listed falls back to a stable hash of its title, so a future/unlisted
# card still gets *a* variant rather than crashing or defaulting to plain.
_CARD_VARIANT_BY_PREFIX = [
    ("Pre-Throw Checklist", 0), ("Post-Throw Checklist", 1),
    ("Feet Set", 2), ("Feet Moving", 3),
    ("Work Day", 4), ("Recovery Protocols", 0),
    ("Player Training Goals", 1), ("Vision Statement", 3),
    ("Building the Engine", 2), ("Bullpen Scripts", 4),
    ("The Gas Station", 0),
]


def _variant_index(title: str) -> int:
    for prefix, idx in _CARD_VARIANT_BY_PREFIX:
        if title.startswith(prefix):
            return idx
    return sum(title.encode("utf-8")) % len(_CARD_VARIANTS)


_LABEL_STYLE = {"color": CRIMSON, "fontWeight": "bold", "fontSize": "13px",
                "textTransform": "uppercase", "letterSpacing": "1px",
                "display": "block", "marginBottom": "4px", "textAlign": "center"}
_TEXTAREA_STYLE = {"width": "100%", "minHeight": "80px", "padding": "8px",
                   "borderRadius": "8px", "fontFamily": "Teko, sans-serif",
                   "fontSize": "15px", "border": "1px solid #ccc"}


# 2026-09-13 planning session: top-level card headers get the same "white
# text on a translucent red/blue graffiti backdrop" treatment the Velo Board
# / Competitive Cauldron banners use, scaled down to a slim per-card strip
# (Brad confirmed top-level titles only -- a table's own sub-label, e.g.
# "Strength" on the engine tables, instead folds into that table's own red
# DataTable header bar; see `tables.engine_metrics_table`'s `label_header`).
# Only 2 backdrop images exist (velo-backdrop.png,
# cauldron-backdrop.png, both 1080x1080 with alpha already baked in) and
# Brad doesn't want the same 2 images reused identically everywhere, so each
# card gets a different crop (`backgroundPosition`) of the same source image
# -- pure CSS, no new image assets, same idiom as `_CARD_VARIANT_BY_PREFIX`
# below it (one variant per card index, so adjacent cards never match).
#
# Round 2 (Brad's screenshot feedback on round 1): rotating the backdrop hit
# a real cross-browser bug -- a `transform`-ed child inside a
# `border-radius` + `overflow:hidden` parent isn't reliably clipped to the
# rounded corners (worst on Safari/iOS, which is exactly what coaches/
# players use on mobile per `project-paw` memory), so some headers rendered
# with a corner poking past the rounded edge -- "not perfectly rectangular."
# Rotation is dropped entirely now; variety comes from `backgroundPosition`
# alone. Sizing switched from a fixed zoomed `backgroundSize` percentage
# (which stretched a SQUARE 1080x1080 source to a wide-short strip's
# unrelated aspect ratio -- both distorting it and, since the percentages
# were 200%+, sampling a small, blurry-looking slice of the source) to the
# `cover` keyword, which preserves the source's aspect ratio and scales it
# to just barely fill the strip -- sharper, undistorted, and every card uses
# the identical sizing rule so they're all genuinely "the same shape."
# Round 3 (Brad: "a bit more blue in the crops"): every header on this page
# is much WIDER than it is tall, against a SQUARE 1080x1080 source -- with
# `cover`, that means the image is always scaled to match the strip's WIDTH
# exactly (height is the excess dimension), so it always shows edge-to-edge
# at full width with NO horizontal crop at all -- the x half of
# `backgroundPosition` is a dead value here, it can't do anything. Only the
# y value actually pans. (Confirmed by rendering both PNGs through the same
# cover math offline before touching real percentages, rather than tuning
# blind against a browser again.) So variety + "more blue" now comes purely
# from y: velo-backdrop's blue lives in a vertical stripe that's ALWAYS
# visible along the strip's right ~15% (any y works; y just moves the
# paint-splatter pattern around it); cauldron-backdrop's blue is a
# horizontal band concentrated in its top ~10-15%, fading to solid crimson
# below that -- y needs to land inside roughly 0.05-0.09 to show a real
# red/blue blend instead of almost-solid blue (y<0.05) or almost-solid
# crimson (y>0.10).
_HEADER_IMAGES = ["/static/reports/velo-backdrop.png", "/static/reports/cauldron-backdrop.png"]
_HEADER_VARIANTS = [
    (0, "50% 5%"),    # velo -- strong blue splatter, upper band
    (1, "50% 7%"),    # cauldron -- balanced red/blue speckle
    (0, "50% 20%"),   # velo -- blue splatter concentrated on the right
    (1, "50% 8.5%"),  # cauldron -- balanced red/blue speckle, slightly redder
    (0, "50% 60%"),   # velo -- blue splatter through the middle
]


def _graffiti_header(text: str, idx: int) -> html.Div:
    img_idx, pos = _HEADER_VARIANTS[idx % len(_HEADER_VARIANTS)]
    # Solid color fallback (matching the image's dominant tone) so a slow/
    # failed image load never leaves the always-white label with nothing
    # behind it -- see the coaches' "header box disappears" report.
    fallback_color = BLUE if img_idx == 0 else CRIMSON
    label = html.Span(text, style={
        "color": "#fff", "fontWeight": "bold", "fontSize": "13px",
        "textTransform": "uppercase", "letterSpacing": "1px",
        "textShadow": "0 1px 3px rgba(0,0,0,0.65)",
    })
    return html.Div(label, style={
        "background": f"url({_HEADER_IMAGES[img_idx]}) {pos}/cover no-repeat {fallback_color}",
        "borderRadius": "6px", "padding": "6px 10px", "margin": "0 0 8px",
        "minHeight": "18px", "display": "flex", "alignItems": "center",
        "justifyContent": "center", "textAlign": "center",
    })


def _card(title: str, child, *, card_id=None, extra_style: dict | None = None) -> html.Div:
    idx = _variant_index(title)
    kwargs = {"style": {**_CARD, **_CARD_VARIANTS[idx], **(extra_style or {})}}
    if card_id:
        kwargs["id"] = card_id
    return html.Div([_graffiti_header(title, idx), child], **kwargs)


def _lines(text: str) -> list[str]:
    return [ln.strip() for ln in (text or "").split("\n") if ln.strip()]


def _bullet_view(text: str, empty_msg: str = "Nothing entered yet.",
                 video_by_title: dict | None = None) -> html.Div:
    """One `<li>` per line; a line that matches a video's title (exact
    match, same idiom as `tables.gas_station_table`'s exercise-to-video
    matching) renders as a clickable link to that video instead of plain
    text -- used by `_drill_section` for the Feet Set/Feet Moving/Work Day
    catalog (see `app.data.splash_report.VIDEO_CATEGORIES`'s "Drills"
    category)."""
    items = _lines(text)
    if not items:
        return html.Div(empty_msg, style={"color": "#888", "fontStyle": "italic"})
    video_by_title = video_by_title or {}

    def _item(x):
        video = video_by_title.get(x)
        if video and video.get("link_url"):
            return html.Li(html.A(x, href=video["link_url"], target="_blank",
                                  rel="noopener",
                                  style={"color": CRIMSON, "textDecoration": "underline"}))
        return html.Li(x)

    return html.Ul([_item(x) for x in items], style={"margin": "0", "paddingLeft": "18px"})


def _text_section(title: str, text: str, *, editable: bool, input_id: str) -> html.Div:
    """Pre-Throw/Post-Throw checklist + Vision Statement + Player Training
    Goals: free-text bulleted notes (one bullet per line)."""
    child = dcc.Textarea(id=input_id, value=text, style=_TEXTAREA_STYLE) \
        if editable else _bullet_view(text)
    return _card(title, child)


def _drill_catalog_controls(section_key: str, drill_options: list[str]) -> html.Div:
    """Compact add/remove row directly under a drill dropdown -- 2026-09-10
    feedback: the catalog add/remove needs to live right at the dropdown,
    not in a separate whole section. `section_key` (one of "feetset" /
    "feetmoving" / "workday") tags the pattern-matching ids so ONE pair of
    callbacks (`_on_drill_catalog_add`/`_on_drill_catalog_remove` in
    callbacks.py, keyed by dash.MATCH) serves all three instances instead
    of tripling the callback code -- they all write to the SAME shared
    catalog (`app.data.splash_report.read_drill_options` et al), so an add
    or remove made from any one of the three shows up in all three after
    the next data refresh."""
    field_style = {"padding": "4px 6px", "borderRadius": "6px", "border": "1px solid #ccc",
                   "fontSize": "12px", "fontFamily": "Teko, sans-serif"}
    return html.Div([
        dcc.Input(id={"type": "splash-drill-add-input", "index": section_key}, type="text",
                 placeholder="Add a drill...", style={**field_style, "width": "130px"}),
        html.Button("+", id={"type": "splash-drill-add-btn", "index": section_key}, n_clicks=0,
                   title="Add to the shared drill catalog",
                   style={"border": "none", "background": CRIMSON, "color": "#fff",
                          "borderRadius": "6px", "padding": "3px 10px", "marginLeft": "4px",
                          "cursor": "pointer", "fontSize": "13px"}),
        dcc.Dropdown(id={"type": "splash-drill-remove-select", "index": section_key},
                    placeholder="Remove from catalog...",
                    options=[{"label": v, "value": v} for v in drill_options],
                    style={"width": "170px", "display": "inline-block",
                          "verticalAlign": "middle", "marginLeft": "8px",
                          "fontFamily": "Teko, sans-serif", "fontSize": "12px"}),
        html.Button("Remove", id={"type": "splash-drill-remove-btn", "index": section_key},
                   n_clicks=0, title="Remove this drill from the shared catalog",
                   style={"border": "none", "background": "none", "color": CRIMSON,
                          "cursor": "pointer", "fontSize": "12px", "marginLeft": "4px",
                          "textDecoration": "underline"}),
        html.Div(id={"type": "splash-drill-status", "index": section_key},
                style={"fontSize": "11px", "color": CRIMSON, "marginTop": "2px", "flexBasis": "100%"}),
    ], style={"display": "flex", "flexWrap": "wrap", "alignItems": "center", "gap": "2px",
             "marginTop": "6px"})


def _drill_section(title: str, text: str, *, editable: bool, is_coach: bool, dd_id: str,
                   section_key: str, drill_options: list[str],
                   drill_videos: list[dict] | None = None) -> html.Div:
    """Feet Set/Feet Moving/Work Day: a multi-select catalog (the coaches'
    real drill list), not free text. `drill_options` comes from
    `app.data.splash_report.read_drill_options()` (coach-managed via the
    inline add/remove row -- `_drill_catalog_controls`, directly below the
    dropdown -- rather than a separate section), loaded once in `load_data`
    rather than queried here so this render stays a pure function of
    `data`. dcc.Dropdown is searchable by typing out of the box, satisfying
    "type-to-search" with no extra code.

    `drill_videos` (2026-09-22, `videos["Drills"]` from `load_data`): a
    selected drill whose name matches a video's title renders as a
    clickable Google-Drive link in the read-only view, same idiom as
    `tables.gas_station_table`'s exercise column -- see `_bullet_view`."""
    if editable:
        dropdown = dcc.Dropdown(
            id=dd_id, multi=True, value=_lines(text),
            options=[{"label": v, "value": v} for v in drill_options],
            style={"fontFamily": "Teko, sans-serif"})
        child = html.Div([dropdown, _drill_catalog_controls(section_key, drill_options)]) \
            if is_coach else dropdown
    else:
        video_by_title = {v["title"]: v for v in (drill_videos or [])}
        child = _bullet_view(text, video_by_title=video_by_title)
    return _card(title, child)


# =============================== VIDEO LIBRARY ===============================
# Shared Recovery Protocols / Gas Station titled-link video library (2026-09-10
# planning session): coach-managed, shown to every player rather than curated
# per plan. See app.data.splash_report.VIDEO_CATEGORIES/list_videos/add_video.

_VIDEO_LINK_STYLE = {"color": CRIMSON, "textDecoration": "underline", "cursor": "pointer",
                     "fontFamily": "Teko, sans-serif", "fontSize": "15px",
                     "padding": "2px 0", "textAlign": "left", "display": "block",
                     "border": "none", "background": "none"}


def _video_link(video: dict) -> html.Div:
    """A link-based video (`link_url` set -- e.g. a Google Drive share link,
    2026-09-16: Brad confirmed these open in a new tab, no inline embedding
    to build) is a plain anchor; an uploaded one pops the shared modal
    (`video_modal`/`_on_video_modal` in callbacks.py) instead, since its
    bytes stream from this app's own `/splash-video/<id>` route."""
    if video.get("link_url"):
        child = html.A(f"↗ {video['title']}", href=video["link_url"], target="_blank",
                       rel="noopener", style=_VIDEO_LINK_STYLE)
    else:
        child = html.Button(f"▶ {video['title']}",
                            id={"type": "splash-video-open", "index": video["id"]},
                            n_clicks=0, style=_VIDEO_LINK_STYLE)
    return html.Div(child, style={"display": "block"})


def video_list_or_empty(videos: list[dict]) -> html.Div:
    """A titled-link list for one category (Recovery Protocols or Gas
    Station Videos) -- click an uploaded video's title to pop it up in the
    shared modal; a link-based one (see `_video_link`) opens in a new tab
    instead, never an embedded player inline on the page either way."""
    if not videos:
        return html.Div("No videos yet.", style={"color": "#888", "fontStyle": "italic"})
    return html.Div([_video_link(v) for v in videos])


def video_modal() -> html.Div:
    """One shared popup for every titled video link on the page (Recovery
    Protocols + Gas Station) -- opened by `{"type": "splash-video-open"}`
    clicks, closed by its own × button. Hidden (`display: none`) until a
    click sets its Source `src`."""
    return html.Div(
        html.Div([
            html.Div([
                html.Span(id="splash-video-modal-title", style={"fontWeight": "bold",
                                                                 "color": "#fff"}),
                html.Button("✕", id="splash-video-modal-close", n_clicks=0,
                           style={"border": "none", "background": "none", "color": "#fff",
                                  "fontSize": "18px", "cursor": "pointer", "float": "right"}),
            ], style={"padding": "8px 12px", "backgroundColor": CRIMSON}),
            html.Video(id="splash-video-modal-player", controls=True, autoPlay=True,
                      children=html.Source(id="splash-video-modal-source", src="",
                                           type="video/mp4"),
                      style={"width": "100%", "display": "block", "background": "#000",
                             "maxHeight": "80vh"}),
            html.Div(id="splash-video-modal-reload", style={"display": "none"}),
        ], style={"maxWidth": "720px", "margin": "5vh auto", "backgroundColor": "#111",
                  "borderRadius": "8px", "overflow": "hidden",
                  "boxShadow": "0 10px 40px rgba(0,0,0,0.5)"}),
        id="splash-video-modal",
        style={"display": "none", "position": "fixed", "inset": "0",
              "backgroundColor": "rgba(0,0,0,0.7)", "zIndex": "1000", "padding": "16px"},
    )


def _video_row(video: dict) -> html.Div:
    """One row in the Manage Video Library list: title, category (+ drill
    category for a Gas Station upload that has one, + "Link" for a
    link-based video), delete."""
    cat_label = video["category"]
    if video.get("drill_category"):
        cat_label += f" · {video['drill_category']}"
    if video.get("link_url"):
        cat_label += " · Link"
    return html.Div([
        html.Span(f"{video['title']} ", style={"fontWeight": "bold"}),
        html.Span(f"({cat_label})", style={"color": "#666", "fontSize": "12px"}),
        html.Button("Remove", id={"type": "splash-video-delete", "index": video["id"]},
                   n_clicks=0, style={"border": "none", "background": "none", "color": CRIMSON,
                                      "cursor": "pointer", "fontSize": "12px",
                                      "marginLeft": "10px", "textDecoration": "underline"}),
    ], style={"padding": "3px 0", "borderBottom": "1px solid #eee"})


def _panel_style(open_: bool) -> dict:
    return {"display": "block" if open_ else "none", "marginTop": "8px"}


def manage_video_library_panel(all_videos: list[dict], *, open_: bool) -> html.Div:
    """Coach-only, collapsed-by-default upload/manage panel for BOTH video
    categories at once (one shared form, a category dropdown picks
    Recovery vs Gas Station) -- avoids duplicating the same upload UI in
    two cards. Lives inside the Recovery Protocols card; the Gas Station
    section just displays whatever's uploaded here under that category.

    `open_` comes from `data["manage_videos_open"]` rather than a local
    Store: this whole subtree is rebuilt from scratch on every splash-data
    change (Add/Remove included -- see callbacks.py), so a local Store
    defaulting to False would silently re-close the panel after every
    single click. Keeping the flag IN `data` is what lets the upload/
    delete callbacks say "and leave it open" when they refresh the data."""
    return html.Div([
        html.Button("Manage Video Library", id="splash-manage-videos-toggle", n_clicks=0,
                   style={"border": f"2px solid {CRIMSON}", "background": "#fff",
                          "color": CRIMSON, "borderRadius": "14px", "padding": "4px 14px",
                          "cursor": "pointer", "fontFamily": "Teko, sans-serif",
                          "fontSize": "13px", "marginTop": "8px"}),
        html.Div([
            html.Div([
                dcc.Input(id="splash-video-title", type="text", placeholder="Title",
                         style={"width": "100%", "padding": "6px", "borderRadius": "6px",
                                "border": "1px solid #ccc", "marginBottom": "6px"}),
                dcc.Dropdown(id="splash-video-category",
                           options=[{"label": c, "value": c} for c in SR.VIDEO_CATEGORIES],
                           value=SR.VIDEO_CATEGORIES[0], clearable=False,
                           style={"marginBottom": "6px"}),
                # Only meaningful for a "Gas Station" upload (see
                # SR.add_video's docstring) -- always rendered regardless of
                # the category dropdown's live value so this id is a stable
                # State target.
                dcc.Dropdown(id="splash-video-drill-category",
                           options=[{"label": c, "value": c}
                                    for c in SR.GAS_STATION_DRILL_CATEGORIES],
                           placeholder="Drill category (Gas Station only)", clearable=True,
                           style={"marginBottom": "6px"}),
                dcc.Upload(id="splash-video-upload",
                          children=html.Button("Choose File & Upload",
                                              style={"border": f"2px solid {CRIMSON}",
                                                     "background": "#fff", "color": CRIMSON,
                                                     "borderRadius": "14px", "padding": "4px 14px",
                                                     "cursor": "pointer",
                                                     "fontFamily": "Teko, sans-serif"}),
                          multiple=False),
                html.Div(id="splash-video-upload-status",
                        style={"fontSize": "12px", "color": CRIMSON, "margin": "6px 0"}),
                html.Div("— or —", style={"fontSize": "11px", "color": "#999",
                                          "textAlign": "center", "margin": "6px 0"}),
                # Link-based video (2026-09-16, Brad: "Prescription Links" --
                # a Google Drive share link, opens in a new tab rather than
                # being downloaded/uploaded -- see SR.add_video_link). Shares
                # the Title/Category/Drill Category fields above with the
                # file-upload path; only one of "Choose File & Upload" or
                # "Add Link" actually needs a value below it.
                dcc.Input(id="splash-video-link-url", type="text",
                         placeholder="Or paste a video link (e.g. Google Drive)",
                         style={"width": "100%", "padding": "6px", "borderRadius": "6px",
                                "border": "1px solid #ccc", "marginBottom": "6px"}),
                html.Button("Add Link", id="splash-video-add-link", n_clicks=0,
                           style={"border": f"2px solid {CRIMSON}", "background": "#fff",
                                  "color": CRIMSON, "borderRadius": "14px", "padding": "4px 14px",
                                  "cursor": "pointer", "fontFamily": "Teko, sans-serif"}),
            ], style={"maxWidth": "320px", "marginBottom": "10px"}),
            html.Div([_video_row(v) for v in all_videos] or
                    [html.Div("No videos in the library yet.",
                             style={"color": "#888", "fontStyle": "italic"})]),
        ], id="splash-manage-videos-panel", style=_panel_style(open_)),
    ])


def _recovery_section(recovery_videos: list[dict], all_videos: list[dict], *,
                      is_coach: bool, manage_videos_open: bool) -> html.Div:
    children = [video_list_or_empty(recovery_videos)]
    if is_coach:
        children.append(manage_video_library_panel(all_videos, open_=manage_videos_open))
    return _card("Recovery Protocols", html.Div(children))


def checklists_grid(plan: dict, *, editable: bool, is_coach: bool, drill_options: list[str],
                    videos: dict, manage_videos_open: bool = False) -> html.Div:
    sections = [
        _text_section("Pre-Throw Checklist", plan["pre_throw_checklist"],
                     editable=editable, input_id="splash-pre"),
        _text_section("Post-Throw Checklist", plan["post_throw_checklist"],
                     editable=editable, input_id="splash-post"),
        _drill_section("Feet Set", plan["feet_set"], editable=editable, is_coach=is_coach,
                       dd_id="splash-feetset", section_key="feetset",
                       drill_options=drill_options, drill_videos=videos.get("Drills", [])),
        _drill_section("Feet Moving", plan["feet_moving"], editable=editable, is_coach=is_coach,
                       dd_id="splash-feetmoving", section_key="feetmoving",
                       drill_options=drill_options, drill_videos=videos.get("Drills", [])),
        _drill_section("Work Day", plan["work_day"], editable=editable, is_coach=is_coach,
                       dd_id="splash-workday", section_key="workday",
                       drill_options=drill_options, drill_videos=videos.get("Drills", [])),
        _recovery_section(videos.get("Recovery", []),
                          videos.get("Recovery", []) + videos.get("Gas Station", []),
                          is_coach=is_coach, manage_videos_open=manage_videos_open),
    ]
    return html.Div(sections, className="paw-chart-grid",
                    style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "10px"})


# 2026-09-14 layout test (Brad: "test this out and I will report back if we
# want to keep it or revert") -- splits `checklists_grid`'s 6 boxes into the
# 2 "throwing" checklists (stay in the center column, above Bullpen Scripts)
# and the other 4 (Feet Set/Feet Moving/Work Day/Recovery Protocols, moved
# to the left column where the skeleton visuals used to sit). See
# `[[splash-report-right-wall-layout-test]]` memory for the before-state
# screenshot if this gets reverted.
def throwing_checklists_row(plan: dict, *, editable: bool) -> html.Div:
    sections = [
        _text_section("Pre-Throw Checklist", plan["pre_throw_checklist"],
                     editable=editable, input_id="splash-pre"),
        _text_section("Post-Throw Checklist", plan["post_throw_checklist"],
                     editable=editable, input_id="splash-post"),
    ]
    return html.Div(sections, className="paw-chart-grid",
                    style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "10px"})


def training_boxes_column(plan: dict, *, editable: bool, is_coach: bool,
                          drill_options: list[str], videos: dict,
                          manage_videos_open: bool = False) -> html.Div:
    """Feet Set / Feet Moving / Work Day / Recovery Protocols, stacked
    single-column -- this lands in the narrow (290px) left sidebar, too
    tight for the 2-column grid `checklists_grid` used in the wider center
    column."""
    sections = [
        _drill_section("Feet Set", plan["feet_set"], editable=editable, is_coach=is_coach,
                       dd_id="splash-feetset", section_key="feetset",
                       drill_options=drill_options, drill_videos=videos.get("Drills", [])),
        _drill_section("Feet Moving", plan["feet_moving"], editable=editable, is_coach=is_coach,
                       dd_id="splash-feetmoving", section_key="feetmoving",
                       drill_options=drill_options, drill_videos=videos.get("Drills", [])),
        _drill_section("Work Day", plan["work_day"], editable=editable, is_coach=is_coach,
                       dd_id="splash-workday", section_key="workday",
                       drill_options=drill_options, drill_videos=videos.get("Drills", [])),
        _recovery_section(videos.get("Recovery", []),
                          videos.get("Recovery", []) + videos.get("Gas Station", []),
                          is_coach=is_coach, manage_videos_open=manage_videos_open),
    ]
    return html.Div(sections)


def engine_tables_block(engine_records: list, *, editable: bool = False) -> html.Div:
    """Just the Strength/ROM table pair. `editable` mirrors the page's
    Edit/Save toggle (2026-09-16: Base/Now reverted from a derived-reading
    history back to plain manual cells, at the coaching staff's request --
    see `app.data.splash_report`'s Building the Engine section docstring),
    so a coach types straight into these grids like every other section,
    submitted on the same Save button."""
    eng = pd.DataFrame(engine_records)
    strength = eng[eng["metric_key"].isin(SR.STRENGTH_METRICS)] if not eng.empty else eng
    rom = eng[eng["metric_key"].isin(SR.ROM_METRICS)] if not eng.empty else eng
    if not rom.empty:
        # Table-only shortening (2026-09-23, Brad: save space, line the two
        # tables up on phone) -- "Scaption ROM" is the widest label in
        # either table, wider than every Strength row, which is what threw
        # the two tables out of alignment. Scoped to just this table's
        # DataFrame, not SR.ENGINE_METRIC_LABELS itself, because the body
        # visual's ROM readout panel (`body_visual.py`) reads that same
        # shared dict and has room for the full "Scaption ROM" -- no
        # complaint was raised about that one.
        rom = rom.copy()
        rom.loc[rom["metric_key"] == "ScaptionROM", "label"] = "Scap ROM"
    # flex:1 on each table used to stretch it across half of a very wide
    # container, leaving a big blank gap between two content-sized tables
    # -- size to content instead so they sit close together.
    # 2026-09-14: "Strength" / "Range of Motion" moved into the tables' own
    # red header bar (white text, top-left cell) instead of a separate black
    # label above each table -- see `tables.engine_metrics_table`'s
    # `label_header`. Header shortened to "ROM" (2026-09-23, Brad) to match
    # the same save-space/line-up-on-phone ask.
    return html.Div([
        html.Div(tables.engine_metrics_table(strength, "splash-engine-strength-table",
                                             label_header="Strength", editable=editable),
                style={"flex": "0 0 auto"}),
        html.Div(tables.engine_metrics_table(rom, "splash-engine-rom-table",
                                             label_header="ROM", editable=editable),
                style={"flex": "0 0 auto"}),
    ], style={"display": "flex", "gap": "24px", "flexWrap": "wrap", "marginBottom": "12px"})



def engine_card(engine_records: list, *, editable: bool) -> html.Div:
    """Building the Engine: just the Strength/ROM tables. Gas Station split
    out into its own card (`gas_station_card`, 2026-09-13 -- Brad wants it
    "its own box like the others", not nested in here) and the body visual
    lives in its own card too now (see `render_from_data`), so this one
    holds only the tables."""
    tables_block = html.Div(engine_tables_block(engine_records, editable=editable),
                            id="splash-engine-tables-wrap")
    return _card("Building the Engine — Strength · ROM", tables_block)


def gas_station_card(gas_records: list, gas_videos: list[dict], *, editable: bool) -> html.Div:
    """The Gas Station, split out of `engine_card` into its own card
    (2026-09-13: Brad wants it "its own box like the others... with the
    background heading and separate opaque box") -- same `_card()` treatment
    (graffiti header + opaque gradient box) as every other section.

    2026-09-16 round 4 (Brad): dropped the standalone "Gas Station Videos"
    browsable list that used to sit under this table -- a player shouldn't
    see a flat library, just the specific video prescribed for each
    exercise row. That linking now happens IN the Exercise column itself
    (see `tables.gas_station_table`): a dropdown a coach can filter while
    editing, a plain link for everyone else."""
    gas = pd.DataFrame(gas_records)
    gas_child = tables.gas_station_table(gas, gas_videos, editable=editable) \
        if (editable or not gas.empty) \
        else html.Div("Nothing entered yet.", style={"color": "#888", "fontStyle": "italic"})
    caption = "Tie a specific exercise to whatever the numbers above flag."
    children = [
        html.Div(caption, style={"fontSize": "12px", "color": "#666", "margin": "2px 0 6px"}),
    ]
    if editable:
        # 2026-09-16 round 7 (Brad): "add an exercise search bar at the top
        # of the column" -- round 6's fix (typing directly into the cell
        # already filters it) worked but had no visible affordance, so
        # Brad still couldn't tell it was there. This is a real, visible
        # search box above the table; `_on_gas_exercise_search`
        # (callbacks.py, clientside) narrows the Exercise column's
        # dropdown options as you type, filtering `gas_videos` client-side
        # against the same splash-data already loaded -- no DB round trip.
        children.append(dcc.Input(
            id="splash-gas-exercise-search", type="text",
            placeholder="Search exercises (e.g. \"shoulder\", \"elbow\")...",
            style={"width": "100%", "maxWidth": "320px", "padding": "6px 10px",
                  "borderRadius": "6px", "border": "1px solid #ccc",
                  "marginBottom": "8px", "fontFamily": "Teko, sans-serif",
                  "fontSize": "14px"}))
    children.append(gas_child)
    return _card("The Gas Station", html.Div(children))


_SCRIPT_LINK_BTN_STYLE = {"border": "none", "background": "none", "color": CRIMSON,
                         "cursor": "pointer", "fontSize": "12px",
                         "textDecoration": "underline", "padding": "0"}


def _script_copy_paste_row(script_number) -> html.Div:
    """Small red Copy/Paste/Undo/Archive/Remove Archive links at the bottom
    of a script card (2026-09-22, Brad's screenshot; narrowed to table-only
    + Undo added 2026-09-23, Archive added same day per follow-up feedback,
    Remove Archive + the two-row split added a round later). Two lines
    (2026-09-23, Brad: "make it on a line below. so the top row of buttons
    are copy, paste and undo, the bottom two are archive and remove
    archive") -- Copy/Paste/Undo (row-level, per-script) read as one group,
    Archive/Remove Archive (type-level, team-wide) as another.

    Copy stashes this script's pitch rows ONLY (never Type/Goal/
    Measurable, which stay manual) into a page-lifetime
    `splash-script-clipboard` Store (`callbacks._on_script_copy`); Paste
    overwrites another script's rows from whatever's currently in that
    Store (`callbacks._on_script_paste`), working across players (the
    Store outlives a player switch) and also snapshotting the target
    script's pre-paste rows into `splash-script-undo-buffer` so Undo can
    restore them (`callbacks._on_script_undo`). Archive saves this
    script's CURRENT rows as the shared team-wide template for its
    script_type (`callbacks._on_script_archive` -> `SR.save_script_
    template`) -- selecting that type on a blank script elsewhere
    auto-pulls it back (`callbacks._on_script_type_change`). Remove Archive
    clears that type's template entirely (`callbacks._on_script_remove_
    archive`), so a stale/wrong archived default stops auto-filling new
    scripts of that type. Edit-mode only (there's nothing to copy/paste/
    archive in read-only view)."""
    row_style = {"display": "flex", "gap": "4px", "alignItems": "center"}
    return html.Div([
        html.Div([
            html.Button("Copy", id=f"splash-script-copy-{script_number}", n_clicks=0,
                       title="Copy this script's pitch table (# / Type / Ball / Info)",
                       style=_SCRIPT_LINK_BTN_STYLE),
            html.Span(" · ", style={"color": "#ccc", "fontSize": "12px"}),
            html.Button("Paste", id=f"splash-script-paste-{script_number}", n_clicks=0,
                       title="Paste the copied pitch table into this script",
                       style=_SCRIPT_LINK_BTN_STYLE),
            html.Span(" · ", style={"color": "#ccc", "fontSize": "12px"}),
            html.Button("Undo", id=f"splash-script-undo-{script_number}", n_clicks=0,
                       title="Undo the last paste into this script",
                       style=_SCRIPT_LINK_BTN_STYLE),
        ], style=row_style),
        html.Div([
            html.Button("Archive", id=f"splash-script-archive-{script_number}", n_clicks=0,
                       title="Save this script's pitch table as the shared default for its Type",
                       style=_SCRIPT_LINK_BTN_STYLE),
            html.Span(" · ", style={"color": "#ccc", "fontSize": "12px"}),
            html.Button("Remove Archive", id=f"splash-script-remove-archive-{script_number}",
                       n_clicks=0,
                       title="Clear the shared default archived for this script's Type",
                       style=_SCRIPT_LINK_BTN_STYLE),
            html.Span(id=f"splash-script-archive-status-{script_number}",
                     style={"fontSize": "11px", "color": "#1e5b28", "marginLeft": "4px"}),
        ], style={**row_style, "marginTop": "4px"}),
    ], style={"marginTop": "6px"})


def script_card(script_number, script_row: dict, rows: list, *, editable: bool) -> html.Div:
    goal = script_row["goal"]
    measurable = script_row["measurable"]
    script_type = script_row.get("script_type") or ""
    pd_result = script_row.get("pitch_design_result") or ""
    goal_child = dcc.Input(id=f"splash-script-goal-{script_number}", value=goal,
                           type="text", style={"width": "100%"}) if editable \
        else html.Div(goal or "—")
    measurable_child = dcc.Input(id=f"splash-script-measurable-{script_number}",
                                 value=measurable, type="text", style={"width": "100%"}) \
        if editable else html.Div(measurable or "—")
    # Drives the Pen Results value's meaning (velo/execution = raw result %,
    # pitch design = % in the target movement window) and which scripts feed
    # the pitch-design movement plot (2026-09-16 coaches' meeting). Also
    # (2026-09-23) which Result widget `script_pitch_table` shows, and
    # which of the two blocks below (pitch_design_result input / Velo
    # summary) is visible -- `callbacks`'s per-script "Result visibility"
    # clientside callback keeps that in sync live as this dropdown changes,
    # without a full page re-render.
    type_child = dcc.Dropdown(
        id=f"splash-script-type-{script_number}",
        options=[{"label": t, "value": t} for t in SR.SCRIPT_TYPES],
        value=script_type or None, clearable=True,
        style={"fontFamily": "Teko, sans-serif"}) if editable \
        else html.Div(script_type or "—")
    # Pitch Design's single end-of-bullpen number (Trackman average) --
    # entered ONCE, not per pitch (no Result column in that script's
    # table -- see `tables.script_pitch_table`). Always rendered (never
    # conditionally omitted), just hidden via style when the current type
    # isn't Pitch Design -- same reasoning as `script_wrap` below: an
    # omitted element would be an invalid State target for the Save
    # callback the moment a coach switches Type without a full re-render.
    pd_result_child = html.Div([
        html.Span("Trackman Avg ", style={"fontSize": "11px", "color": "#666"}),
        dcc.Input(id=f"splash-script-pdresult-{script_number}", value=pd_result,
                 type="text", style={"width": "100%"}) if editable
        else html.Div(pd_result or "—"),
    ], id=f"splash-script-pdresult-wrap-{script_number}", style={
        "marginTop": "4px", "display": "block" if script_type == "Pitch Design" else "none"})
    velo_summary_child = html.Div(
        id=f"splash-script-velosummary-{script_number}",
        style={"fontSize": "12px", "color": "#555", "marginTop": "4px"})
    velo_summary_wrap = html.Div(velo_summary_child,
        id=f"splash-script-velosummary-wrap-{script_number}",
        style={"display": "block" if script_type == "Velo" else "none"})
    # Fixed-height OUTER wrappers (2026-09-24, Brad, screenshot: "some [script
    # cards] wider and longer than others... is it possible to have all of
    # the outline boxes be the same size?") -- a Pitch Design card shows
    # Trackman Avg (pd_result_child) and no other type does; a Velo card
    # shows the Max/Avg summary (velo_summary_wrap) and no other type does,
    # so without this a card's height depended on its Type. Reserving each
    # block's own natural height on EVERY card (not "display: none" on the
    # unused one, which collapses it to zero) equalizes all six without
    # adding height beyond what a Pitch Design or Velo card already has on
    # its own -- Brad: "I did not want the expansion to bring about more
    # white space." The wrap divs above keep their own ids/style (still the
    # clientside "Result visibility" callback's Output targets, which
    # REPLACES their whole style prop on a Type switch) -- these are new
    # parents around them, not a change to those elements themselves.
    pd_result_slot = html.Div(pd_result_child, style={"minHeight": "44px"})
    velo_summary_slot = html.Div(velo_summary_wrap, style={"minHeight": "20px"})
    card = html.Div([
        html.Div(f"Script #{script_number}", style={"fontWeight": "bold", "color": CRIMSON}),
        html.Div([html.Span("Type ", style={"fontSize": "11px", "color": "#666"}),
                  type_child]),
        html.Div([html.Span("Goal ", style={"fontSize": "11px", "color": "#666"}),
                  goal_child], style={"marginTop": "4px"}),
        html.Div([html.Span("Measurable ", style={"fontSize": "11px", "color": "#666"}),
                  measurable_child], style={"marginTop": "4px"}),
        pd_result_slot,
        html.Div(tables.script_pitch_table(pd.DataFrame(rows), script_number,
                                           script_type=script_type, editable=editable),
                 style={"marginTop": "6px"}),
        velo_summary_slot,
        *([_script_copy_paste_row(script_number)] if editable else []),
    # Fixed width (2026-09-14, part of the flex-wrap fix above): without it
    # the card shrinks to fit its content, and in a shrink-to-fit box a
    # `width: 100%` child (the Goal/Measurable inputs in edit mode) has
    # nothing real to resolve 100% against -- a fixed width here gives both
    # the inputs a real anchor and the flex-wrap row a predictable per-card
    # size to count columns by. `boxSizing: border-box` makes that width the
    # card's FULL rendered width (padding included) instead of content plus
    # 20px of padding on top of it. ONE fixed width for every Type (2026-09-24,
    # Brad, screenshot: "some [cards] wider and longer than others... is it
    # possible to have all of the outline boxes be the same size?") -- a
    # per-Type width (220px for Pitch Design's narrower 4-column table,
    # 300px for Velo/Execution's Result column, 2026-09-23) looked fine card
    # by card but ragged side by side in the grid. 300px for all -- the
    # width the widest table (Result column) actually needs, matching
    # `pd_result_slot`/`velo_summary_slot` above equalizing height the same
    # way.
    ], style={"backgroundColor": "rgba(255,255,255,0.85)", "borderRadius": "8px",
              "padding": "10px", "marginBottom": "12px", "width": "300px",
              "boxSizing": "border-box"})
    # ALWAYS rendered (never conditionally omitted) so its Save-form Inputs
    # stay valid targets for `callbacks._script_states()` regardless of
    # which scripts are currently picked in "splash-script-select" --
    # visibility is toggled client-side by wrapper display:none/block
    # instead, so hiding a script never risks a missing-State callback
    # error. See `_on_script_select` in callbacks.py.
    return html.Div(card, id=f"splash-script-wrap-{script_number}", style={"display": "none"})


def _removed_pen_row(row: dict) -> html.Div:
    value = row.get("value")
    value_text = "—" if value is None else f"{value:g}%"
    return html.Div([
        html.Span(f"Script {row.get('script_number')} · {row.get('pen_date') or '—'} · "
                 f"{value_text}", style={"fontSize": "12px"}),
        html.Button("Restore", id={"type": "splash-pen-restore", "index": row["id"]},
                   n_clicks=0, style={"border": "none", "background": "none", "color": CRIMSON,
                                      "cursor": "pointer", "fontSize": "12px",
                                      "marginLeft": "10px", "textDecoration": "underline"}),
    ], style={"padding": "2px 0", "borderBottom": "1px solid #eee"})


def _removed_pen_panel(deleted_records: list) -> html.Div:
    """Coach-in-edit-mode-only, always-visible-when-nonempty list of
    soft-deleted pen results (see `app.data.splash_report.save_pen_results`'s
    docstring for why deleting a pen result is a soft-delete, not a hard one)
    with a per-row Restore button. Unlike Manage Drills/Manage Video Library,
    this one doesn't need an open/closed flag at all -- it simply isn't
    rendered when there's nothing removed, which sidesteps that whole class
    of bug (see this session's fix for those two panels re-closing themselves
    on every edit) by never having state to lose in the first place.

    2026-09-21 (Brad): a season's worth of removed test data turned this into
    a long list that "clutters up a lot of the space" on the read-only view
    -- `scripts_section` now only renders this panel at all when `editable`
    (edit mode is where a Restore actually matters), and the row list itself
    is capped to a scrollable strip here so it stays out of the way even with
    many entries."""
    if not deleted_records:
        return html.Div()
    return html.Div([
        html.Div("Recently Removed", style={"fontSize": "12px", "fontWeight": "bold",
                                            "color": CRIMSON, "marginTop": "8px"}),
        html.Div([_removed_pen_row(r) for r in deleted_records],
                 style={"maxHeight": "120px", "overflowY": "auto"}),
    ])


def _scripts_with_data(scripts_records: list, script_rows: dict) -> list[int]:
    """Script numbers whose 12-row pitch TABLE already has something entered
    (Type/Ball/Info on any row) -- so "Show Scripts" opens on whatever a
    coach already filled in instead of starting blank on every player
    (2026-09-22, Brad: once a script's filled in, "every player... has
    script one automatically open"). Deliberately checks the pitch rows
    only, not the Type/Goal/Measurable header fields above the table --
    Brad: "I meant that data in these tables," i.e. the rows themselves
    (a script's header can be set without any pitch actually logged yet)."""
    have = []
    for r in scripts_records:
        n = int(r["script_number"])
        rows = script_rows.get(str(n), [])
        if any((row.get(k) or "").strip() for row in rows
              for k in ("pitch_type", "ball_info", "info")):
            have.append(n)
    return have


def scripts_section(pen_records: list, deleted_pen_records: list, scripts_records: list,
                    script_rows: dict, movement_records: dict, *, editable: bool,
                    is_coach: bool) -> html.Div:
    """Script Pen Results trend graph on top, the 6 script cards collapsed
    below it behind a multi-select ("only show when clicked" -- 2026-09-10
    planning session): "Compare Scripts" narrows which lines the graph
    shows, "Show Scripts" reveals the matching card(s) -- the SAME control
    serves both view mode (pick a script to read) and edit mode (pick a
    script to edit); nothing selected shows nothing, by design."""
    pen = pd.DataFrame(pen_records)
    script_numbers = list(range(1, SR.N_SCRIPTS + 1))
    compare_options = [{"label": f"Script {n}", "value": n} for n in script_numbers]
    graph_block = html.Div([
        html.Label("Compare Scripts", style={**_LABEL_STYLE, "textAlign": "left"}),
        dcc.Dropdown(id="splash-pen-compare", options=compare_options, multi=True,
                    value=script_numbers, style={"fontFamily": "Teko, sans-serif",
                                                 "marginBottom": "8px"}),
        dcc.Graph(id="splash-pen-graph", figure=charts.pen_results_fig(pen),
                 config={"displayModeBar": False}),
        # Shared movement chart (2026-09-16 round 2, Brad: "just place it
        # right underneath the script pen chart," always visible). Shares
        # "Compare Scripts" with the graph above it rather than its own
        # selector.
        dcc.Graph(id="splash-movement-graph",
                 figure=charts.scripts_movement_fig(movement_records, script_numbers),
                 config={"displayModeBar": False}),
    ])
    # 2026-09-17, Brad (screenshot): the per-script Movement Log entry table
    # used to sit beside each script's card in the grid below -- "that area
    # is designated only for scripts... having a random movement log table
    # looks awkward and messes up the perfect 3x2 columns." Replaced with
    # ONE shared table (`tables.movement_log_table`, same shape as
    # `pen_results_table` but with a Script # column) placed right next to
    # the pen results table here instead -- "move the movement log next to
    # that table in the white space on the right."
    tables_row = []
    if editable:
        tables_row.append(html.Div(tables.pen_results_table(pen, editable=True),
                                   style={"flex": "0 0 auto"}))
        tables_row.append(html.Div([
            html.Div("Movement Log", style={"fontWeight": "bold", "color": CRIMSON,
                                            "marginBottom": "4px"}),
            tables.movement_log_table(movement_records, editable=True),
        ], style={"flex": "0 0 auto"}))
    # 2026-09-17 round 2 (Brad, screenshot): "just have this table show up
    # when editing, the visual does a good enough telling the story" -- view
    # mode no longer renders the Movement Log at all, same as
    # pen_results_table (which was already edit-only); the shared HB/IVB
    # chart above is the only movement-related thing a player sees.
    if tables_row:
        graph_block.children.append(html.Div(tables_row, style={
            "display": "flex", "flexWrap": "wrap", "gap": "20px",
            "alignItems": "flex-start", "marginTop": "10px"}))
    if is_coach and editable:
        graph_block.children.append(
            html.Div(_removed_pen_panel(deleted_pen_records), id="splash-pen-removed-wrap"))

    cards = [script_card(int(r["script_number"]), r, script_rows[str(r["script_number"])],
                         editable=editable)
            for r in scripts_records]
    # 2026-09-14 (Brad, matching the skeleton-visuals grid fix): a fixed
    # 2-column grid stretched every card to half the (now much wider) center
    # column, leaving a lot of blank space to the right of each card's
    # actual content (title/goal/measurable/table, all narrow and
    # content-sized -- see `script_card` and `tables.script_pitch_table`'s
    # `width: fit-content`). Flex-wrap instead of a fixed column count: each
    # card sizes to its own content, and the row fits as many as actually
    # fit -- 3x2 on a wide monitor, 2x3 or 1x6 as the column narrows -- with
    # no media queries, same technique as `body_visual.render`'s compact
    # grid.
    select_block = html.Div([
        html.Label("Show Scripts", style={**_LABEL_STYLE, "textAlign": "left"}),
        dcc.Dropdown(id="splash-script-select", options=compare_options, multi=True,
                    value=_scripts_with_data(scripts_records, script_rows),
                    placeholder="Select a script to view or edit...",
                    style={"fontFamily": "Teko, sans-serif", "marginBottom": "8px"}),
        html.Div(cards, style={"display": "flex", "flexWrap": "wrap",
                              "justifyContent": "center", "alignItems": "flex-start",
                              "gap": "14px"}),
    # `maxWidth` (2026-09-24, Brad, screenshot with the dead area boxed in):
    # this whole card is a CSS Grid item (`gridArea: "center"`, see
    # `serve_layout`'s `center_block`), which stretches to the FULL center
    # column's width by default regardless of how many (now uniformly
    # 300px, see `script_card`) cards are actually showing -- 2-3 selected
    # scripts left a lot of the card's own translucent background exposed
    # to their right. Capped to fit 3 across (the layout's own original
    # "3x2 on a wide monitor" target, per the comment above) so the row
    # only takes the width it needs; flex-wrap still drops to 2 or 1 per
    # row on a narrower viewport same as before.
    ], style={"marginTop": "16px", "maxWidth": "950px"})
    return _card(f"Bullpen Scripts · {SR.N_SCRIPTS} Scripts", html.Div([graph_block, select_block]))


def sidebar(profile: dict, kpis: dict, plan: dict, *, editable: bool,
           extra: list | None = None) -> html.Div:
    photo = profile["photo"] or PHOTO_PLACEHOLDER
    jersey = f"#{profile['jersey']} · " if profile["jersey"] else ""
    meta = " · ".join([x for x in (profile["class_year"],
                                   f"Throws {profile['throws']}" if profile["throws"] else "")
                       if x])

    def tile(label, value):
        return html.Div([
            html.Div(value, style={"fontSize": "22px", "fontWeight": "bold", "color": CRIMSON}),
            html.Div(label, style={"fontSize": "12px", "color": "#555"}),
        ], style={"textAlign": "center", "padding": "6px 8px",
                  "backgroundColor": "rgba(255,255,255,0.8)", "borderRadius": "8px"})

    profile_card = html.Div([
        html.Img(src=photo, style={"width": "100%", "borderRadius": "8px",
                                   "border": "4px solid white",
                                   "background": "rgba(255,255,255,0.6)"}),
        html.Div(f"{jersey}{profile['name'] or '—'}",
                 style={"fontSize": "24px", "fontWeight": "bold", "marginTop": "8px"}),
        html.Div(meta, style={"fontSize": "15px", "color": "#555"}),
        html.Div([tile("K%", kpis.get("k_pct")), tile("Barrel%", kpis.get("barrel_pct")),
                  tile("BB%", kpis.get("bb_pct"))],
                 style={"display": "grid", "gridTemplateColumns": "1fr 1fr 1fr",
                        "gap": "6px", "marginTop": "10px"}),
    ], style=_CARD)
    goals = _text_section("Player Training Goals", plan["training_goals"],
                          editable=editable, input_id="splash-goals")
    # Vision Statement moved down here from the center column (2026-09-10
    # planning session: "moving things more to the left sidebar") -- it's a
    # short reflective text block like Training Goals, and the sidebar was
    # otherwise running much shorter than center/right, leaving the left
    # rail looking empty next to two much taller columns.
    # "Season Focus" dropped from the title (2026-09-10 planning session:
    # remove that field entirely -- it changes every cycle) -- 2026-09-13:
    # Brad flagged the leftover text in the heading itself.
    vision = _text_section("Vision Statement", plan["vision_statement"],
                           editable=editable, input_id="splash-vision")
    # `extra` (2026-09-14 layout test): Feet Set/Feet Moving/Work Day/
    # Recovery Protocols, moved here from the center column -- see
    # `render_from_data` and `[[splash-report-right-wall-layout-test]]`.
    # Vision Statement above Player Training Goals (2026-09-14, Brad).
    return html.Div([profile_card, vision, goals, *(extra or [])])


def filters(player_id, season_label, cycle) -> html.Div:
    is_coach = bool(getattr(current_user, "is_coach", False))
    own = getattr(current_user, "trackman_id", None)
    players = selectors.pitcher_options(is_coach=is_coach, own_trackman_id=own,
                                        season=season_label)
    return html.Div([
        html.Div([html.Label("Player", style=_LABEL_STYLE),
                  dcc.Dropdown(id="splash-player", options=players, value=player_id,
                              clearable=False, style={"minWidth": "200px"})]),
        html.Div([html.Label("Season", style=_LABEL_STYLE),
                  dcc.Dropdown(id="splash-season",
                              options=[{"label": s, "value": s}
                                      for s in seasons.available_seasons()],
                              value=season_label, clearable=False,
                              style={"minWidth": "140px"})]),
        html.Div([html.Label("Cycle", style=_LABEL_STYLE),
                  dcc.Dropdown(id="splash-cycle",
                              options=[{"label": c, "value": c} for c in SR.CYCLES],
                              value=cycle, clearable=False, style={"minWidth": "130px"})]),
    ], style={"display": "flex", "gap": "20px", "justifyContent": "center",
             "alignItems": "flex-end", "flexWrap": "wrap", "padding": "12px 16px"})


def load_data(player_id, season_label, cycle) -> dict:
    """Every read the page needs, in ONE call -- cached client-side in the
    `splash-data` Store so switching Edit on/off (which changes only HOW
    this data is drawn, not WHAT data to show) never re-queries the DB."""
    if player_id is None:
        return {}
    pid = int(player_id)
    profile = pitching_caps.pitcher_profile(pid)
    s_b, e_b = seasons.season_bounds(season_label)
    kpis = pitching_caps.range_summary(pid, s_b, e_b)
    plan = SR.read_plan(pid, season_label, cycle)
    engine = SR.read_engine_metrics(pid, season_label, cycle)
    gas = SR.read_gas_station(pid, season_label, cycle)
    scripts = SR.read_scripts(pid, season_label, cycle)
    script_rows = SR.read_all_script_rows(pid, season_label, cycle)
    pen = SR.read_pen_results(pid, season_label, cycle)
    deleted_pen = SR.read_deleted_pen_results(pid, season_label, cycle)
    movement = SR.read_all_movement(pid, season_label, cycle)
    # Drill catalog + video library are global (coach-managed, not scoped to
    # a player/season/cycle), but loaded here too so render_from_data stays
    # a pure function of `data` with zero DB calls of its own -- these are
    # tiny tables, so re-reading them on every player/season/cycle switch is
    # cheap.
    drill_options = SR.read_drill_options()
    videos = {cat: SR.list_videos(cat).to_dict("records") for cat in SR.VIDEO_CATEGORIES}
    return {
        "profile": profile, "kpis": kpis, "plan": plan, "cycle": cycle,
        "engine": engine.to_dict("records"),
        "gas": gas.to_dict("records"),
        "scripts": scripts.to_dict("records"),
        # dict keys round-trip through dcc.Store's JSON as strings either way;
        # use str() up front so in-process (no round trip yet) access matches.
        "script_rows": {str(n): df.to_dict("records") for n, df in script_rows.items()},
        "pen": pen.to_dict("records"), "deleted_pen": deleted_pen.to_dict("records"),
        "movement": {str(n): df.to_dict("records") for n, df in movement.items()},
        "drill_options": drill_options, "videos": videos,
    }


def render_from_data(data: dict, *, editable: bool, is_coach: bool = False) -> html.Div:
    """Pure render: builds the whole body from an already-loaded `data` dict
    (see `load_data`) -- no DB calls here at all. `is_coach` is passed in
    explicitly (rather than read from `current_user` here) so this stays
    callable outside a request context, e.g. in tests."""
    if not data:
        return html.Div("Select a pitcher.", style={"padding": "20px"})
    plan = data["plan"]
    videos = data.get("videos", {})

    # 2026-09-14 layout test (Brad: "test this out and I will report back if
    # we want to keep it or revert the layout back again") -- see
    # `[[splash-report-right-wall-layout-test]]` memory for the before-state
    # screenshot and a plain description of this arrangement. Design-only:
    # every block below is the same component as before, just regrouped
    # into 3 columns instead of 4 grid areas.
    #   left ("profile"):  photo/stats + goals + vision (unchanged), PLUS
    #                       Feet Set/Feet Moving/Work Day/Recovery Protocols
    #                       (moved here from the center column, where the
    #                       skeleton visuals used to sit).
    #   center ("center"): Pre-Throw/Post-Throw Checklist, then Bullpen
    #                       Scripts underneath (moved here from the right
    #                       column).
    #   right ("right"):   skeleton visuals on top as a compact 3-col grid
    #                       (`body_visual.render(..., compact=True)`), then
    #                       Building the Engine (unchanged internally) and
    #                       Gas Station stacked underneath.
    profile_block = html.Div(
        sidebar(data["profile"], data["kpis"], plan, editable=editable,
               extra=[training_boxes_column(
                   plan, editable=editable, is_coach=is_coach,
                   drill_options=data.get("drill_options", []), videos=videos,
                   manage_videos_open=data.get("manage_videos_open", False))]),
        style={"gridArea": "profile"})
    center_block = html.Div([
        throwing_checklists_row(plan, editable=editable),
        scripts_section(data["pen"], data.get("deleted_pen", []), data["scripts"],
                       data["script_rows"], data.get("movement", {}),
                       editable=editable, is_coach=is_coach),
    ], style={"gridArea": "center", "minWidth": "0"})
    visuals_block = html.Div(
        body_visual.render(data["engine"], (data.get("profile") or {}).get("throws"),
                          compact=True),
        id="splash-engine-visual-wrap", style={**_CARD})
    right_block = html.Div([
        visuals_block,
        engine_card(data["engine"], editable=editable),
        gas_station_card(data["gas"], videos.get("Gas Station", []), editable=editable),
    ], style={"gridArea": "right", "minWidth": "0"})
    # 3 named areas, one row on desktop; the phone override in shell.py's
    # `@media (max-width: 720px)` block restacks them profile -> center ->
    # right.
    return html.Div([profile_block, center_block, right_block],
                    className="paw-splash-grid",
                    style={"display": "grid",
                          "gridTemplateColumns": "290px 1fr 1fr",
                          "gridTemplateAreas": '"profile center right"',
                          "gap": "12px", "alignItems": "start"})


# Slim page-title banner, "Built on the Bluff" (this page's planned rename
# -- 2026-09-13 planning session confirmed this graffiti banner IS that
# title, not a separate element). Sits above the Edit/Save row.
#
# Round 2 (Brad's screenshot feedback): round 1 stretched the backdrop
# across the FULL page width with no contained box, which read as a plain
# background wash rather than a banner. Rebuilt to match the Velo Board /
# Competitive Cauldron idiom Brad pointed at -- a CONTAINED box (capped
# width, centered, rounded corners, drop shadow) with the page's own
# grey/palms background showing on either side, not a full-bleed strip.
# Kept shorter than those banners (no crest/logo, just the title line) per
# the brief ("should not dominate the page; keep it narrow/skinny").
def _page_title_banner() -> html.Div:
    # Round 3 (Brad: "looks a little small and pathetic", wants an
    # "aggressive cursive font" + an LMU logo in the box). Font switched
    # from Alfa Slab One (a blocky poster face, all-caps) to "Cauldron
    # Script" -- Kaushan Script (OFL), the same cursive TTF the Competitive
    # Cauldron banner already embeds for its "Cauldron" wordmark, now
    # registered as a normal page font in shell.py's @font-face block so it
    # can be used here too without a new asset. Cursive scripts read as
    # connected strokes, so this drops the uppercase+letterSpacing treatment
    # (both fight a script face) in favor of title case and tight spacing.
    # Kaushan Script is a flowing signature style, not a harsh/tagging
    # script -- "aggressive" may want something blockier; swap the font-face
    # src in shell.py for a different script TTF if this one doesn't read
    # aggressive enough once seen live.
    logo = html.Img(src="/static/reports/lmu.png", alt="LMU", style={
        "display": "block", "margin": "0 auto 2px", "height": "56px", "width": "auto",
    })
    title = html.Div("Built on the Bluff", style={
        "textAlign": "center", "color": "#fff",
        "fontFamily": "'Cauldron Script', cursive", "fontSize": "46px",
        "lineHeight": "1.1", "textShadow": "0 2px 6px rgba(0,0,0,0.65)",
    })
    box = html.Div([logo, title], style={
        "background": "url(/static/reports/velo-backdrop.png) center/cover no-repeat",
        "borderRadius": "10px", "maxWidth": "720px", "margin": "16px auto 8px",
        "padding": "14px 20px 18px", "boxShadow": "0 2px 8px rgba(0,0,0,0.18)",
    })
    return html.Div(box, style={"padding": "0 20px"})


def serve_layout() -> html.Div:
    if not current_user.is_authenticated:
        return html.Div("Please log in.")
    is_coach = bool(getattr(current_user, "is_coach", False))
    own = getattr(current_user, "trackman_id", None)
    season = seasons.current_season()
    cycle = SR.cycle_for_date(date.today())
    players = selectors.pitcher_options(is_coach=is_coach, own_trackman_id=own, season=season)
    default_player = selectors.resolve_pitcher(None, is_coach=is_coach, own_trackman_id=own) \
        or (players[0]["value"] if players else None)

    controls = []
    if is_coach:
        controls.append(html.Div(edit_save_buttons("splash-edit", "splash-save",
                                                    "splash-save-status"),
                                 id="splash-coach-section"))
    controls.append(filters(default_player, season, cycle))

    data = load_data(default_player, season, cycle)
    return html.Div([
        dcc.Store(id="splash-editing", data=False),
        dcc.Store(id="splash-data", data=data),
        # Clipboard for the per-script Copy/Paste buttons
        # (`_script_copy_paste_row`) -- never persisted to the DB, just
        # holds whatever was last copied until a Paste (or a browser-side
        # clear) replaces/clears it. Outlives a player switch on purpose
        # (Copy on one player, Paste on another) -- both this and the Store
        # below sit OUTSIDE `splash-body`, which is what makes that
        # possible: `splash-body` (and every script-scoped Button inside
        # it) gets torn down and rebuilt on every player/season/cycle/edit
        # change. `storage_type="local"` (2026-09-23, Brad) -- the default
        # "memory" only lives in one tab's React state, so a coach copying
        # in one browser tab and pasting in another (two separate Dash
        # sessions) silently did nothing; localStorage is shared by every
        # tab on the same browser+origin, so a Paste in tab B now sees what
        # was copied in tab A.
        dcc.Store(id="splash-script-clipboard", storage_type="local"),
        # {"script_number", "rows"} snapshot of a script's pitch rows from
        # immediately before the most recent Paste into it -- lets a single
        # Undo click (`callbacks._on_script_undo`) restore them. Single-
        # level (one paste's worth), not a full history stack. Deliberately
        # stays `storage_type="memory"` (this tab only), unlike the
        # clipboard above -- Undo means "undo what I just did in THIS tab";
        # sharing it via localStorage would let a stale buffer from tab A
        # get undone by a click in tab B, reverting the wrong player/script.
        dcc.Store(id="splash-script-undo-buffer"),
        header(back_href="/pitching", back_label="← Pitching"),
        _page_title_banner(),
        html.Div(controls, style={"borderBottom": f"2px solid {CRIMSON}",
                                  "backgroundColor": "rgba(255,255,255,0.55)"}),
        html.Div(id="splash-body",
                 children=render_from_data(data, editable=False, is_coach=is_coach),
                 style={"padding": "16px"}),
        video_modal(),
        # Dummy Output target for the Backspace/Delete fix clientside
        # callback (callbacks.py) -- never actually renders anything.
        html.Div(id="splash-backspace-fix", style={"display": "none"}),
    ])
