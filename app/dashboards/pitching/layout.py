"""The pitching dashboard shell: sidebar + selector row + tab frame."""
from __future__ import annotations

from datetime import date

from dash import dcc, html
from flask_login import current_user

from app.data import pitcher_development, pitching_caps, seasons, parallel
from app.data import video as videodata
from app.dashboards import date_range as dr, notes_ui
from app.dashboards.shell import BANNER, CRIMSON, PHOTO_PLACEHOLDER, header
from app.dashboards.pitching import selectors


def _tile(label, value):
    return html.Div([
        html.Div(value, style={"fontSize": "28px", "fontWeight": "bold", "color": CRIMSON}),
        html.Div(label, style={"fontSize": "14px", "color": "#555"}),
    ], style={"textAlign": "center", "padding": "6px 10px",
              "backgroundColor": "rgba(255,255,255,0.8)", "borderRadius": "8px"})


# ---------------------------------------------------------------------------
# Development-trend callout (season over season), under the KPI tiles.
# ---------------------------------------------------------------------------

# WHICH WAY IS BETTER, PER METRIC. The raw sign of `current - previous` says
# nothing about whether the pitcher improved, so colour is driven by
# `delta * _GOOD_DIRECTION[metric]` and NEVER by the sign of the delta alone.
# +1 = higher is better, -1 = lower is better. A pitcher whose BB% or Barrel%
# went UP has got worse and must render red, not green -- that inversion is the
# single most important line in this file.
_GOOD_DIRECTION = {
    "avg_velo": +1,     # throwing harder is better
    "max_velo": +1,     # throwing harder is better
    "k_pct": +1,        # more strikeouts is better
    "bb_pct": -1,       # more walks allowed is WORSE
    "barrel_pct": -1,   # more barrels allowed is WORSE
}

_DEV_LABELS = {"avg_velo": "Avg Velo", "max_velo": "Max Velo", "k_pct": "K%",
               "bb_pct": "BB%", "barrel_pct": "Barrel%"}
# The three rate stats print with a trailing '%'; the velo pair is bare mph.
_DEV_SUFFIX = {"k_pct": "%", "bb_pct": "%", "barrel_pct": "%"}

# Improvement / regression / no-meaningful-change. Deliberately NOT the brand
# crimson for "worse": crimson is this app's neutral accent (every KPI tile
# above uses it), so reusing it here would read as "normal", not "down".
_BETTER, _WORSE, _FLAT = "#1B7A3F", "#B00020", "#666"
# className mirrors the colour so a test (and a future stylesheet) can assert on
# the SEMANTICS -- better/worse -- rather than on a hex string.
_BETTER_CLASS, _WORSE_CLASS, _FLAT_CLASS = ("paw-delta-better", "paw-delta-worse",
                                            "paw-delta-flat")


def _short_season(label) -> str:
    """'2024/2025' -> "'25" -- the spring year, which is how coaches name a
    season, and short enough for a 260px sidebar. Anything not in YYYY/YYYY
    form passes through untouched."""
    text = str(label or "")
    tail = text.split("/")[-1]
    return f"'{tail[-2:]}" if len(tail) == 4 and tail.isdigit() else text


def _delta_badge(metric, delta) -> html.Div:
    """The coloured arrow row: direction from the sign, COLOUR from whether
    that direction is an improvement for this particular metric."""
    suffix = _DEV_SUFFIX.get(metric, "")
    if round(float(delta), 1) == 0:
        # Rounds to nothing at display precision -- render it flat rather than
        # an arrow pointing at "+0.0", which reads as a change that isn't one.
        return html.Div(f"± 0.0{suffix}", className=_FLAT_CLASS,
                        style={"fontSize": "13px", "color": _FLAT})
    improved = float(delta) * _GOOD_DIRECTION[metric] > 0
    arrow = "▲" if delta > 0 else "▼"
    return html.Div(f"{arrow} {delta:+.1f}{suffix}",
                    className=_BETTER_CLASS if improved else _WORSE_CLASS,
                    style={"fontSize": "13px", "fontWeight": "bold",
                           "color": _BETTER if improved else _WORSE})


