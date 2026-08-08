"""SFTP connection wrapper (mocked; no live network)."""
from unittest.mock import MagicMock

from app.ingest import connections


def test_open_sftp_sets_keepalive(monkeypatch):
    """Long /v3 walks were dropping on idle; open_sftp must set a keepalive."""
    transport = MagicMock()
    monkeypatch.setattr(connections.socket, "create_connection",
                        lambda *a, **k: MagicMock())
    monkeypatch.setattr(connections.paramiko, "Transport", lambda sock: transport)
    monkeypatch.setattr(connections.paramiko.SFTPClient, "from_transport",
                        lambda t: MagicMock())
    with connections.open_sftp({"host": "h", "port": 22, "user": "u", "password": "p"}):
        pass
    transport.set_keepalive.assert_called_once_with(30)
