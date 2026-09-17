"""DataTable builders for Built on the Bluff's editable grids."""
from __future__ import annotations

import pandas as pd
from dash import dash_table

from app.data import splash_report as SR

_HEADER_STYLE = {"backgroundColor": "#9A0021", "color": "white",
                 "fontWeight": "bold", "textAlign": "center"}
_CELL_STYLE = {"textAlign": "center", "padding": "6px 8px",
              "fontFamily": "Teko, sans-serif", "fontSize": "15px"}
_TABLE_STYLE = {"overflowX": "auto", "width": "fit-content", "maxWidth": "100%"}


def _table(id_, columns, data, *, editable: bool, row_deletable: bool = False,
          dropdown=None, extra_style=None, cell_style=None, header_style=None,
          cell_conditional=None) -> dash_table.DataTable:
    return dash_table.DataTable(
        id=id_, columns=columns, data=data, editable=editable,
        row_deletable=row_deletable, dropdown=dropdown or {},
        style_table=_TABLE_STYLE, style_as_list_view=True,
        style_header=header_style or _HEADER_STYLE, style_cell=cell_style or _CELL_STYLE,
        style_cell_conditional=cell_conditional or [],
        style_data={"backgroundColor": "rgba(255,255,255,0.85)"},
        style_data_conditional=extra_style or [],
        markdown_options={"link_target": "_blank"},
    )


# Bigger than the shared _CELL_STYLE -- Building the Engine's two tables sit
# alone in their own card now that the body visual moved to the sidebar
# (2026-09-11 feedback: "lots of white space on the Building the Engine
# side"), so a larger, easier-to-read grid helps fill it. Not applied to
# every table site-wide -- the script/gas-station/pen-results grids are
# already dense (many rows/columns) and don't have the same spare room.
_ENGINE_CELL_STYLE = {"textAlign": "center", "padding": "10px 16px",
                      "fontFamily": "Teko, sans-serif", "fontSize": "19px"}
_ENGINE_HEADER_STYLE = {**_HEADER_STYLE, "fontSize": "16px", "padding": "8px 16px"}


_FLAG_STYLE = {
    "ok": {"backgroundColor": "#d4edda", "color": "#1e5b28"},
    "yellow": {"backgroundColor": "#fff3cd", "color": "#7a5c00"},
    "red": {"backgroundColor": "#f8d7da", "color": "#7a1420"},
}
_DELTA_STYLE = {
    "up": {"backgroundColor": "#d4edda", "color": "#1e5b28"},
    "down": {"backgroundColor": "#f8d7da", "color": "#7a1420"},
}


def engine_metrics_table(df: pd.DataFrame, table_id: str, *,
                         label_header: str = "", editable: bool = False) -> dash_table.DataTable:
    """Label / Base / Now / Δ. Base and Now are plain manually-typed cells
    (`editable` -- true only in the page's Edit mode, same as every other
    grid here; a coach's edits flow through the page's normal Save button
    into `app.data.splash_report.upsert_engine_metrics`, not a separate
    action). `now_value` is colored by `flag` ("ok"/"yellow"/"red"/None)
    against the D1 baseline; Δ is colored green/red by its own sign
    (positive = green, negative = red, zero/blank = neutral) -- the one
    piece of this table that's still derived, not typed. Called twice per
    page (Strength + ROM), so `table_id` must be distinct each time -- a
    duplicate Dash component id is invalid. `label_header` (2026-09-14,
    Brad: fold "Strength"/"Range of Motion" into the red header bar as white
    text instead of a separate black label above the table) fills the
    otherwise-blank top-left header cell."""
    d = df.copy()
    delta_sign = d["delta"].map(lambda v: None if pd.isna(v) else ("up" if v > 0 else
                                                                    "down" if v < 0 else None))
    d["delta"] = d["delta"].map(lambda v: "—" if pd.isna(v) else f"{v:+.1f}")
    columns = [
        {"name": label_header, "id": "label", "editable": False},
        {"name": "Base", "id": "base_value", "editable": editable, "type": "numeric"},
        {"name": "Now", "id": "now_value", "editable": editable, "type": "numeric"},
        {"name": "Δ", "id": "delta", "editable": False},
    ]
    extra_style = [
        {"if": {"row_index": i, "column_id": "now_value"}, **style}
        for i, flag in enumerate(d.get("flag", []))
        for style in ([_FLAG_STYLE[flag]] if flag in _FLAG_STYLE else [])
    ] + [
        {"if": {"row_index": i, "column_id": "delta"}, **_DELTA_STYLE[sign]}
        for i, sign in enumerate(delta_sign) if sign in _DELTA_STYLE
    ]
    return _table(table_id, columns, d.to_dict("records"), editable=False,
                 extra_style=extra_style, cell_style=_ENGINE_CELL_STYLE,
                 header_style=_ENGINE_HEADER_STYLE)


