"""Development Plan tab: per-player coach-authored plan (coach edits, player reads)."""
from __future__ import annotations

from dash import dcc, html

from app.data import dev_plans

_CRIMSON = "#9A0021"
_BOX = {"fontStyle": "italic", "padding": "10px 12px",
        "backgroundColor": "rgba(255,255,255,0.75)", "borderRadius": "8px"}


def _header():
    return html.Div("Development Plan", style={"color": _CRIMSON, "fontWeight": "bold",
                    "fontSize": "18px", "marginBottom": "6px"})


def render(subject_id, is_coach: bool) -> html.Div:
    if subject_id is None:
        return html.Div([_header(),
                         html.Div("Select a hitter.", style={**_BOX, "color": "#888"})])
    text = dev_plans.get_plan("hitting", subject_id)
    if not is_coach:
        return html.Div([_header(),
                         html.Div(text or "No development plan yet.", style=_BOX)])
    return html.Div([
        _header(),
        dcc.Textarea(id="devplan-text", value=text,
                     style={"width": "100%", "minHeight": "220px", "padding": "10px",
                            "borderRadius": "8px", "fontFamily": "Teko, sans-serif",
                            "fontSize": "16px"}),
        html.Div([
            html.Button("Save", id="devplan-save", n_clicks=0,
                        style={"background": _CRIMSON, "color": "#fff", "border": "none",
                               "borderRadius": "8px", "padding": "6px 18px",
                               "cursor": "pointer", "fontFamily": "Teko, sans-serif",
                               "marginRight": "8px"}),
            html.Button("Delete", id="devplan-delete", n_clicks=0,
                        style={"background": "#fff", "color": _CRIMSON,
                               "border": f"2px solid {_CRIMSON}", "borderRadius": "8px",
                               "padding": "5px 16px", "cursor": "pointer",
                               "fontFamily": "Teko, sans-serif"}),
            html.Span(id="devplan-status",
                      style={"marginLeft": "10px", "color": "#555", "fontSize": "14px"}),
        ], style={"marginTop": "8px"}),
    ], style={"padding": "10px 4px", "maxWidth": "820px"})