def _dev_card(metric, current, previous, deltas):
    """One metric: small-caps label, the big current number, then (only when
    there IS a comparison) the delta badge and last season's value.

    Returns None -- so the caller drops it -- when the metric is missing this
    season; a blank card is worse than one fewer card.
    """
    value = current.get(metric)
    if value is None:
        return None
    suffix = _DEV_SUFFIX.get(metric, "")
    kids = [
        html.Div(_DEV_LABELS[metric],
                 style={"fontSize": "11px", "letterSpacing": "1px",
                        "textTransform": "uppercase", "color": "#555"}),
        html.Div(f"{value:.1f}{suffix}",
                 style={"fontSize": "22px", "fontWeight": "bold", "color": CRIMSON,
                        "lineHeight": "1.1"}),
    ]
    # `metric in deltas` is the render guard the data layer is built around: a
    # metric missing on EITHER side is absent from the dict (not present-as-
    # None), and `deltas` is empty outright for a first-year pitcher -- so this
    # one test covers both "no previous season" and "no previous value".
    if metric in deltas:
        kids.append(_delta_badge(metric, deltas[metric]))
        kids.append(html.Div(
            f"{_short_season(previous['label'])} {previous[metric]:.1f}{suffix}",
            style={"fontSize": "11px", "color": "#777"}))
    return html.Div(kids, style={"textAlign": "center", "padding": "6px 8px",
                                 "backgroundColor": "rgba(255,255,255,0.8)",
                                 "borderRadius": "8px"})


def development_callout(pitcher_id, season=None) -> html.Div:
    """Season-over-season development block for the sidebar.

    Season-scoped, NOT date-range-scoped -- unlike the KPI tiles above it --
    because "did he add a tick this year?" is only meaningful against whole
    seasons. Hence the explicit season caption: two blocks of numbers stacked
    in one sidebar under different scopes would otherwise be a trap.

    Renders the current values with no arrows and no previous row when there is
    no prior season with data; no "N/A", no apology text.
    """
    comp = pitcher_development.season_comparison(int(pitcher_id), season)
    current, previous = comp["current"], comp["previous"]
    deltas = comp["deltas"] or {}
    cards = [c for c in (_dev_card(m, current, previous, deltas)
                         for m in pitcher_development.DELTA_METRICS) if c is not None]
    if not cards:
        return html.Div()   # nothing measurable this season -- show nothing
    caption = f"Development · {_short_season(current['label'])}"
    if previous:
        caption += f" vs {_short_season(previous['label'])}"
    return html.Div([
        html.Div(caption, style={"fontSize": "13px", "fontWeight": "bold",
                                 "color": CRIMSON, "marginTop": "12px"}),
        html.Div(cards, style={"display": "grid", "gridTemplateColumns": "1fr 1fr",
                               "gap": "6px", "marginTop": "4px"}),
        html.Div("Season totals, not the date range above.",
                 style={"fontSize": "11px", "color": "#777", "marginTop": "4px"}),
    ])


