"""Render-smoke tests for the shared video component (no live DB needed)."""
import pandas as pd
from dash import dash_table, html

from app.dashboards import video as vc
from app.data import video as vdata


def _df():
    row = {c: "x" for c in vdata.DISPLAY_COLS}
    row.update({vdata.URL_COL[a]: (f"http://x/{a}.mp4" if a != "Broadcast" else None)
                for a, _ in vdata.ANGLES})
    row.update({"batter_side": "Right", "pitch_uid": "u1"})
    return pd.DataFrame([row])


def _walk(node):
    yield node
    for child in (getattr(getattr(node, "children", None), "__iter__", lambda: [])()
                  if isinstance(getattr(node, "children", None), (list, tuple))
                  else ([node.children] if getattr(node, "children", None) is not None else [])):
        if hasattr(child, "children") or hasattr(child, "id"):
            yield from _walk(child)


def test_empty_df_shows_empty_state():
    out = vc.render(pd.DataFrame(columns=vdata._ALL_COLS), prefix="pit", default_angle="HomeBehind")
    text = str(out)
    assert "No video" in text


def test_render_has_table_player_and_angle_buttons():
    out = vc.render(_df(), prefix="pit", default_angle="HomeBehind")
    ids = [getattr(n, "id", None) for n in _walk(out)]
    assert "pit-video-table" in ids
    assert "pit-video-player" in ids
    # four angle buttons as pattern-matching dict ids
    btns = [i for i in ids if isinstance(i, dict) and i.get("type") == "pit-angle"]
    assert len(btns) == 4


def test_resolve_default_prefers_broadcast_then_falls_back():
    from app.dashboards.video import component as comp
    angles = [a for a, _ in vdata.ANGLES]
    # pitch WITH a broadcast clip -> broadcast is chosen
    p_all = {"urls": {a: f"http://x/{a}.mp4" for a in angles}, "side": "Right"}
    assert comp._resolve_default(p_all, "Broadcast") == "Broadcast"
    # pitch WITHOUT broadcast -> falls back to an available angle (not empty)
    p_nob = {"urls": {a: (None if a == "Broadcast" else f"http://x/{a}.mp4")
                      for a in angles}, "side": "Right"}
    got = comp._resolve_default(p_nob, "Broadcast")
    assert got != "Broadcast" and p_nob["urls"][got]


def _contains(node, typ):
    if isinstance(node, typ):
        return True
    ch = getattr(node, "children", None)
    kids = ch if isinstance(ch, (list, tuple)) else ([ch] if ch is not None else [])
    return any(_contains(k, typ) for k in kids)


def test_video_display_cols_drops_date():
    # Item 2: Date column removed from the pitch table.
    assert "Date" not in vdata.DISPLAY_COLS


def test_video_is_left_and_larger_than_table():
    # Item 2: video is the dominant element on the left; table compact on the right.
    out = vc.render(_df(), prefix="pit", default_angle="HomeBehind")
    row = out.children[-1]                       # the two-column flex row
    left, right = row.children[0], row.children[1]
    assert _contains(left, html.Video)           # video on the left
    assert _contains(right, dash_table.DataTable)  # table on the right
    assert float(left.style["flex"]) > float(right.style["flex"])  # video column larger


def test_table_hides_url_columns_but_keeps_them_in_data():
    out = vc.render(_df(), prefix="hit", default_angle="batter_side")
    table = next(n for n in _walk(out)
                 if isinstance(n, dash_table.DataTable) and n.id == "hit-video-table")
    shown = [c["id"] for c in table.columns]
    assert shown == vdata.DISPLAY_COLS          # only display columns shown
    assert "url_homebehind" in table.data[0]    # url still present in row data
