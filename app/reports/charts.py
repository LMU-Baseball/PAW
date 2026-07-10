"""Turn a Plotly figure into a self-contained base64 PNG data URI (kaleido)."""
from __future__ import annotations

import base64

import plotly.graph_objects as go


def fig_to_data_uri(fig: go.Figure, width: int = 800, height: int = 500,
                    scale: int = 2) -> str:
    png = fig.to_image(format="png", width=width, height=height, scale=scale)
    b64 = base64.b64encode(png).decode("ascii")
    return f"data:image/png;base64,{b64}"
