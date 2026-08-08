"""Phase 5 defense-in-depth: all_pas_figure never crashes on an oversized df."""
import pandas as pd

from app.dashboards.hitting import charts


def _pa_rows(n_pas):
    """n_pas distinct (GameID, Inning, PAofInning) PAs, one pitch each."""
    return pd.DataFrame([
        {"GameID": g, "Inning": 1, "PAofInning": 1, "PitchofPA": 1,
         "TaggedPitchType": "Fastball", "PlateLocSide": 0.0, "PlateLocHeight": 2.5,
         "PitchCall": "StrikeCalled", "PlayResult": "Undefined"}
        for g in range(n_pas)
    ])


def test_all_pas_figure_caps_and_never_crashes():
    # 300 PAs would be a 100-row subplot grid -> make_subplots raises without
    # the cap. With the cap it builds exactly _MAX_PA_SUBPLOTS PA subplots.
    fig = charts.all_pas_figure(_pa_rows(300))
    assert fig is not None
    titles = [a for a in fig.layout.annotations if a.text]
    assert len(titles) == charts._MAX_PA_SUBPLOTS


def test_all_pas_figure_small_df_unchanged():
    fig = charts.all_pas_figure(_pa_rows(3))
    titles = [a for a in fig.layout.annotations if a.text]
    assert len(titles) == 3
