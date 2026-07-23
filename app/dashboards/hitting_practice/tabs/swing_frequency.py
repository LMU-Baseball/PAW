"""Swing Frequency tab — KPIs, Swing Decision Score, EV/dist, zone bars."""
from __future__ import annotations

import pandas as pd
from dash import dcc, html

from app.data import practice as P
from app.dashboards.hitting_practice import charts, tables
from app.dashboards.shell import CRIMSON, section


def _tile(label, value):
    return html.Div([
        html.Div(str(value), style={"fontSize": "28px", "fontWeight": "bold",
                                    "color": CRIMSON}),
        html.Div(label, style={"fontSize": "14px", "color": "#555"}),
    ], style={"textAlign": "center", "padding": "10px 14px",
              "backgroundColor": "rgba(255,255,255,0.85)", "borderRadius": "8px",
              "minWidth": "110px"})


def _fmt(v, suffix=""):
    return "—" if v is None else f"{v}{suffix}"


def render(df: pd.DataFrame) -> html.Div:
    if df.empty:
        return html.Div("No pitch data for these filters.",
                        style={"color": "#555", "padding": "12px"})
    d = P.trim_to_first_contact(df)
    summ = P.contact_summary(d)
    sds = P.swing_decision_score(d)
    zone = P.zone_contact_table(d)
    contacts = d[d["is_contact"]] if "is_contact" in d.columns else d.iloc[0:0]
    avg_ev = (round(float(contacts["exit_velocity"].dropna().mean()), 1)
              if not contacts.empty and contacts["exit_velocity"].notna().any()
              else None)

    tiles = html.Div([
        _tile("Pitches", summ["pitches"]),
        _tile("Contacts", summ["contacts"]),
        _tile("Contact%", _fmt(summ["contact_pct"], "%")),
        _tile("Avg EV", _fmt(avg_ev, " mph")),
    ], style={"display": "flex", "gap": "10px", "flexWrap": "wrap",
              "marginBottom": "12px"})
    score_tiles = html.Div([
        _tile("In-Zone Contact%", _fmt(sds["in_zone_pct"], "%")),
        _tile("Chase Contact%", _fmt(sds["chase_pct"], "%")),
        _tile("Swing Decision Score", _fmt(sds["score"])),
    ], style={"display": "flex", "gap": "10px", "flexWrap": "wrap",
              "marginBottom": "12px"})

    # Session detail table
    if not d.empty:
        sess = (d.groupby("play_date")
                .agg(Pitches=("result", "count"),
                     Contacts=("is_contact", "sum"))
                .reset_index())
        sess["Contact%"] = (100.0 * sess["Contacts"] / sess["Pitches"]).round(1)
        sess["play_date"] = pd.to_datetime(sess["play_date"]).dt.strftime("%Y-%m-%d")
        sess = sess.rename(columns={"play_date": "Date"}).sort_values("Date", ascending=False)
    else:
        sess = pd.DataFrame()

    return html.Div([
        section("Swing Frequency"),
        tiles,
        section("Swing Decision Score"),
        score_tiles,
        html.Div("Score = In-Zone Contact% (zones 1–9) − Chase Contact% (zones 10–13).",
                 style={"fontSize": "12px", "color": "#888", "marginBottom": "8px"}),
        dcc.Graph(figure=charts.ev_distance_by_pitch(d)),
        dcc.Graph(figure=charts.contact_by_zone_bars(zone)),
        section("Session Detail"),
        tables.df_table(sess, id_="sf-session-table") if not sess.empty
        else html.Div("No sessions."),
    ])
