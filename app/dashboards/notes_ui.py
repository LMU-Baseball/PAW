"""Shared per-game coach-note card + callbacks for the game dashboards."""
from __future__ import annotations

from dash import Input, Output, State, dcc, html
from flask_login import current_user

from app.data import notes
from app.dashboards import date_range as dr

_CRIMSON = "#9A0021"
_BOX = {"fontStyle": "italic", "padding": "10px 12px",
        "backgroundColor": "rgba(255,255,255,0.75)", "borderRadius": "8px"}


def note_card(module: str) -> html.Div:
    """Persistent container; populated by the render callback on selection change."""
    return html.Div(id=f"{module}-note-card", style={"margin": "8px 0"})


def _header():
    return html.Div("Coach Note", style={"color": _CRIMSON, "fontWeight": "bold",
                                         "fontSize": "16px", "marginBottom": "4px"})


def _render_note(module: str, subject_id, game_id, is_coach: bool) -> html.Div:
    if subject_id is None or game_id is None or game_id == dr.ALL_IN_RANGE:
        return html.Div([_header(), html.Div(
            "Select a single game to add a note.", style={**_BOX, "color": "#888"})])
    text = notes.get_note(module, subject_id, game_id)
    if not is_coach:
        return html.Div([_header(),
                         html.Div(text or "No note for this game.", style=_BOX)])
    return html.Div([
        _header(),
        dcc.Textarea(id=f"{module}-note-text", value=text,
                     style={"width": "100%", "minHeight": "70px", "padding": "8px",
                            "borderRadius": "8px", "fontFamily": "Teko, sans-serif",
                            "fontSize": "15px"}),
        html.Div([
            html.Button("Save", id=f"{module}-note-save", n_clicks=0,
                        style={"background": _CRIMSON, "color": "#fff", "border": "none",
                               "borderRadius": "8px", "padding": "6px 16px",
                               "cursor": "pointer", "fontFamily": "Teko, sans-serif",
                               "marginRight": "8px"}),
            html.Button("Delete", id=f"{module}-note-delete", n_clicks=0,
                        style={"background": "#fff", "color": _CRIMSON,
                               "border": f"2px solid {_CRIMSON}", "borderRadius": "8px",
                               "padding": "5px 14px", "cursor": "pointer",
                               "fontFamily": "Teko, sans-serif"}),
            html.Span(id=f"{module}-note-status",
                      style={"marginLeft": "10px", "color": "#555", "fontSize": "14px"}),
        ], style={"marginTop": "6px"}),
    ])


def register_note_callbacks(dash_app, module: str, subject_key: str) -> None:
    @dash_app.callback(
        Output(f"{module}-note-card", "children"),
        Input("selection", "data"),
    )
    def _note_render(sel):
        sel = sel or {}
        is_coach = bool(getattr(current_user, "is_coach", False))
        return _render_note(module, sel.get(subject_key), sel.get("game_id"), is_coach)

    @dash_app.callback(
        Output(f"{module}-note-status", "children"),
        Input(f"{module}-note-save", "n_clicks"),
        State(f"{module}-note-text", "value"), State("selection", "data"),
        prevent_initial_call=True,
    )
    def _note_save(_n, text, sel):
        if not getattr(current_user, "is_coach", False):
            return "Coaches only."
        sel = sel or {}
        gid = sel.get("game_id")
        if sel.get(subject_key) is None or gid is None or gid == dr.ALL_IN_RANGE:
            return ""
        notes.upsert_note(module, sel[subject_key], gid, text,
                          getattr(current_user, "id", None))
        return "Saved." if (text or "").strip() else "Deleted."

    @dash_app.callback(
        Output(f"{module}-note-text", "value"),
        Output(f"{module}-note-status", "children", allow_duplicate=True),
        Input(f"{module}-note-delete", "n_clicks"),
        State("selection", "data"),
        prevent_initial_call=True,
    )
    def _note_delete(_n, sel):
        if not getattr(current_user, "is_coach", False):
            return "", "Coaches only."
        sel = sel or {}
        gid = sel.get("game_id")
        if sel.get(subject_key) is not None and gid is not None and gid != dr.ALL_IN_RANGE:
            notes.delete_note(module, sel[subject_key], gid)
        return "", "Deleted."
