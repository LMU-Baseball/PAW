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
from app.dashboards.shell import BANNER, CRIMSON, PHOTO_PLACEHOLDER, header, edit_save_buttons
from app.dashboards.splash_report import charts, tables

_CARD = {"backgroundColor": "rgba(255,255,255,0.85)", "borderRadius": "8px",
         "padding": "12px 14px", "marginBottom": "16px"}
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
    kwargs = {"style": _CARD}
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


def _drill_section(title: str, text: str, *, editable: bool, dd_id: str) -> html.Div:
    """Feet Set/Feet Moving/Work Day: a fixed multi-select catalog (the
    coaches' real drill list), not free text -- see
    `app.data.splash_report.FEET_DRILL_OPTIONS`."""
    if editable:
        child = dcc.Dropdown(
            id=dd_id, multi=True, value=_lines(text),
            options=[{"label": v, "value": v} for v in SR.FEET_DRILL_OPTIONS],
            style={"fontFamily": "Teko, sans-serif"})
    else:
        child = _bullet_view(text)
    return _card(title, child)


def _recovery_section(url: str) -> html.Div:
    """Placeholder for now: a single demonstration video, added later."""
    if url:
        child = html.Video(src=url, controls=True, style={"width": "100%", "borderRadius": "8px"})
    else:
        child = html.Div("No recovery video yet.",
                         style={"color": "#888", "fontStyle": "italic"})
    return _card("Recovery Protocols", child)


def checklists_grid(plan: dict, *, editable: bool) -> html.Div:
    sections = [
        _text_section("Pre-Throw Checklist", plan["pre_throw_checklist"],
                     editable=editable, input_id="splash-pre"),
        _text_section("Post-Throw Checklist", plan["post_throw_checklist"],
                     editable=editable, input_id="splash-post"),
        _drill_section("Feet Set", plan["feet_set"], editable=editable, dd_id="splash-feetset"),
        _drill_section("Feet Moving", plan["feet_moving"], editable=editable,
                       dd_id="splash-feetmoving"),
        _drill_section("Work Day", plan["work_day"], editable=editable, dd_id="splash-workday"),
        _recovery_section(plan["recovery_video_url"]),
    ]
    return html.Div(sections, className="paw-chart-grid",
                    style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "12px"})


def engine_and_gas_station(engine_records: list, gas_records: list, *, editable: bool) -> html.Div:
    eng = pd.DataFrame(engine_records)
    gas = pd.DataFrame(gas_records)
    strength = eng[eng["metric_key"].isin(SR.STRENGTH_METRICS)]
    rom = eng[eng["metric_key"].isin(SR.ROM_METRICS)]
    gas_child = tables.gas_station_table(gas, editable=editable) if (editable or not gas.empty) \
        else html.Div("Nothing entered yet.", style={"color": "#888", "fontStyle": "italic"})
    return _card("Building the Engine — Strength · ROM", html.Div([
        # flex:1 on each table used to stretch it across half of a very wide
        # container, leaving a big blank gap between two content-sized
        # tables -- size to content instead so they sit close together.
        html.Div([
            html.Div([html.B("Strength · lb"),
                      tables.engine_metrics_table(strength, "splash-engine-strength-table",
                                                  editable=editable)],
                     style={"flex": "0 0 auto"}),
            html.Div([html.B("Range of Motion · °"),
                      tables.engine_metrics_table(rom, "splash-engine-rom-table",
                                                  editable=editable)],
                     style={"flex": "0 0 auto"}),
        ], style={"display": "flex", "gap": "24px", "flexWrap": "wrap", "marginBottom": "12px"}),
        html.Div([html.B("The Gas Station"),
                  html.Div("Tie a specific exercise to whatever the numbers above flag.",
                          style={"fontSize": "12px", "color": "#666", "margin": "2px 0 6px"}),
                  gas_child]),
    ]))


