"""The hitting dashboard shell: sidebar + selector row + tab frame."""
from __future__ import annotations

from datetime import date

from dash import dcc, html
from flask_login import current_user

from app.data import hitting_caps, seasons, parallel
from app.data import video as videodata
from app.dashboards import date_range as dr, notes_ui
from app.dashboards.hitting import selectors
from app.dashboards.shell import (
    BANNER as _BANNER,
    CRIMSON as _CRIMSON,
    PHOTO_PLACEHOLDER as _PHOTO_PLACEHOLDER,
    header,
)


def _tile(label, value):
    return html.Div([
        html.Div(value, style={"fontSize": "28px", "fontWeight": "bold",
                               "color": _CRIMSON}),
        html.Div(label, style={"fontSize": "14px", "color": "#555"}),
    ], style={"textAlign": "center", "padding": "6px 10px",
              "backgroundColor": "rgba(255,255,255,0.8)", "borderRadius": "8px"})


def sidebar(batter_id, season=None, start=None, end=None) -> html.Div:
    if batter_id is None:
        return html.Div("Select a hitter.", style={"padding": "12px"})
    # Warm the two independent sidebar reads concurrently (helps the cold
    # player-selection callback path, not just first paint).
    parallel.prefetch(
        lambda: hitting_caps.player_profile(int(batter_id)),
        lambda: hitting_caps.sidebar_stats(int(batter_id), season, start, end),
    )
    prof = hitting_caps.player_profile(int(batter_id))
    slash = hitting_caps.sidebar_stats(int(batter_id), season, start, end)
    qab = slash["qab"]
    qab_txt = f"{round(qab * 100, 1)}%" if qab is not None else "—"
    photo = prof["photo"] or _PHOTO_PLACEHOLDER
    jersey = f"#{prof['jersey']} · " if prof["jersey"] else ""
    meta = " · ".join([x for x in (prof["class_year"], prof["position"],
                                   f"Bats {prof['bats']}" if prof["bats"] else "") if x])
    return html.Div([
        html.Img(src=photo, style={"width": "100%", "borderRadius": "8px",
                                   "border": "4px solid white",
                                   "background": "rgba(255,255,255,0.6)"}),
        html.Div(f"{jersey}{prof['name'] or '—'}",
                 style={"fontSize": "26px", "fontWeight": "bold", "marginTop": "8px"}),
        html.Div(meta, style={"fontSize": "16px", "color": "#555"}),
        # 2x3 grid (2-column, matching the other dashboards' sidebars).
        # POP-UP% lives on the HitTrax batting-practice dashboard, not here.
        html.Div([_tile("QAB%", qab_txt), _tile("BA", slash["BA"]),
                  _tile("SLG", slash["SLG"]), _tile("OBP", slash["OBP"]),
                  _tile("HARD-HIT%", slash["hard_hit_pct"]),
                  _tile("xBA", slash["xba"])],
                 style={"display": "grid", "gridTemplateColumns": "1fr 1fr",
                        "gap": "6px", "marginTop": "10px"}),
        html.Div("Stats reflect the selected date range.",
                 style={"fontSize": "12px", "color": "#555", "marginTop": "4px"}),
    ], style={"padding": "8px"})


def scoreboard(game_id, start=None, end=None, games_df=None) -> html.Div:
    if game_id == dr.ALL_IN_RANGE:
        return html.Div(dr.range_scoreboard_text(games_df, start, end),
                        style={"color": "white", "fontWeight": "bold",
                               "fontSize": "20px", "alignSelf": "center"})
    if not game_id:
        return html.Div()
    sb = hitting_caps.scoreboard(str(game_id))
    parts = [p for p in (sb["date"], f"{sb['loc']} {sb['opp']}".strip(),
                         sb["game_type"]) if p]
    return html.Div(" · ".join(parts),
                    style={"color": "white", "fontWeight": "bold",
                           "fontSize": "20px", "alignSelf": "center"})


