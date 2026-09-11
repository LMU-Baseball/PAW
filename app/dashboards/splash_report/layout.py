"""Splash Report page shell: filters, sidebar, and the whole editable body.

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
from app.dashboards.shell import BANNER, BLUE, CRIMSON, PHOTO_PLACEHOLDER, header, edit_save_buttons
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
]


def _card_style(title: str) -> dict:
    for prefix, idx in _CARD_VARIANT_BY_PREFIX:
        if title.startswith(prefix):
            variant = _CARD_VARIANTS[idx]
            break
    else:
        variant = _CARD_VARIANTS[sum(title.encode("utf-8")) % len(_CARD_VARIANTS)]
    return {**_CARD, **variant}
_LABEL_STYLE = {"color": CRIMSON, "fontWeight": "bold", "fontSize": "13px",
                "textTransform": "uppercase", "letterSpacing": "1px",
                "display": "block", "marginBottom": "4px", "textAlign": "center"}
_TEXTAREA_STYLE = {"width": "100%", "minHeight": "80px", "padding": "8px",
                   "borderRadius": "8px", "fontFamily": "Teko, sans-serif",
                   "fontSize": "15px", "border": "1px solid #ccc"}


def _title(text: str) -> html.H3:
    return html.H3(text, style={"color": CRIMSON, "margin": "0 0 8px",
                                "fontSize": "18px", "textTransform": "uppercase",
                                "letterSpacing": "1px"})


def _card(title: str, child, *, card_id=None) -> html.Div:
    kwargs = {"style": _card_style(title)}
    if card_id:
        kwargs["id"] = card_id
    return html.Div([_title(title), child], **kwargs)


def _lines(text: str) -> list[str]:
    return [ln.strip() for ln in (text or "").split("\n") if ln.strip()]


def _bullet_view(text: str, empty_msg: str = "Nothing entered yet.") -> html.Div:
    items = _lines(text)
    if not items:
        return html.Div(empty_msg, style={"color": "#888", "fontStyle": "italic"})
    return html.Ul([html.Li(x) for x in items], style={"margin": "0", "paddingLeft": "18px"})


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
                   section_key: str, drill_options: list[str]) -> html.Div:
    """Feet Set/Feet Moving/Work Day: a multi-select catalog (the coaches'
    real drill list), not free text. `drill_options` comes from
    `app.data.splash_report.read_drill_options()` (coach-managed via the
    inline add/remove row -- `_drill_catalog_controls`, directly below the
    dropdown -- rather than a separate section), loaded once in `load_data`
    rather than queried here so this render stays a pure function of
    `data`. dcc.Dropdown is searchable by typing out of the box, satisfying
    "type-to-search" with no extra code."""
    if editable:
        dropdown = dcc.Dropdown(
            id=dd_id, multi=True, value=_lines(text),
            options=[{"label": v, "value": v} for v in drill_options],
            style={"fontFamily": "Teko, sans-serif"})
        child = html.Div([dropdown, _drill_catalog_controls(section_key, drill_options)]) \
            if is_coach else dropdown
    else:
        child = _bullet_view(text)
    return _card(title, child)


# =============================== VIDEO LIBRARY ===============================
# Shared Recovery Protocols / Gas Station titled-link video library (2026-09-10
# planning session): coach-managed, shown to every player rather than curated
# per plan. See app.data.splash_report.VIDEO_CATEGORIES/list_videos/add_video.

def _video_link(video: dict) -> html.Div:
    return html.Div(
        html.Button(f"▶ {video['title']}", id={"type": "splash-video-open", "index": video["id"]},
                   n_clicks=0, style={"border": "none", "background": "none", "color": CRIMSON,
                                      "textDecoration": "underline", "cursor": "pointer",
                                      "fontFamily": "Teko, sans-serif", "fontSize": "15px",
                                      "padding": "2px 0", "textAlign": "left"}),
        style={"display": "block"})


def _video_list_or_empty(videos: list[dict]) -> html.Div:
    """A titled-link list for one category (Recovery Protocols or Gas
    Station Videos) -- click a title to pop the clip up in the shared
    modal (`video_modal`/`_on_video_modal` in callbacks.py), never an
    embedded player inline on the page."""
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
    """One row in the Manage Video Library list: title, category, delete."""
    return html.Div([
        html.Span(f"{video['title']} ", style={"fontWeight": "bold"}),
        html.Span(f"({video['category']})", style={"color": "#666", "fontSize": "12px"}),
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
            ], style={"maxWidth": "320px", "marginBottom": "10px"}),
            html.Div([_video_row(v) for v in all_videos] or
                    [html.Div("No videos in the library yet.",
                             style={"color": "#888", "fontStyle": "italic"})]),
        ], id="splash-manage-videos-panel", style=_panel_style(open_)),
    ])


def _recovery_section(recovery_videos: list[dict], all_videos: list[dict], *,
                      is_coach: bool, manage_videos_open: bool) -> html.Div:
    children = [_video_list_or_empty(recovery_videos)]
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
                       drill_options=drill_options),
        _drill_section("Feet Moving", plan["feet_moving"], editable=editable, is_coach=is_coach,
                       dd_id="splash-feetmoving", section_key="feetmoving",
                       drill_options=drill_options),
        _drill_section("Work Day", plan["work_day"], editable=editable, is_coach=is_coach,
                       dd_id="splash-workday", section_key="workday",
                       drill_options=drill_options),
        _recovery_section(videos.get("Recovery", []),
                          videos.get("Recovery", []) + videos.get("Gas Station", []),
                          is_coach=is_coach, manage_videos_open=manage_videos_open),
    ]
    return html.Div(sections, className="paw-chart-grid",
                    style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "10px"})


def _days_ago(iso_date: str | None) -> str:
    if not iso_date:
        return "No readings logged yet."
    try:
        d = date.fromisoformat(str(iso_date)[:10])
    except ValueError:
        return "No readings logged yet."
    n = (date.today() - d).days
    if n <= 0:
        return "Last updated today."
    if n == 1:
        return "Last updated 1 day ago."
    return f"Last updated {n} days ago."


def _update_readings_panel(latest_date: str | None) -> html.Div:
    """Coach-only control, separate from the page's Edit/Save toggle: logs
    TODAY's Building-the-Engine reading as a new dated row (see
    `app.data.splash_report.upsert_engine_readings`) instead of overwriting
    the existing Base/Now -- so the every-2-week reassessment cadence
    builds a real trend instead of erasing it. Hidden by default; the
    toggle button reveals it (`splash-update-readings-open` Store)."""
    field_style = {"width": "90px", "padding": "4px", "borderRadius": "6px",
                   "border": "1px solid #ccc", "fontFamily": "Teko, sans-serif"}
    metric_fields = html.Div([
        html.Div([
            html.Label(SR.ENGINE_METRIC_LABELS[k], style={"fontSize": "12px", "color": "#555",
                                                           "display": "block"}),
            dcc.Input(id=f"splash-reading-{k}", type="number", placeholder="—",
                     style=field_style),
        ]) for k in SR.ENGINE_METRIC_KEYS
    ], style={"display": "flex", "gap": "10px", "flexWrap": "wrap", "margin": "10px 0"})
    return html.Div([
        html.Div([
            html.Button("Update Readings", id="splash-update-readings-toggle", n_clicks=0,
                       style={"border": f"2px solid {CRIMSON}", "background": "#fff",
                              "color": CRIMSON, "borderRadius": "14px", "padding": "4px 14px",
                              "cursor": "pointer", "fontFamily": "Teko, sans-serif",
                              "fontSize": "14px"}),
            html.Span(_days_ago(latest_date), style={"fontSize": "12px", "color": "#666",
                                                      "marginLeft": "10px"}),
        ]),
        html.Div([
            html.Div("Log today's numbers below -- this adds a new dated reading, it never "
                    "overwrites a past one.", style={"fontSize": "12px", "color": "#666"}),
            html.Div([html.Label("Date", style={"fontSize": "12px", "color": "#555"}),
                      dcc.Input(id="splash-reading-date", type="text",
                               value=date.today().isoformat(), style=field_style)],
                     style={"marginTop": "6px"}),
            metric_fields,
            html.Button("Save Reading", id="splash-update-readings-save", n_clicks=0,
                       style={"border": "none", "background": CRIMSON, "color": "#fff",
                              "borderRadius": "14px", "padding": "6px 16px", "cursor": "pointer",
                              "fontFamily": "Teko, sans-serif", "fontSize": "14px"}),
            html.Div(id="splash-update-readings-status",
                    style={"fontSize": "12px", "color": CRIMSON, "marginTop": "6px"}),
        ], id="splash-update-readings-panel", style={"display": "none", "marginTop": "8px"}),
        dcc.Store(id="splash-update-readings-open", data=False),
    ])


def engine_tables_block(engine_records: list) -> html.Div:
    """Just the Strength/ROM table pair -- factored out so the "View
    Cycles" filter callback (`_on_engine_cycle_filter` in callbacks.py) can
    rebuild exactly this and nothing else when a coach widens the view
    across cycles, instead of re-rendering the whole card."""
    eng = pd.DataFrame(engine_records)
    strength = eng[eng["metric_key"].isin(SR.STRENGTH_METRICS)] if not eng.empty else eng
    rom = eng[eng["metric_key"].isin(SR.ROM_METRICS)] if not eng.empty else eng
    # flex:1 on each table used to stretch it across half of a very wide
    # container, leaving a big blank gap between two content-sized tables
    # -- size to content instead so they sit close together.
    return html.Div([
        html.Div([html.B("Strength · lb"),
                  tables.engine_metrics_table(strength, "splash-engine-strength-table")],
                 style={"flex": "0 0 auto"}),
        html.Div([html.B("Range of Motion · °"),
                  tables.engine_metrics_table(rom, "splash-engine-rom-table")],
                 style={"flex": "0 0 auto"}),
    ], style={"display": "flex", "gap": "24px", "flexWrap": "wrap", "marginBottom": "12px"})


def engine_and_gas_station(engine_records: list, gas_records: list, gas_videos: list[dict], *,
                           editable: bool, is_coach: bool, latest_engine_date: str | None,
                           cycle: str) -> html.Div:
    """Body visual moved to the left sidebar (see `sidebar`) -- this card is
    back to just the Strength/ROM tables + View Cycles + Update Readings +
    Gas Station. 2026-09-11 feedback ("lots of white space on the Building
    the Engine side ... fill that in"): the Strength/ROM tables themselves
    got bigger (`tables._ENGINE_CELL_STYLE`) -- measured live, they now fill
    ~91% of this card's content width on their own (528px of 579px
    available at the card's actual rendered size), which is most of what
    was making the card feel sparse. A "Gas Station beside the tables"
    layout was tried and dropped: at that width there's only ~50px left in
    the row, nowhere near enough for a readable 4-column table, so it just
    wrapped to a second row every time anyway -- no different from stacking
    it below outright, just with extra flex-layout code pretending
    otherwise. The remaining sparseness below the tables is Gas Station
    actually having no rows entered yet, which is a data gap, not a layout
    one -- see this function's home commit/report for the measurement and
    the options considered (narrowing the sidebar/right columns to give
    this card more width; a denser Gas Station table style) if more is
    wanted."""
    gas = pd.DataFrame(gas_records)
    gas_child = tables.gas_station_table(gas, editable=editable) if (editable or not gas.empty) \
        else html.Div("Nothing entered yet.", style={"color": "#888", "fontStyle": "italic"})
    # "Seasonal cycle filter: multi-select (fall, winter, spring, or full
    # year)" -- 2026-09-10 planning session. Defaults to just the page's
    # currently-selected cycle (today's exact display); widening it re-reads
    # Base/Now/Δ across the union of the picked cycles (see
    # SR.read_engine_history's docstring) via `_on_engine_cycle_filter`.
    view_cycles = html.Div([
        html.Label("View Cycles", style={**_LABEL_STYLE, "textAlign": "left"}),
        dcc.Dropdown(id="splash-engine-cycle-filter",
                    options=[{"label": c, "value": c} for c in SR.CYCLES], multi=True,
                    value=[cycle], style={"fontFamily": "Teko, sans-serif",
                                          "marginBottom": "8px", "maxWidth": "360px"}),
    ])
    children = [
        view_cycles,
        html.Div(engine_tables_block(engine_records), id="splash-engine-tables-wrap"),
    ]
    if is_coach:
        children.append(_update_readings_panel(latest_engine_date))
    children.append(html.Div([html.B("The Gas Station"),
                  html.Div("Tie a specific exercise to whatever the numbers above flag.",
                          style={"fontSize": "12px", "color": "#666", "margin": "2px 0 6px"}),
                  gas_child]))
    children.append(html.Div([html.B("Gas Station Videos", style={"fontSize": "13px"}),
                              _video_list_or_empty(gas_videos)],
                             style={"marginTop": "10px"}))
    return _card("Building the Engine — Strength · ROM", html.Div(children))


def script_card(script_number, script_row: dict, rows: list, *, editable: bool) -> html.Div:
    goal = script_row["goal"]
    measurable = script_row["measurable"]
    goal_child = dcc.Input(id=f"splash-script-goal-{script_number}", value=goal,
                           type="text", style={"width": "100%"}) if editable \
        else html.Div(goal or "—")
    measurable_child = dcc.Input(id=f"splash-script-measurable-{script_number}",
                                 value=measurable, type="text", style={"width": "100%"}) \
        if editable else html.Div(measurable or "—")
    card = html.Div([
        html.Div(f"Script #{script_number}", style={"fontWeight": "bold", "color": CRIMSON}),
        html.Div([html.Span("Goal ", style={"fontSize": "11px", "color": "#666"}),
                  goal_child]),
        html.Div([html.Span("Measurable ", style={"fontSize": "11px", "color": "#666"}),
                  measurable_child], style={"marginTop": "4px"}),
        html.Div(tables.script_pitch_table(pd.DataFrame(rows), script_number, editable=editable),
                 style={"marginTop": "6px"}),
    ], style={"backgroundColor": "rgba(255,255,255,0.85)", "borderRadius": "8px",
              "padding": "10px", "marginBottom": "12px"})
    # ALWAYS rendered (never conditionally omitted) so its Save-form Inputs
    # stay valid targets for `callbacks._script_states()` regardless of
    # which scripts are currently picked in "splash-script-select" --
    # visibility is toggled client-side by wrapper display:none/block
    # instead, so hiding a script never risks a missing-State callback
    # error. See `_on_script_select` in callbacks.py.
    return html.Div(card, id=f"splash-script-wrap-{script_number}", style={"display": "none"})


def scripts_section(pen_records: list, scripts_records: list, script_rows: dict, *,
                    editable: bool) -> html.Div:
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
    ])
    if editable:
        graph_block.children.append(tables.pen_results_table(pen, editable=True))

    cards = [script_card(int(r["script_number"]), r, script_rows[str(int(r["script_number"]))],
                         editable=editable)
             for r in scripts_records]
    select_block = html.Div([
        html.Label("Show Scripts", style={**_LABEL_STYLE, "textAlign": "left"}),
        dcc.Dropdown(id="splash-script-select", options=compare_options, multi=True, value=[],
                    placeholder="Select a script to view or edit...",
                    style={"fontFamily": "Teko, sans-serif", "marginBottom": "8px"}),
        html.Div(cards, className="paw-chart-grid",
                style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "10px"}),
    ], style={"marginTop": "16px"})
    return _card(f"Bullpen Scripts · {SR.N_SCRIPTS} Scripts", html.Div([graph_block, select_block]))


def sidebar(profile: dict, kpis: dict, plan: dict, engine_records: list, *,
           editable: bool) -> html.Div:
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
    vision = _text_section("Vision Statement · Season Focus", plan["vision_statement"],
                           editable=editable, input_id="splash-vision")
    # Building the Engine's body visual moved here from the Building the
    # Engine card (2026-09-11 feedback: "fit on the white space in the left
    # column") -- five small panels (IR/ER/Scaption/Grip/ROM), see
    # app.dashboards.splash_report.body_visual. `splash-engine-visual-wrap`
    # keeps its id here so `_on_engine_cycle_filter` in callbacks.py (which
    # targets it by id, not position) still refreshes it when a coach
    # widens the View Cycles selection.
    visual = html.Div(body_visual.render(engine_records, profile.get("throws")),
                      id="splash-engine-visual-wrap", style={"marginTop": "10px"})
    return html.Div([profile_card, goals, vision, visual])


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
    latest_engine_date = SR.latest_engine_reading_date(pid, season_label, cycle)
    gas = SR.read_gas_station(pid, season_label, cycle)
    scripts = SR.read_scripts(pid, season_label, cycle)
    script_rows = SR.read_all_script_rows(pid, season_label, cycle)
    pen = SR.read_pen_results(pid, season_label, cycle)
    # Drill catalog + video library are global (coach-managed, not scoped to
    # a player/season/cycle), but loaded here too so render_from_data stays
    # a pure function of `data` with zero DB calls of its own -- these are
    # tiny tables, so re-reading them on every player/season/cycle switch is
    # cheap.
    drill_options = SR.read_drill_options()
    videos = {cat: SR.list_videos(cat).to_dict("records") for cat in SR.VIDEO_CATEGORIES}
    return {
        "profile": profile, "kpis": kpis, "plan": plan, "cycle": cycle,
        "engine": engine.to_dict("records"), "latest_engine_date": latest_engine_date,
        "gas": gas.to_dict("records"),
        "scripts": scripts.to_dict("records"),
        # dict keys round-trip through dcc.Store's JSON as strings either way;
        # use str() up front so in-process (no round trip yet) access matches.
        "script_rows": {str(n): df.to_dict("records") for n, df in script_rows.items()},
        "pen": pen.to_dict("records"),
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
    left = html.Div(sidebar(data["profile"], data["kpis"], plan, data["engine"],
                            editable=editable),
                    className="paw-dash-sidebar", style={"width": "290px", "flexShrink": "0"})
    videos = data.get("videos", {})
    center = html.Div([
        checklists_grid(plan, editable=editable, is_coach=is_coach,
                        drill_options=data.get("drill_options", []), videos=videos,
                        manage_videos_open=data.get("manage_videos_open", False)),
        engine_and_gas_station(data["engine"], data["gas"], videos.get("Gas Station", []),
                               editable=editable, is_coach=is_coach,
                               latest_engine_date=data.get("latest_engine_date"),
                               cycle=data.get("cycle")),
    ], style={"flex": "1 1 0", "minWidth": "0"})
    # Bullpen Scripts (pen-results trend on top, the 6 scripts collapsed
    # below it -- see scripts_section) sits alongside the sidebar+center on
    # a wide screen (matching the original mockup's 3-column layout)
    # instead of stacking below everything -- that stacking was what forced
    # most of the extra vertical scrolling on desktop; .paw-dash-row's
    # phone media query still stacks all three into one column on a narrow
    # screen.
    right = html.Div(scripts_section(data["pen"], data["scripts"], data["script_rows"],
                                     editable=editable),
                     style={"flex": "1 1 0", "minWidth": "0"})
    return html.Div([left, center, right], className="paw-dash-row",
                    style={"display": "flex", "gap": "12px", "flexWrap": "wrap",
                           "alignItems": "flex-start"})


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
        header(back_href="/pitching", back_label="← Pitching"),
        html.Div(controls, style={"borderBottom": f"2px solid {CRIMSON}",
                                  "backgroundColor": "rgba(255,255,255,0.55)"}),
        html.Div(id="splash-body",
                 children=render_from_data(data, editable=False, is_coach=is_coach),
                 style={"padding": "16px"}),
        video_modal(),
    ])