def script_card(script_number, script_row: dict, rows: list, *, editable: bool) -> html.Div:
    goal = script_row["goal"]
    measurable = script_row["measurable"]
    goal_child = dcc.Input(id=f"splash-script-goal-{script_number}", value=goal,
                           type="text", style={"width": "100%"}) if editable \
        else html.Div(goal or "—")
    measurable_child = dcc.Input(id=f"splash-script-measurable-{script_number}",
                                 value=measurable, type="text", style={"width": "100%"}) \
        if editable else html.Div(measurable or "—")
    return html.Div([
        html.Div(f"Script #{script_number}", style={"fontWeight": "bold", "color": CRIMSON}),
        html.Div([html.Span("Goal ", style={"fontSize": "11px", "color": "#666"}),
                  goal_child]),
        html.Div([html.Span("Measurable ", style={"fontSize": "11px", "color": "#666"}),
                  measurable_child], style={"marginTop": "4px"}),
        html.Div(tables.script_pitch_table(pd.DataFrame(rows), script_number, editable=editable),
                 style={"marginTop": "6px"}),
    ], style={"backgroundColor": "rgba(255,255,255,0.85)", "borderRadius": "8px",
              "padding": "10px", "marginBottom": "12px"})


def bullpen_scripts(scripts_records: list, script_rows: dict, *, editable: bool) -> html.Div:
    cards = [script_card(int(r["script_number"]), r, script_rows[str(int(r["script_number"]))],
                         editable=editable)
             for r in scripts_records]
    return _card(f"Bullpen Scripts · {SR.N_SCRIPTS} Scripts",
                html.Div(cards, className="paw-chart-grid",
                        style={"display": "grid", "gridTemplateColumns": "1fr 1fr",
                               "gap": "12px"}))


def script_pen_results(pen_records: list, *, editable: bool) -> html.Div:
    pen = pd.DataFrame(pen_records)
    fig = charts.pen_results_fig(pen)
    children = [dcc.Graph(figure=fig, config={"displayModeBar": False})]
    if editable:
        children.append(tables.pen_results_table(pen, editable=True))
    return _card("Script Pen Results — Trend", html.Div(children))


def sidebar(profile: dict, kpis: dict, plan: dict, *, editable: bool) -> html.Div:
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
    return html.Div([profile_card, goals])


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
    return {
        "profile": profile, "kpis": kpis, "plan": plan,
        "engine": engine.to_dict("records"), "gas": gas.to_dict("records"),
        "scripts": scripts.to_dict("records"),
        # dict keys round-trip through dcc.Store's JSON as strings either way;
        # use str() up front so in-process (no round trip yet) access matches.
        "script_rows": {str(n): df.to_dict("records") for n, df in script_rows.items()},
        "pen": pen.to_dict("records"),
    }


def render_from_data(data: dict, *, editable: bool) -> html.Div:
    """Pure render: builds the whole body from an already-loaded `data` dict
    (see `load_data`) -- no DB calls here at all."""
    if not data:
        return html.Div("Select a pitcher.", style={"padding": "20px"})
    plan = data["plan"]
    left = html.Div(sidebar(data["profile"], data["kpis"], plan, editable=editable),
                    className="paw-dash-sidebar", style={"width": "260px", "flexShrink": "0"})
    center = html.Div([
        _text_section("Vision Statement · Season Focus", plan["vision_statement"],
                     editable=editable, input_id="splash-vision"),
        checklists_grid(plan, editable=editable),
        engine_and_gas_station(data["engine"], data["gas"], editable=editable),
        script_pen_results(data["pen"], editable=editable),
    ], style={"flex": "1 1 0", "minWidth": "0"})
    # Bullpen Scripts sits alongside the sidebar+center on a wide screen
    # (matching the original mockup's 3-column layout) instead of stacking
    # below everything -- that stacking was what forced most of the extra
    # vertical scrolling on desktop; .paw-dash-row's phone media query still
    # stacks all three into one column on a narrow screen.
    right = html.Div(bullpen_scripts(data["scripts"], data["script_rows"], editable=editable),
                     style={"flex": "1 1 0", "minWidth": "0"})
    return html.Div([left, center, right], className="paw-dash-row",
                    style={"display": "flex", "gap": "16px", "flexWrap": "wrap",
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
                 children=render_from_data(data, editable=False),
                 style={"padding": "16px"}),
    ])
