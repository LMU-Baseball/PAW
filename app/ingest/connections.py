"""Context managers for opening Trackman SFTP / HitTrax FTPS connections.

No live-network tests here on purpose (per task brief) — these are thin
wrappers around paramiko / ftplib whose correctness is exercised by the
loader tasks that use them against the real servers.
"""
from __future__ import annotations

import ftplib
import socket
from contextlib import contextmanager

import paramiko

TIMEOUT_SECONDS = 30


@contextmanager
def open_sftp(cfg: dict):
    """Yield a paramiko SFTPClient connected per `cfg` (host/port/user/password)."""
    sock = socket.create_connection((cfg["host"], cfg["port"]), timeout=TIMEOUT_SECONDS)
    transport = paramiko.Transport(sock)
    try:
        transport.connect(username=cfg["user"], password=cfg["password"])
        transport.set_keepalive(30)  # keep long /v3 walks alive (idle drops otherwise)
        sftp = paramiko.SFTPClient.from_transport(transport)
        try:
            yield sftp
        finally:
            sftp.close()
    finally:
        transport.close()


@contextmanager
def open_ftps(cfg: dict):
    """Yield an ftplib FTP_TLS client connected/logged in/secured per `cfg`."""
    ftps = ftplib.FTP_TLS(timeout=TIMEOUT_SECONDS)
    try:
        ftps.connect(cfg["host"], cfg["port"])
        ftps.login(cfg["user"], cfg["password"])
        ftps.prot_p()
        yield ftps
    finally:
        ftps.close()
