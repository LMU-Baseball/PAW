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


def test_table_hides_url_columns_but_keeps_them_in_data():
    out = vc.render(_df(), prefix="hit", default_angle="batter_side")
    table = next(n for n in _walk(out)
                 if isinstance(n, dash_table.DataTable) and n.id == "hit-video-table")
    shown = [c["id"] for c in table.columns]
    assert shown == vdata.DISPLAY_COLS          # only display columns shown
    assert "url_homebehind" in table.data[0]    # url still present in row data
