"""Location / Movement tab: pitch-type chip filter -> movement + location + table,
plus a year-over-year movement comparison for returning pitchers.

The chip/count/result/hand filters and the two figures at the top are scoped to
the CURRENT selection (one outing, or the whole date range). The year-over-year
panel underneath is deliberately NOT -- it is season vs season, read straight
from `pitcher_development.season_movement`, because "has his slider moved
differently this year?" is a question about full seasons, not about whichever
outing happens to be selected.
"""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import pitcher_development as PD
from app.data import pitching as P
from app.dashboards.pitching import tables
from app.dashboards.shell import section


def chip_row(df: pd.DataFrame, prefix: str) -> html.Div:
    """A clickable color chip per pitch type present (all active by default)."""
    types = list(P.pitch_type(df).value_counts().index)
    chips = [html.Button(
        pt, id={"type": f"{prefix}-chip", "index": pt}, n_clicks=0,
        style={"border": f"2px solid {P.pitch_color(pt)}", "background": P.pitch_color(pt),
               "color": "#fff", "borderRadius": "14px", "padding": "3px 12px",
               "margin": "0 6px 6px 0", "cursor": "pointer",
               "fontFamily": "Teko, sans-serif", "fontSize": "15px"})
        for pt in types]
    return html.Div([dcc.Store(id=f"{prefix}-active", data=types),
                     html.Div(chips)], style={"margin": "6px 0"})


def all_pitches(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "Pitch": P.pitch_type(df),
        "Count": df["balls"].astype("Int64").astype(str) + "-"
                 + df["strikes"].astype("Int64").astype(str),
        "Velo": df["rel_speed"].round(1),
        "Result": P.result_labels(df),
    }).reset_index(drop=True)


def body(df: pd.DataFrame) -> html.Div:
    if df.empty:
        return html.Div("No pitches for the selected pitch types.")
    return html.Div([
        html.Div([
            html.Div([section("Movement"), dcc.Graph(figure=P.fig_movement(df))],
                     style={"flex": "1"}),
            html.Div([section("Location"), dcc.Graph(figure=P.fig_location(df))],
                     style={"flex": "1"}),
        ], className="paw-chart-row", style={"display": "flex", "gap": "16px"}),
        section("All Pitches"),
        tables.df_table(all_pitches(df), id_="lm-all"),
    ])


def apply_filters(df: pd.DataFrame, *, pitch_types=None, counts=None,
                  results=None, hand="All") -> pd.DataFrame:
    """Compose the Movement Profile filters (all AND-ed together). Pure."""
    if df is None or df.empty:
        return df
    d = df
    if pitch_types is not None:
        d = d[P.pitch_type(d).isin(pitch_types)]
    if counts is not None:
        cs = (d["balls"].astype("Int64").astype(str) + "-"
              + d["strikes"].astype("Int64").astype(str))
        d = d[cs.isin(counts)]
    if results is not None:
        d = d[P.result_labels(d).isin(results)]
    if hand and hand != "All":
        d = d[d["batter_side"] == hand]
    return d


def _filter_row(df: pd.DataFrame) -> html.Div:
    counts = P.count_states(df)
    results = sorted(P.result_labels(df).dropna().unique())
    ctl = {"minWidth": "180px"}
    return html.Div([
        dcc.Dropdown(id="lm-count", multi=True, placeholder="Count(s)",
                     options=[{"label": c, "value": c} for c in counts],
                     value=counts, style=ctl),
        dcc.Dropdown(id="lm-result", multi=True, placeholder="Result(s)",
                     options=[{"label": r, "value": r} for r in results],
                     value=results, style=ctl),
        dcc.RadioItems(id="lm-hand", inline=True, value="All",
                       options=[{"label": "All", "value": "All"},
                                {"label": "vs RHH", "value": "Right"},
                                {"label": "vs LHH", "value": "Left"}],
                       style={"display": "inline-flex", "gap": "10px",
                              "alignItems": "center"}),
    ], style={"display": "flex", "gap": "12px", "flexWrap": "wrap",
              "alignItems": "center", "margin": "6px 0"})