def gas_station_table(df: pd.DataFrame, gas_videos: list[dict], *,
                      editable: bool) -> dash_table.DataTable:
    """Need (dropdown) / Exercise / Sets x Reps / Notes -- variable rows.

    2026-09-16 round 4 (Brad): the "Gas Station Videos" library used to be
    a separate browsable list under this table -- now a video is tied to
    ONE exercise row directly, in the Exercise cell itself. A coach picks
    from `gas_videos` via a filterable dropdown (Dash's dropdown cells
    narrow as you type, same as `need`'s) while editing; everyone else
    just sees that pick rendered as a plain link, same as any other titled
    video on this page. `exercise` still stores the video's plain title
    text (no schema change) -- the link is built at render time by
    matching that text against `gas_videos`, so a legacy free-typed
    exercise that isn't a known video title just renders as plain text."""
    video_by_title = {v["title"]: v for v in gas_videos}
    columns = [
        {"name": "Need", "id": "need", "editable": editable, "presentation": "dropdown"},
        {"name": "Exercise", "id": "exercise", "editable": editable,
         "presentation": "dropdown" if editable else "markdown"},
        {"name": "Sets x Reps", "id": "sets_reps", "editable": editable},
        {"name": "Notes", "id": "notes", "editable": editable},
    ]
    dropdown = {"need": {"options": [{"label": v, "value": v} for v in
                                     SR.STRENGTH_NEED_OPTIONS]}}
    if editable:
        # 2026-09-16 round 6 (Brad): "add a way to search... so the coach
        # doesn't have to scroll the entire thing" -- the cell already
        # filters live as you type (Dash's built-in dropdown-cell behavior,
        # matching anywhere in the label -- category prefix or the drill
        # name), but that's not discoverable without a visible search box,
        # and `gas_videos` arrives sorted newest-first (`SR.list_videos`),
        # which is meaningless order for scanning by eye. Sorting here by
        # category then title makes scrolling without typing usable too.
        sorted_videos = sorted(
            gas_videos, key=lambda v: (v.get("drill_category") or v["category"], v["title"]))
        dropdown["exercise"] = {"options": [
            {"label": f"{v.get('drill_category') or v['category']} — {v['title']}",
             "value": v["title"]}
            for v in sorted_videos
        ]}
    data = df[["need", "exercise", "sets_reps", "notes"]].to_dict("records") \
        if not df.empty else []
    if not editable:
        for row in data:
            title = row.get("exercise") or ""
            video = video_by_title.get(title)
            # A markdown-presentation cell renders None as the literal text
            # "null" (JSON round-trip through the frontend, unlike a plain
            # cell which shows blank) -- coerce to "" up front so a row with
            # no exercise typed still renders empty.
            if video:
                url = video.get("link_url") or f"/splash-video/{video['id']}"
                row["exercise"] = f"[{title}]({url})"
            else:
                row["exercise"] = title
    if editable and len(data) < 8:
        data = data + [{"need": "", "exercise": "", "sets_reps": "", "notes": ""}
                      for _ in range(8 - len(data))]
    # 2026-09-16 round 7 (Brad): "without anything in the column it is
    # skinny and hard to read" -- an empty/short exercise cell had nothing
    # to size the column against (every other column here is either short,
    # fixed-option, or numeric), so a long drill title or link truncated
    # hard. A generous fixed width fixes both the empty-column case and the
    # truncation; left-aligned since centering a long title/link reads
    # worse than centering "3x10".
    cell_conditional = [
        {"if": {"column_id": "exercise"}, "minWidth": "260px", "width": "260px",
         "textAlign": "left"},
    ]
    return _table("splash-gas-table", columns, data, editable=editable,
                 row_deletable=editable, dropdown=dropdown,
                 cell_conditional=cell_conditional)


