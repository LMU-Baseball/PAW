"""Plate Appearances tab: per-PA zone scatter + pitch table; all-PAs facet."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.dashboards.hitting import charts, tables

_PA_TABLE_COLS = ["PitchofPA", "TaggedPitchType", "PitchCall", "PlayResult",
                  "Balls", "Strikes", "ExitSpeed", "Pitcher"]


def pa_choices(game_df: pd.DataFrame) -> list[dict]:
    if game_df is None or game_df.empty:
        return []
    keys = sorted(game_df.groupby(["Inning", "PAofInning"]).groups.keys())
    # Label by the hitter's sequential game PA (1,2,3…), not PAofInning.
    return [{"label": f"PA {seq} · Inn {int(i)}", "value": f"{int(i)}-{int(p)}"}
            for seq, (i, p) in enumerate(keys, 1)]


def _pa_slice(game_df, pa_value):
    keys = sorted(game_df.groupby(["Inning", "PAofInning"]).groups.keys())
    if not keys:
        return game_df.iloc[0:0]
    if pa_value:
        inn, pa = (int(x) for x in pa_value.split("-"))
    else:
        inn, pa = keys[0]
    return game_df[(game_df["Inning"] == inn) & (game_df["PAofInning"] == pa)]


def render_breakdown(game_df: pd.DataFrame, pa_value: str | None) -> html.Div:
    sub = _pa_slice(game_df, pa_value) if game_df is not None and not game_df.empty \
        else pd.DataFrame()
    fig = charts.zone_scatter(sub, title="Pitch Locations")
    cols = [c for c in _PA_TABLE_COLS if c in sub.columns]
    tbl = tables.stat_table(sub[cols] if not sub.empty else pd.DataFrame(),
                            id="tbl-pa")
    return html.Div([
        html.Div(dcc.Graph(figure=fig, config={"displayModeBar": False}),
                 style={"maxWidth": "560px"}),
        tbl,
    ])


def render_all_pas(game_df: pd.DataFrame) -> dcc.Graph | html.Div:
    """All-PAs facet grid, capped to the 12 most recent PAs when pooling a range.

    A pooled multi-game df carries a `GameID` column (every game reuses Inning 1,
    PAofInning 1, etc., so GameID must be part of the PA key to avoid conflating
    PAs across games); a single game's df has no GameID variation, so the cap is
    keyed by Inning/PAofInning alone there (a no-op — a game has only a handful).
    """
    df = game_df
    capped_note = None
    if df is not None and not df.empty:
        key_cols = ["GameID", "Inning", "PAofInning"] if "GameID" in df.columns \
            else ["Inning", "PAofInning"]
        keys = df[key_cols].drop_duplicates()
        if len(keys) > 12:
            recent = keys.tail(12)
            df = df.merge(recent, on=key_cols, how="inner")
            capped_note = f"showing 12 most recent of {len(keys)} PAs"

    graph = dcc.Graph(figure=charts.all_pas_figure(df),
                      config={"displayModeBar": False})
    if not capped_note:
        return graph
    return html.Div([
        html.Div(capped_note, style={"fontSize": "13px", "color": "#888",
                                     "marginBottom": "4px"}),
        graph,
    ])