def sidebar(pitcher_id, start=None, end=None, season=None) -> html.Div:
    if pitcher_id is None:
        return html.Div("Select a pitcher.", style={"padding": "12px"})
    # The development callout is season-over-season, so it needs the SELECTED
    # season (threaded down from the `pit-season` dropdown) rather than the
    # date range that scopes the tiles above it. Defaulting keeps the older
    # 3-arg call signature working.
    season = season or seasons.current_season()
    # Warm the three independent sidebar reads concurrently (helps the cold
    # player-selection callback path, not just first paint).
    parallel.prefetch(
        lambda: pitching_caps.pitcher_profile(int(pitcher_id)),
        lambda: pitching_caps.range_summary(int(pitcher_id), start, end),
        lambda: pitcher_development.season_comparison(int(pitcher_id), season),
    )
    prof = pitching_caps.pitcher_profile(int(pitcher_id))
    summ = pitching_caps.range_summary(int(pitcher_id), start, end)
    photo = prof["photo"] or PHOTO_PLACEHOLDER
    jersey = f"#{prof['jersey']} · " if prof["jersey"] else ""
    meta = " · ".join([x for x in (prof["class_year"], prof["position"],
                                   f"Throws {prof['throws']}" if prof["throws"] else "") if x])
    return html.Div([
        html.Img(src=photo, style={"width": "100%", "borderRadius": "8px",
                                   "border": "4px solid white",
                                   "background": "rgba(255,255,255,0.6)"}),
        html.Div(f"{jersey}{prof['name'] or '—'}",
                 style={"fontSize": "26px", "fontWeight": "bold", "marginTop": "8px"}),
        html.Div(meta, style={"fontSize": "16px", "color": "#555"}),
        html.Div([_tile("APP", summ["appearances"]), _tile("IP", summ["ip"]),
                  _tile("K%", summ["k_pct"]), _tile("BB%", summ["bb_pct"]),
                  _tile("Barrel%", summ["barrel_pct"])],
                 style={"display": "grid", "gridTemplateColumns": "1fr 1fr",
                        "gap": "6px", "marginTop": "10px"}),
        html.Div("Stats reflect the selected date range · Barrel = 95+ mph EV (provisional).",
                 style={"fontSize": "12px", "color": "#555", "marginTop": "4px"}),
        development_callout(pitcher_id, season),
    ], style={"padding": "8px"})


def scoreboard(game_id, start=None, end=None, games_df=None) -> html.Div:
    if game_id == dr.ALL_IN_RANGE:
        return html.Div(dr.range_scoreboard_text(games_df, start, end),
                        style={"color": "white", "fontWeight": "bold",
                               "fontSize": "20px", "alignSelf": "center"})
    if not game_id:
        return html.Div()
    try:
        ctx = pitching_caps.game_context(str(game_id))
    except Exception:
        return html.Div()
    opp = ctx["away_team"] if ctx["lmu_is_home"] else ctx["home_team"]
    loc = "vs" if ctx["lmu_is_home"] else "@"
    parts = [str(ctx["game_date"]), f"{loc} {opp}", ctx.get("game_type") or ""]
    return html.Div(" · ".join(p for p in parts if p),
                    style={"color": "white", "fontWeight": "bold",
                           "fontSize": "20px", "alignSelf": "center"})


