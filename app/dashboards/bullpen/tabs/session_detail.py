"""Session Detail tab — one bullpen session in detail (interactive report)."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import bullpen as B
from app.data import pitching as P
from app.dashboards.bullpen import charts, tables

_MUTED = {"padding": "12px", "color": "#555"}

# snake_case -> friendly Title-Case headers for the all-pitches table.
_PITCH_HEADERS = {
    "pitch_no": "Pitch #", "tagged_pitch_type": "Pitch",
    "rel_speed": "Velo", "spin_rate": "Spin", "spin_eff": "Spin Eff",
    "ind_vert_break": "IVB", "horz_break": "HB", "vert_break": "VB",
    "rel_height": "Rel H", "rel_side": "Rel S", "extension": "Ext",
    "plate_loc_side": "Loc Side", "plate_loc_height": "Loc Ht", "tilt": "Tilt",
}

# snake_case -> friendly Title-Case headers for the stats-by-pitch-type summary table.
_SUMMARY_HEADERS = {
    "pitch": "Pitch", "qty": "#",
    "velo_min": "Velo Min", "velo_max": "Velo Max", "velo_avg": "Velo Avg",
    "spin_min": "Spin Min", "spin_max": "Spin Max", "spin_avg": "Spin Avg",
    "ivb_avg": "IVB Avg", "hb_avg": "HB Avg", "vert_avg": "VB Avg",
    "rel_h_avg": "Rel H Avg", "rel_side_avg": "Rel S Avg", "ext_avg": "Ext Avg",
}


def _round2(df: pd.DataFrame) -> pd.DataFrame:
    """Round every float column to 2 decimals."""
    out = df.copy()
    float_cols = out.select_dtypes(include="float").columns
    out[float_cols] = out[float_cols].round(2)
    return out


def _display_pitches(df: pd.DataFrame) -> pd.DataFrame:
    """All-pitches table for display: renumber pitch 1..N, round floats to 2dp,
    rename snake_case columns to friendly Title-Case headers."""
    out = _round2(df)
    if "pitch_no" in out.columns:
        out["pitch_no"] = range(1, len(out) + 1)
    return out.rename(columns=_PITCH_HEADERS)


def _display_summary(summ_df: pd.DataFrame) -> pd.DataFrame:
    """Stats-by-pitch-type summary table for display: round floats to 2dp and
    rename snake_case columns to friendly Title-Case headers."""
    out = _round2(summ_df)
    return out.rename(columns=_SUMMARY_HEADERS)


def render(pitcher_id, date) -> html.Div:
    if pitcher_id is None:
        return html.Div("Select a pitcher.", style=_MUTED)
    if not date:
        return html.Div("No bullpen session in this date range.", style=_MUTED)
    df = B.session_pitches(int(pitcher_id), date)
    if df.empty:
        return html.Div("No pitches for this session.", style=_MUTED)

    summ_df = pd.DataFrame(B.summary_by_pitch_type(df))
    graph = lambda fig: dcc.Graph(figure=fig, style={"height": "340px"})
    charts_grid = html.Div(
        [graph(charts.velo_fig(df)), graph(charts.movement_fig(df)),
         graph(charts.release_fig(df)), graph(charts.location_fig(df))],
        className="paw-chart-grid",
        style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "12px"})

    fb = P.fastball_callout(df, pt_col="tagged_pitch_type")
    callout = html.Div()
    if fb["avg_velo"] is not None:
        avg_spin = fb["avg_spin"] if fb["avg_spin"] is not None else "—"
        callout = html.Div([html.B("Fastball"),
            f" — Avg Velo {fb['avg_velo']} · Max {fb['max_velo']} · Avg Spin {avg_spin}"],
            style={"padding": "6px 4px", "color": "#555", "fontSize": "15px"})

    return html.Div([
        tables.df_table(_display_summary(summ_df), id_="bp-summary", color_col="Pitch"),
        callout,
        html.Div(style={"height": "12px"}),
        html.H4(f"Pitch Frequency (Total {len(df)})",
                style={"color": "#9A0021", "margin": "4px 0 0"}),
        dcc.Graph(figure=charts.pitch_freq_bar(df), style={"height": "150px"}),
        html.Div(style={"height": "12px"}),
        charts_grid,
        html.H4("All pitches", style={"color": "#9A0021", "marginTop": "14px"}),
        tables.df_table(_display_pitches(df), id_="bp-pitches", color_col="Pitch"),
    ])
