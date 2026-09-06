"""Splash Report page shell: filters, sidebar, and the whole editable body."""
from __future__ import annotations

from datetime import date

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


def engine_and_gas_station(player_id, season_label, cycle, *, editable: bool) -> html.Div:
    eng = SR.read_engine_metrics(player_id, season_label, cycle)
    gas = SR.read_gas_station(player_id, season_label, cycle)
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


def script_card(script_number, script_row, rows, *, editable: bool) -> html.Div:
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
        html.Div(tables.script_pitch_table(rows, script_number, editable=editable),
                 style={"marginTop": "6px"}),
    ], style={"backgroundColor": "rgba(255,255,255,0.85)", "borderRadius": "8px",
              "padding": "10px", "marginBottom": "12px"})


def bullpen_scripts(player_id, season_label, cycle, *, editable: bool) -> html.Div:
    scripts = SR.read_scripts(player_id, season_label, cycle)
    # One query for all six scripts' pitch rows instead of one per script.
    all_rows = SR.read_all_script_rows(player_id, season_label, cycle)
    cards = [script_card(int(r["script_number"]), r, all_rows[int(r["script_number"])],
                         editable=editable)
             for _, r in scripts.iterrows()]
    return _card(f"Bullpen Scripts · {SR.N_SCRIPTS} Scripts",
                html.Div(cards, className="paw-chart-grid",
                        style={"display": "grid", "gridTemplateColumns": "1fr 1fr",
                               "gap": "12px"}))


def script_pen_results(player_id, season_label, cycle, *, editable: bool) -> html.Div:
    pen = SR.read_pen_results(player_id, season_label, cycle)
    fig = charts.pen_results_fig(pen)
    children = [dcc.Graph(figure=fig, config={"displayModeBar": False})]
    if editable:
        children.append(tables.pen_results_table(pen, editable=True))
    return _card("Script Pen Results — Trend", html.Div(children))


def sidebar(pitcher_id, season_label, *, editable: bool, plan: dict) -> html.Div:
    if pitcher_id is None:
        return html.Div("Select a pitcher.", style={"padding": "12px"})
    prof = pitching_caps.pitcher_profile(int(pitcher_id))
    # Scoped to the page's own Season filter -- range_summary(pid) with no
    # start/end silently defaults to the CURRENT season, which made the K%/
    # BB%/Barrel% tiles ignore the Season dropdown entirely (a real bug: they
    # never changed no matter what season was selected).
    s_b, e_b = seasons.season_bounds(season_label)
    summ = pitching_caps.range_summary(int(pitcher_id), s_b, e_b)
    photo = prof["photo"] or PHOTO_PLACEHOLDER
    jersey = f"#{prof['jersey']} · " if prof["jersey"] else ""
    meta = " · ".join([x for x in (prof["class_year"],
                                   f"Throws {prof['throws']}" if prof["throws"] else "") if x])

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
        html.Div(f"{jersey}{prof['name'] or '—'}",
                 style={"fontSize": "24px", "fontWeight": "bold", "marginTop": "8px"}),
        html.Div(meta, style={"fontSize": "15px", "color": "#555"}),
        html.Div([tile("K%", summ.get("k_pct")), tile("Barrel%", summ.get("barrel_pct")),
                  tile("BB%", summ.get("bb_pct"))],
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


def render_body(player_id, season_label, cycle, *, editable: bool) -> html.Div:
    if player_id is None:
        return html.Div("Select a pitcher.", style={"padding": "20px"})
    plan = SR.read_plan(player_id, season_label, cycle)
    left = html.Div(sidebar(player_id, season_label, editable=editable, plan=plan),
                    className="paw-dash-sidebar", style={"width": "260px", "flexShrink": "0"})
    center = html.Div([
        _text_section("Vision Statement · Season Focus", plan["vision_statement"],
                     editable=editable, input_id="splash-vision"),
        checklists_grid(plan, editable=editable),
        engine_and_gas_station(player_id, season_label, cycle, editable=editable),
        script_pen_results(player_id, season_label, cycle, editable=editable),
    ], style={"flex": "1 1 0", "minWidth": "0"})
    # Bullpen Scripts sits alongside the sidebar+center on a wide screen
    # (matching the original mockup's 3-column layout) instead of stacking
    # below everything -- that stacking was what forced most of the extra
    # vertical scrolling on desktop; .paw-dash-row's phone media query still
    # stacks all three into one column on a narrow screen.
    right = html.Div(bullpen_scripts(player_id, season_label, cycle, editable=editable),
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

    return html.Div([
        dcc.Store(id="splash-editing", data=False),
        header(back_href="/pitching", back_label="← Pitching"),
        html.Div(controls, style={"borderBottom": f"2px solid {CRIMSON}",
                                  "backgroundColor": "rgba(255,255,255,0.55)"}),
        html.Div(id="splash-body",
                 children=render_body(default_player, season, cycle, editable=False),
                 style={"padding": "16px"}),
    ])
