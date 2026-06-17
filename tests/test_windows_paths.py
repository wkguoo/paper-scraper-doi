from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class WindowsPathTests(unittest.TestCase):
    def test_chrome_bin_falls_back_to_edge_on_windows(self) -> None:
        import windows_paths

        edge = Path(r"C:\PF86") / "Microsoft" / "Edge" / "Application" / "msedge.exe"

        def exists(path: Path) -> bool:
            return path == edge

        env = {
            "PROGRAMFILES": r"C:\PF",
            "PROGRAMFILES(X86)": r"C:\PF86",
            "LOCALAPPDATA": r"C:\Users\Me\AppData\Local",
        }
        with patch.dict(os.environ, env, clear=False), \
                patch.object(windows_paths.sys, "platform", "win32"), \
                patch.object(Path, "exists", exists), \
                patch.object(windows_paths.shutil, "which", return_value=None):
            self.assertEqual(windows_paths.chrome_bin(), str(edge))

    def test_chrome_default_profile_falls_back_to_edge_profile(self) -> None:
        import windows_paths

        edge_default = Path(r"C:\Users\Me\AppData\Local") / "Microsoft" / "Edge" / "User Data" / "Default"

        def exists(path: Path) -> bool:
            return path == edge_default

        env = {"LOCALAPPDATA": r"C:\Users\Me\AppData\Local"}
        with patch.dict(os.environ, env, clear=False), \
                patch.object(windows_paths.sys, "platform", "win32"), \
                patch.object(Path, "exists", exists):
            self.assertEqual(windows_paths.chrome_default_profile(), str(edge_default))


if __name__ == "__main__":
    unittest.main()
