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


def test_zone_frequency_fig_empty_grid_is_placeholder():
    import plotly.graph_objects as go
    from app.data.hitting import zone_frequency_grid
    fig = charts.zone_frequency_fig(zone_frequency_grid(pd.DataFrame()), metric="ev")
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 0  # placeholder figure, no heatmap trace


def test_zone_frequency_fig_renders_heatmap_with_values():
    import plotly.graph_objects as go
    grid = [[{"value": None, "n": 0}, {"value": 80.0, "n": 3}, {"value": 90.0, "n": 2}],
            [{"value": 85.0, "n": 4}, {"value": 95.0, "n": 10}, {"value": 88.0, "n": 5}],
            [{"value": 70.0, "n": 1}, {"value": 92.0, "n": 6}, {"value": 91.0, "n": 3}]]
    fig = charts.zone_frequency_fig(grid, metric="ev")
    assert isinstance(fig, go.Figure)
    heat = fig.data[0]
    assert isinstance(heat, go.Heatmap)
    assert "n=0" in heat.text[0][0]  # missing cell shown as em-dash + n=0
    assert "n=3" in heat.text[0][1]


def test_zone_frequency_fig_avg_formats_batting_average():
    grid = [[{"value": None, "n": 0} for _ in range(3)] for _ in range(3)]
    grid[1][1] = {"value": 0.325, "n": 20}
    fig = charts.zone_frequency_fig(grid, metric="avg")
    assert ".325" in fig.data[0].text[1][1]


def test_zone_frequency_fig_uses_muted_colorscale_not_stock_rdbu():
    """Stock Plotly "RdBu" runs to near-black at both ends (unreadable
    against the cell text) -- must use the muted custom scale instead."""
    grid = [[{"value": 80.0, "n": 3} for _ in range(3)] for _ in range(3)]
    fig = charts.zone_frequency_fig(grid, metric="ev")
    assert fig.data[0].colorscale != "RdBu"
    stops = [c[1].lower() for c in fig.data[0].colorscale]
    assert "#053061" not in stops and "#67001f" not in stops


def test_zone_frequency_fig_compact_hides_colorbar_and_shortens_title():
    grid = [[{"value": 80.0, "n": 3} for _ in range(3)] for _ in range(3)]
    fig = charts.zone_frequency_fig(grid, metric="ev", compact=True)
    assert fig.data[0].showscale is False
    assert fig.layout.title.text == "Avg Exit Velocity"  # no "Zone Frequency --" prefix
    assert fig.layout.height == 340


def test_zone_pitch_frequency_fig_uses_sequential_scale_and_plain_counts():
    import plotly.graph_objects as go
    grid = [[{"value": None, "n": 0}, {"value": 4, "n": 4}, {"value": 9, "n": 9}],
            [{"value": 6, "n": 6}, {"value": 15, "n": 15}, {"value": 3, "n": 3}],
            [{"value": 1, "n": 1}, {"value": 8, "n": 8}, {"value": 5, "n": 5}]]
    fig = charts.zone_pitch_frequency_fig(grid)
    assert isinstance(fig, go.Figure)
    heat = fig.data[0]
    assert isinstance(heat, go.Heatmap)
    assert heat.colorscale != "RdBu"
    assert len(heat.colorscale) == 2  # single-hue light->dark, not diverging
    assert heat.text[0][0] == "0"  # empty cell -> plain "0", no "n=" suffix
    assert heat.text[0][1] == "4"


def test_zone_pitch_frequency_fig_empty_is_placeholder():
    import plotly.graph_objects as go
    from app.data.hitting import zone_pitch_frequency_grid
    fig = charts.zone_pitch_frequency_fig(zone_pitch_frequency_grid(pd.DataFrame()))
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 0