def serve_layout() -> html.Div:
    if not current_user.is_authenticated:
        return html.Div("Please log in.")
    is_coach = bool(getattr(current_user, "is_coach", False))
    own = getattr(current_user, "trackman_id", None)
    # Default to today's real calendar season (bypassing current_season()'s
    # GAMES-only "latest season WITH data" preference), same fix as Velo
    # Board/Cauldron: once a new season starts, showing a stale-but-populated
    # prior season is worse than an honest empty view of the real one. See
    # docs/superpowers/specs/2026-08-25-post-slaa-fixes-design.md §4.
    season = seasons.season_label_for(date.today().isoformat())
    s_bound, e_bound = seasons.season_bounds(season)
    # Layer-2 fan-out: the unscoped + range-scoped roster reads and the season
    # list are mutually independent -- warm them concurrently so the sequential
    # code below reads cache hits instead of paying 3 serial round trips.
    parallel.prefetch(
        lambda: selectors.hitter_options(is_coach=is_coach, own_trackman_id=own,
                                         season=season),
        lambda: selectors.hitter_options(is_coach=is_coach, own_trackman_id=own,
                                         season=season, start=s_bound, end=e_bound),
        seasons.available_seasons,
    )
    hitters_all = selectors.hitter_options(is_coach=is_coach, own_trackman_id=own, season=season)
    default_batter = selectors.resolve_batter(
        hitters_all[0]["value"] if hitters_all else None,
        is_coach=is_coach, own_trackman_id=own)
    # Season is the OUTER scope; the date range + calendar nest inside the
    # selected academic year (Aug 1 -> Jul 31). Default range = the whole season.
    min_bound, max_bound = s_bound, e_bound
    start_d, end_d = s_bound, e_bound

    # First-paint options scoped to that same season-default range (mirrors
    # the _on_daterange_hitters callback) -- not every hitter in the season.
    # Fallback mirrors _on_daterange_hitters exactly: if the unscoped default
    # isn't in the range-scoped options, fall back to the first available
    # option's value (or None) -- NOT resolve_batter(), which would force a
    # player-role user back to their own id even when it's not among `hitters`.
    hitters = selectors.hitter_options(is_coach=is_coach, own_trackman_id=own,
                                       season=season, start=start_d, end=end_d)
    hitter_values = {h["value"] for h in hitters}
    if default_batter not in hitter_values:
        default_batter = hitters[0]["value"] if hitters else None

    # Layer-2 fan-out: once the default player is known, its games->video chain
    # and its two sidebar reads are mutually independent -- warm them together.
    if default_batter:
        parallel.prefetch(
            lambda: videodata.video_game_ids(
                hitting_caps.games_for_batter(default_batter, s_bound, e_bound),
                batter_id=default_batter),
            lambda: hitting_caps.player_profile(int(default_batter)),
            lambda: hitting_caps.sidebar_stats(int(default_batter), season, start_d, end_d),
        )

    games_df = (hitting_caps.games_for_batter(default_batter, s_bound, e_bound)
                if default_batter else None)
    if games_df is not None and not games_df.empty:
        games = dr.game_options(
            games_df, videodata.video_game_ids(games_df, batter_id=default_batter))
        default_game = str(games_df.iloc[0]["game_id"])
    else:
        games = []
        default_game = None

    selector_row = html.Div([
        html.Div([
            html.Label("Season", style={"color": "white", "fontWeight": "bold"}),
            dcc.Dropdown(id="hit-season",
                         options=[{"label": s, "value": s}
                                  for s in seasons.available_seasons()],
                         value=season, clearable=False,
                         style={"minWidth": "130px"}),
        ]),
        html.Div([
            html.Label("Hitter", style={"color": "white", "fontWeight": "bold"}),
            dcc.Dropdown(id="hitter-dd", options=hitters, value=default_batter,
                         clearable=False,
                         style={"minWidth": "220px"}),
        ]),
        html.Div([
            html.Label("Date range", style={"color": "white", "fontWeight": "bold"}),
            dr.date_control("hit", (end_d or date.today().isoformat()),
                            min_date=min_bound, max_date=max_bound, preset="season",
                            start=start_d, end=end_d),
        ]),
        html.Div([
            html.Label("Game", style={"color": "white", "fontWeight": "bold"}),
            dcc.Dropdown(id="game-dd", options=games, value=default_game,
                         clearable=False, style={"minWidth": "260px"}),
        ]),
        html.Div(id="scoreboard"),
    ], style={"display": "flex", "gap": "16px", "alignItems": "flex-end",
              "flexWrap": "wrap", "padding": "12px 16px", "backgroundColor": _BANNER})

    tabs = dcc.Tabs(id="tabs", value="game", children=[
        dcc.Tab(label="Game Level", value="game"),
        dcc.Tab(label="Video", value="video"),
        dcc.Tab(label="Balls in Play", value="bip"),
        dcc.Tab(label="Last 27 PA", value="last27"),
        dcc.Tab(label="Dev Plan", value="devplan"),
    ])

    return html.Div([
        dcc.Store(id="selection", data={"batter_id": default_batter,
                                        "game_id": default_game,
                                        "season": season,
                                        "start": start_d, "end": end_d}),
        dcc.Store(id="game-data"),
        header(back_href="/hitting", back_label="← Hitting"),
        html.Div([
            html.Div([
                html.Div(id="sidebar", children=sidebar(default_batter, season, start_d, end_d)),
                notes_ui.note_card("hitting"),
            ], className="paw-dash-sidebar", style={"width": "260px", "flexShrink": "0"}),
            html.Div([selector_row, tabs,
                      html.Div(id="tab-content", style={"padding": "8px 16px"})],
                     className="paw-dash-content", style={"flexGrow": "1"}),
        ], className="paw-dash-row", style={"display": "flex", "gap": "16px", "padding": "16px",
                  "alignItems": "flex-start"}),
    ])
