"""Plate Appearances tab: per-PA zone scatter + pitch table; all-PAs facet."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.dashboards.hitting import charts, tables

_PA_TABLE_COLS = ["PitchofPA", "TaggedPitchType", "PitchCall", "PlayResult",
                  "Balls", "Strikes", "ExitSpeed", "Pitcher"]


def _pa_keys(game_df: pd.DataFrame) -> list[tuple]:
    """Ordered composite PA identity: (GameID, Inning, PAofInning).

    A pooled multi-game df reuses Inning/PAofInning per game (every game has its
    own Inning 1, PAofInning 1, …), so GameID must be part of the key or PAs from
    different games collapse together. GameID defaults to 0 when the column is
    absent so a single game's grouping/ordering is unaffected.
    """
    if "GameID" not in game_df.columns:
        return [(0, i, p) for i, p in
                sorted(game_df.groupby(["Inning", "PAofInning"]).groups.keys())]
    return sorted(game_df.groupby(["GameID", "Inning", "PAofInning"]).groups.keys())


def _pa_value(key: tuple) -> str:
    # GameID is an opaque string (numeric surrogate or composite like
    # "20220311-GoodwinField-1"), so it is NOT int()'d; Inning/PAofInning are
    # numeric. "|" is a safe delimiter (composite ids use "-", never "|").
    gid, inn, pa = key
    return f"{gid}|{int(inn)}|{int(pa)}"


def pa_choices(game_df: pd.DataFrame) -> list[dict]:
    if game_df is None or game_df.empty:
        return []
    keys = _pa_keys(game_df)
    multi_game = len({k[0] for k in keys}) > 1
    choices = []
    # Label by the hitter's sequential game PA (1,2,3…), not PAofInning.
    for seq, key in enumerate(keys, 1):
        gid, inn, pa = key
        label = f"PA {seq} · Inn {inn}"
        if multi_game:
            label = f"G{gid} · {label}"
        choices.append({"label": label, "value": _pa_value(key)})
    return choices


def _pa_slice(game_df, pa_value):
    keys = _pa_keys(game_df)
    if not keys:
        return game_df.iloc[0:0]
    if pa_value:
        gid_s, inn_s, pa_s = pa_value.split("|", 2)
        gid, inn, pa = gid_s, int(inn_s), int(pa_s)
    else:
        gid, inn, pa = keys[0]
    mask = (game_df["Inning"] == inn) & (game_df["PAofInning"] == pa)
    if "GameID" in game_df.columns:
        mask &= (game_df["GameID"].astype(str) == str(gid))
    return game_df[mask]


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

    PA identity is `["GameID", "Inning", "PAofInning"]` (every game reuses Inning
    1, PAofInning 1, etc., so GameID must be part of the PA key to avoid
    conflating PAs across games). `GameID` is always present (from `_PITCH_SELECT`)
    but constant for a single game, so the cap is a no-op there — a game has only
    a handful of PAs.
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
