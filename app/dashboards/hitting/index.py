"""The Dash HTML shell for hitting — now delegates to the shared shell.
Kept as a thin module so app.dashboards.hitting.index.INDEX_STRING still resolves.
"""
from app.dashboards.shell import index_string

INDEX_STRING = index_string()