def script_pitch_table(df: pd.DataFrame, script_number: int, *,
                       editable: bool) -> dash_table.DataTable:
    """# (readonly 1-12) / Type / Ball / Info -- always exactly 12 rows."""
    columns = [
        {"name": "#", "id": "row_num", "editable": False},
        {"name": "Type", "id": "pitch_type", "editable": editable},
        {"name": "Ball", "id": "ball_info", "editable": editable},
        {"name": "Info", "id": "info", "editable": editable},
    ]
    return _table(f"splash-script-rows-{script_number}", columns,
                 df.to_dict("records"), editable=editable)


def pen_results_table(df: pd.DataFrame, *, editable: bool) -> dash_table.DataTable:
    """Script # / Pen Date / Value% -- variable rows, one shared table across
    all 6 scripts (pen_number is derived at read time, not a user-facing
    column here). Each row's `data` dict also carries `id` -- not declared
    in `columns` so it never renders, but Dash round-trips extra keys on a
    row through edits untouched, which is how `_on_save`
    (app.dashboards.splash_report.callbacks) tells `SR.save_pen_results`
    "this is row #N, not a new one" without showing a raw database id to a
    coach. A freshly-added blank row has no `id` key at all, which
    `save_pen_results` treats as "insert new." Deleting a row here is safe
    now -- see that function's docstring -- it soft-deletes rather than
    destroying it, and it's recoverable from "Recently Removed.\""""
    columns = [
        {"name": "Script #", "id": "script_number", "editable": editable, "type": "numeric"},
        {"name": "Pen Date (YYYY-MM-DD)", "id": "pen_date", "editable": editable},
        {"name": "Value %", "id": "value", "editable": editable, "type": "numeric"},
    ]
    data = df[["id", "script_number", "pen_date", "value"]].to_dict("records") \
        if not df.empty else []
    if editable and len(data) < 6:
        data = data + [{"script_number": None, "pen_date": "", "value": None}
                      for _ in range(6 - len(data))]
    return _table("splash-pen-table", columns, data, editable=editable,
                 row_deletable=editable)


def movement_table(df: pd.DataFrame, script_number: int, *, editable: bool) -> dash_table.DataTable:
    """Pitch Type / Pen Date / HB / IVB -- variable rows, ONE script's
    movement entries (unlike pen_results_table, not shared across all 6 --
    see `app.data.splash_report.save_movement`). Same `id`-round-tripping/
    soft-delete idiom as `pen_results_table`."""
    columns = [
        {"name": "Pitch Type", "id": "pitch_type", "editable": editable},
        {"name": "Pen Date (YYYY-MM-DD)", "id": "pen_date", "editable": editable},
        {"name": "HB", "id": "hb", "editable": editable, "type": "numeric"},
        {"name": "IVB", "id": "ivb", "editable": editable, "type": "numeric"},
    ]
    data = df[["id", "pitch_type", "pen_date", "hb", "ivb"]].to_dict("records") \
        if not df.empty else []
    if editable and len(data) < 4:
        data = data + [{"pitch_type": "", "pen_date": "", "hb": None, "ivb": None}
                      for _ in range(4 - len(data))]
    return _table(f"splash-script-movement-table-{script_number}", columns, data,
                 editable=editable, row_deletable=editable)
