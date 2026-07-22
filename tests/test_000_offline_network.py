from __future__ import annotations

import os
import socket
import sys
import unittest
from pathlib import Path

from offline_network_guard import install


install()
_tests_dir = str(Path(__file__).resolve().parent)
_existing_pythonpath = os.environ.get("PYTHONPATH", "")
if _tests_dir not in _existing_pythonpath.split(os.pathsep):
    os.environ["PYTHONPATH"] = os.pathsep.join(
        part for part in (_tests_dir, _existing_pythonpath) if part
    )


class OfflineNetworkGuardTests(unittest.TestCase):
    def test_public_socket_is_blocked(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "unmocked_public_network_blocked"):
            socket.create_connection(("example.com", 443), timeout=0.01)

    def test_loopback_is_allowed_to_reach_the_os(self) -> None:
        sock = socket.socket()
        sock.settimeout(0.01)
        try:
            # No service is required; the guard must not raise its own error.
            try:
                sock.connect(("127.0.0.1", 9))
            except (ConnectionRefusedError, TimeoutError, OSError):
                pass
        finally:
            sock.close()


if __name__ == "__main__":
    unittest.main()