# ---------------------------------------------------------------------------
# Year-over-year movement comparison (returning pitchers only).
# ---------------------------------------------------------------------------

# Inches of headroom around the union of both seasons' break extents, so a
# marker sitting at the extreme never lands on the axis line.
_YOY_PAD = 2.0
# Half-width applied when both seasons collapse to a single break value -- a
# zero-width range renders as a hairline and Plotly then ignores it.
_YOY_MIN_HALF_SPAN = 1.0


def _union_range(frames, col):
    """The [lo, hi] axis range covering `col` across ALL of `frames`, padded.

    Shared axes are the whole point of this panel: two movement scatters
    side by side that each autorange to their own data are actively
    MISLEADING -- a season with a tighter cluster gets zoomed in until it
    looks like the pitch moved more, not less. So both figures get the union
    of both seasons' extents. Returns None when nothing is plottable, in which
    case the caller leaves the axis alone.
    """
    vals = [f[col].dropna() for f in frames if col in getattr(f, "columns", [])]
    vals = pd.concat(vals, ignore_index=True) if vals else pd.Series(dtype="float64")
    if vals.empty:
        return None
    lo, hi = float(vals.min()), float(vals.max())
    if lo == hi:
        lo, hi = lo - _YOY_MIN_HALF_SPAN, hi + _YOY_MIN_HALF_SPAN
    return [lo - _YOY_PAD, hi + _YOY_PAD]


def _yoy_panel(season_label: str, df: pd.DataFrame, x_range, y_range) -> html.Div:
    """One side of the comparison: `fig_movement` with the SHARED axis ranges
    forced on afterwards (reusing the existing figure builder rather than
    writing a second movement plot)."""
    fig = P.fig_movement(df)
    if x_range:
        fig.update_xaxes(range=x_range)
    if y_range:
        fig.update_yaxes(range=y_range)
    fig.update_layout(title=f"Movement · {season_label}")
    return html.Div([
        html.Div(season_label, style={"fontFamily": "Teko, sans-serif",
                                      "fontSize": "18px", "fontWeight": "bold",
                                      "color": "#555"}),
        dcc.Graph(figure=fig),
    ], style={"flex": "1"})


def yoy_movement(pitcher_id, season):
    """Previous season LEFT, current season RIGHT -- or None.

    None (and therefore nothing rendered at all: no empty panel, no apology
    text) whenever there is no prior season in which this pitcher actually
    threw. `previous_season_with_data` walks BACK past redshirt/injury years,
    so "returning pitcher" here means "has tracked pitches in some earlier
    season", not "was on the roster last year".
    """
    if pitcher_id is None or not season:
        return None
    prev_label = PD.previous_season_with_data(int(pitcher_id), season)
    if not prev_label:
        return None
    prev_df = PD.season_movement(int(pitcher_id), prev_label)
    cur_df = PD.season_movement(int(pitcher_id), season)
    if prev_df.empty and cur_df.empty:
        return None
    x_range = _union_range([prev_df, cur_df], "horz_break")
    y_range = _union_range([prev_df, cur_df], "induced_vert_break")
    return html.Div([
        section("Year Over Year Movement"),
        html.Div([
            _yoy_panel(str(prev_label), prev_df, x_range, y_range),
            _yoy_panel(str(season), cur_df, x_range, y_range),
        ], className="paw-chart-row", style={"display": "flex", "gap": "16px"}),
    ])


def render(df: pd.DataFrame, pitcher_id=None, season=None) -> html.Div:
    """`pitcher_id` / `season` come from the `selection` store via
    `callbacks._render_tab` (the same way the Outing Trend tab is handed its
    pitcher). They are optional so a bare `render(df)` -- tests, and any caller
    that only has a dataframe -- still works, just without the year-over-year
    panel, which cannot be built from one selection's pitches alone."""
    if df.empty:
        return html.Div("No pitch data.")
    children = [chip_row(df, "lm"), _filter_row(df),
                html.Div(id="lm-body", children=body(df))]
    yoy = yoy_movement(pitcher_id, season)
    if yoy is not None:
        children.append(yoy)
    return html.Div(children)
