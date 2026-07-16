"""Turn a Plotly figure into a self-contained base64 PNG data URI (kaleido)."""
from __future__ import annotations

import base64
import threading
from contextlib import contextmanager

import kaleido
import plotly.graph_objects as go

# kaleido renders each figure by driving a headless Chrome. Cold-starting that
# Chrome per figure costs ~3s each (~30s for a full report's ~9 charts). Keeping
# one Chrome alive for the whole batch drops it to ~0.2s per figure after the
# first. The kaleido sync server is process-global, so builds are serialized
# with a lock to keep concurrent report requests from starting/stopping each
# other's server.
_render_lock = threading.Lock()


@contextmanager
def rendering_session():
    """Keep one headless Chrome alive for a batch of fig_to_data_uri() calls.

    Wrap all of a report's chart rendering in a single `with rendering_session():`
    so the figures share one Chrome process instead of cold-starting one each.
    """
    with _render_lock:
        kaleido.start_sync_server()
        try:
            yield
        finally:
            kaleido.stop_sync_server()


def fig_to_data_uri(fig: go.Figure, width: int = 800, height: int = 500,
                    scale: int = 2) -> str:
    """Render a Plotly figure to a base64 PNG data URI.

    Reuses the running kaleido server when called inside rendering_session();
    falls back to kaleido's own per-call startup otherwise (slow but correct).
    """
    png = fig.to_image(format="png", width=width, height=height, scale=scale)
    b64 = base64.b64encode(png).decode("ascii")
    return f"data:image/png;base64,{b64}"
