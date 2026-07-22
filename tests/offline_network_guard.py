from __future__ import annotations

import ipaddress
import os
import socket
from typing import Any


_INSTALLED = False
_ORIGINAL_CONNECT = socket.socket.connect
_ORIGINAL_CONNECT_EX = socket.socket.connect_ex
_ORIGINAL_CREATE_CONNECTION = socket.create_connection


def _is_loopback_address(address: Any) -> bool:
    if isinstance(address, str):
        # AF_UNIX paths and Windows named local endpoints are local.
        return True
    if not isinstance(address, tuple) or not address:
        return True
    host = str(address[0] or "").strip().strip("[]").casefold()
    if host in {"localhost", "localhost.localdomain"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _deny(address: Any) -> None:
    if not _is_loopback_address(address):
        raise RuntimeError(f"unmocked_public_network_blocked:{address!r}")


def install() -> None:
    global _INSTALLED
    if _INSTALLED or os.environ.get("PAPER_SCRAPER_TEST_ALLOW_NETWORK") == "1":
        return

    def guarded_connect(sock, address):
        _deny(address)
        return _ORIGINAL_CONNECT(sock, address)

    def guarded_connect_ex(sock, address):
        _deny(address)
        return _ORIGINAL_CONNECT_EX(sock, address)

    def guarded_create_connection(address, *args, **kwargs):
        _deny(address)
        return _ORIGINAL_CREATE_CONNECTION(address, *args, **kwargs)

    socket.socket.connect = guarded_connect
    socket.socket.connect_ex = guarded_connect_ex
    socket.create_connection = guarded_create_connection
    _INSTALLED = True