def serve_layout() -> html.Div:
    if not current_user.is_authenticated:
        return html.Div("Please log in.")
    is_coach = bool(getattr(current_user, "is_coach", False))
    own = getattr(current_user, "trackman_id", None)
    season = seasons.current_season()
    s_bound, e_bound = seasons.season_bounds(season)
    # Layer-2 fan-out: the unscoped + range-scoped roster reads and the season
    # list are mutually independent -- warm them concurrently so the sequential
    # code below reads cache hits instead of paying 3 serial round trips.
    parallel.prefetch(
        lambda: selectors.pitcher_options(is_coach=is_coach, own_trackman_id=own,
                                           season=season),
        lambda: selectors.pitcher_options(is_coach=is_coach, own_trackman_id=own,
                                           season=season, start=s_bound, end=e_bound),
        seasons.available_seasons,
    )
    pitchers_all = selectors.pitcher_options(is_coach=is_coach, own_trackman_id=own, season=season)
    default_pitcher = selectors.resolve_pitcher(
        pitchers_all[0]["value"] if pitchers_all else None,
        is_coach=is_coach, own_trackman_id=own)
    # Season is the OUTER scope; the date range + calendar nest inside the
    # selected academic year (Aug 1 -> Jul 31). Default range = the whole season.
    min_bound, max_bound = s_bound, e_bound
    start_d, end_d = s_bound, e_bound

    # First-paint options scoped to that same season-default range (mirrors
    # the _on_daterange_pitchers callback) -- not every pitcher in the season.
    # Fallback mirrors _on_daterange_pitchers exactly: if the unscoped default
    # isn't in the range-scoped options, fall back to the first available
    # option's value (or None) -- NOT resolve_pitcher(), which would force a
    # player-role user back to their own id even when it's not among `pitchers`.
    pitchers = selectors.pitcher_options(is_coach=is_coach, own_trackman_id=own,
                                         season=season, start=start_d, end=end_d)
    pitcher_values = {p["value"] for p in pitchers}
    if default_pitcher not in pitcher_values:
        default_pitcher = pitchers[0]["value"] if pitchers else None

    # Layer-2 fan-out: once the default player is known, its games->video chain
    # and its two sidebar reads are mutually independent -- warm them together.
    if default_pitcher:
        parallel.prefetch(
            lambda: videodata.video_game_ids(
                pitching_caps.games_for_pitcher(default_pitcher, s_bound, e_bound),
                pitcher_id=default_pitcher),
            lambda: pitching_caps.pitcher_profile(int(default_pitcher)),
            lambda: pitching_caps.range_summary(int(default_pitcher), start_d, end_d),
            lambda: pitcher_development.season_comparison(int(default_pitcher), season),
        )

    games_df = (pitching_caps.games_for_pitcher(default_pitcher, s_bound, e_bound)
                if default_pitcher else None)
    if games_df is not None and not games_df.empty:
        outings = dr.game_options(
            games_df, videodata.video_game_ids(games_df, pitcher_id=default_pitcher))
        default_game = str(games_df.iloc[0]["game_id"])  # most recent single game (opaque id)
    else:
        outings = []
        default_game = None

    selector_row = html.Div([
        html.Div([
            html.Label("Season", style={"color": "white", "fontWeight": "bold"}),
            dcc.Dropdown(id="pit-season",
                         options=[{"label": s, "value": s}
                                  for s in seasons.available_seasons()],
                         value=season, clearable=False,
                         style={"minWidth": "130px"}),
        ]),
        html.Div([
            html.Label("Pitcher", style={"color": "white", "fontWeight": "bold"}),
            dcc.Dropdown(id="pitcher-dd", options=pitchers, value=default_pitcher,
                         clearable=False,
                         style={"minWidth": "220px"}),
        ]),
        html.Div([
            html.Label("Date range", style={"color": "white", "fontWeight": "bold"}),
            dr.date_control("pit", (end_d or date.today().isoformat()),
                            min_date=min_bound, max_date=max_bound, preset="season",
                            start=start_d, end=end_d),
        ]),
        html.Div([
            html.Label("Outing", style={"color": "white", "fontWeight": "bold"}),
            dcc.Dropdown(id="outing-dd", options=outings, value=default_game,
                         clearable=False, style={"minWidth": "260px"}),
        ]),
        html.Div(id="scoreboard"),
    ], style={"display": "flex", "gap": "16px", "alignItems": "flex-end",
              "flexWrap": "wrap", "padding": "12px 16px", "backgroundColor": BANNER})

    tabs = dcc.Tabs(id="tabs", value="breakdown", children=[
        dcc.Tab(label="Personal Breakdown", value="breakdown"),
        dcc.Tab(label="Movement Profile", value="location"),
        dcc.Tab(label="Outing Overview", value="outings"),
        dcc.Tab(label="Outing Video", value="pitchlevel"),
        dcc.Tab(label="Count Performance", value="counts"),
        dcc.Tab(label="Zone Frequency", value="heatmaps"),
    ])

    return html.Div([
        dcc.Store(id="selection", data={"pitcher_id": default_pitcher,
                                        "game_id": default_game,
                                        "season": season,
                                        "start": start_d, "end": end_d}),
        dcc.Store(id="game-data"),
        header(back_href="/pitching", back_label="← Pitching"),
        html.Div([
            html.Div([
                html.Div(id="sidebar", children=sidebar(default_pitcher, start_d, end_d, season)),
                notes_ui.note_card("pitching"),
            ], className="paw-dash-sidebar", style={"width": "260px", "flexShrink": "0"}),
            html.Div([selector_row, tabs,
                      html.Div(id="tab-content", style={"padding": "8px 16px"})],
                     className="paw-dash-content", style={"flexGrow": "1"}),
        ], className="paw-dash-row", style={"display": "flex", "gap": "16px", "padding": "16px",
                  "alignItems": "flex-start"}),
    ])
