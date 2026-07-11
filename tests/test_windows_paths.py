from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class WindowsPathTests(unittest.TestCase):
    def test_chrome_bin_uses_browser_env_override(self) -> None:
        import windows_paths

        override = r"D:\PortableChrome\chrome.exe"
        with patch.dict(os.environ, {windows_paths.BROWSER_EXE_ENV: override}, clear=True), \
                patch.object(windows_paths.sys, "platform", "win32"):
            self.assertEqual(windows_paths.chrome_bin(), override)

    def test_chrome_bin_does_not_auto_select_edge_on_windows(self) -> None:
        import windows_paths

        edge = Path(r"C:\PF86") / "Microsoft" / "Edge" / "Application" / "msedge.exe"
        expected = Path(r"C:\PF") / "Google" / "Chrome" / "Application" / "chrome.exe"

        def exists(path: Path) -> bool:
            return path == edge

        env = {
            "PROGRAMFILES": r"C:\PF",
            "PROGRAMFILES(X86)": r"C:\PF86",
            "LOCALAPPDATA": r"C:\Users\Me\AppData\Local",
        }
        with patch.dict(os.environ, env, clear=True), \
                patch.object(windows_paths.sys, "platform", "win32"), \
                patch.object(Path, "exists", exists), \
                patch.object(windows_paths.shutil, "which", return_value=None):
            self.assertEqual(windows_paths.chrome_bin(), str(expected))

    def test_chrome_bin_prefers_chrome_over_edge_on_windows(self) -> None:
        import windows_paths

        edge = Path(r"C:\PF86") / "Microsoft" / "Edge" / "Application" / "msedge.exe"
        chrome = Path(r"C:\PF") / "Google" / "Chrome" / "Application" / "chrome.exe"

        def exists(path: Path) -> bool:
            return path in {edge, chrome}

        env = {
            "PROGRAMFILES": r"C:\PF",
            "PROGRAMFILES(X86)": r"C:\PF86",
            "LOCALAPPDATA": r"C:\Users\Me\AppData\Local",
        }
        with patch.dict(os.environ, env, clear=True), \
                patch.object(windows_paths.sys, "platform", "win32"), \
                patch.object(Path, "exists", exists), \
                patch.object(windows_paths.shutil, "which", return_value=None):
            self.assertEqual(windows_paths.chrome_bin(), str(chrome))

    def test_chrome_bin_does_not_auto_select_edge_beta_on_windows(self) -> None:
        import windows_paths

        edge_beta = Path(r"C:\PF86") / "Microsoft" / "Edge Beta" / "Application" / "msedge.exe"
        expected = Path(r"C:\PF") / "Google" / "Chrome" / "Application" / "chrome.exe"

        def exists(path: Path) -> bool:
            return path == edge_beta

        env = {
            "PROGRAMFILES": r"C:\PF",
            "PROGRAMFILES(X86)": r"C:\PF86",
            "LOCALAPPDATA": r"C:\Users\Me\AppData\Local",
        }
        with patch.dict(os.environ, env, clear=True), \
                patch.object(windows_paths.sys, "platform", "win32"), \
                patch.object(Path, "exists", exists), \
                patch.object(windows_paths.shutil, "which", return_value=None):
            self.assertEqual(windows_paths.chrome_bin(), str(expected))

    def test_chrome_bin_does_not_auto_select_any_edge_channel(self) -> None:
        import windows_paths

        edge_stable_x86 = Path(r"C:\PF86") / "Microsoft" / "Edge" / "Application" / "msedge.exe"
        edge_beta_pf = Path(r"C:\PF") / "Microsoft" / "Edge Beta" / "Application" / "msedge.exe"
        expected = Path(r"C:\PF") / "Google" / "Chrome" / "Application" / "chrome.exe"

        def exists(path: Path) -> bool:
            return path in {edge_stable_x86, edge_beta_pf}

        env = {
            "PROGRAMFILES": r"C:\PF",
            "PROGRAMFILES(X86)": r"C:\PF86",
            "LOCALAPPDATA": r"C:\Users\Me\AppData\Local",
        }
        with patch.dict(os.environ, env, clear=True), \
                patch.object(windows_paths.sys, "platform", "win32"), \
                patch.object(Path, "exists", exists), \
                patch.object(windows_paths.shutil, "which", return_value=None):
            self.assertEqual(windows_paths.chrome_bin(), str(expected))

    def test_chrome_bin_falls_back_to_playwright_chromium_on_windows(self) -> None:
        import windows_paths

        with tempfile.TemporaryDirectory() as tmpdir:
            chromium = (
                Path(tmpdir)
                / "ms-playwright"
                / "chromium-1224"
                / "chrome-win64"
                / "chrome.exe"
            )
            chromium.parent.mkdir(parents=True)
            chromium.touch()

            env = {"LOCALAPPDATA": tmpdir}
            with patch.dict(os.environ, env, clear=True), \
                    patch.object(windows_paths.sys, "platform", "win32"), \
                    patch.object(windows_paths.shutil, "which", return_value=None):
                self.assertEqual(windows_paths.chrome_bin(), str(chromium))

    def test_chrome_default_profile_prefers_chrome_profile_without_explicit_edge(self) -> None:
        import windows_paths

        edge_default = Path(r"C:\Users\Me\AppData\Local") / "Microsoft" / "Edge" / "User Data" / "Default"
        chrome_default = Path(r"C:\Users\Me\AppData\Local") / "Google" / "Chrome" / "User Data" / "Default"

        def exists(path: Path) -> bool:
            return path in {edge_default, chrome_default}

        env = {"LOCALAPPDATA": r"C:\Users\Me\AppData\Local"}
        with patch.dict(os.environ, env, clear=True), \
                patch.object(windows_paths.sys, "platform", "win32"), \
                patch.object(Path, "exists", exists):
            self.assertEqual(windows_paths.chrome_default_profile(), str(chrome_default))

    def test_browser_default_profile_follows_explicit_chrome_browser(self) -> None:
        import windows_paths

        chrome_exe = Path(r"C:\PF") / "Google" / "Chrome" / "Application" / "chrome.exe"
        edge_default = Path(r"C:\Users\Me\AppData\Local") / "Microsoft" / "Edge" / "User Data" / "Default"
        chrome_default = Path(r"C:\Users\Me\AppData\Local") / "Google" / "Chrome" / "User Data" / "Default"

        def exists(path: Path) -> bool:
            return path in {edge_default, chrome_default}

        env = {"LOCALAPPDATA": r"C:\Users\Me\AppData\Local"}
        with patch.dict(os.environ, env, clear=True), \
                patch.object(windows_paths.sys, "platform", "win32"), \
                patch.object(Path, "exists", exists):
            self.assertEqual(windows_paths.browser_default_profile(str(chrome_exe)), str(chrome_default))

    def test_browser_default_profile_follows_explicit_edge_beta_browser(self) -> None:
        import windows_paths

        edge_beta_exe = Path(r"C:\PF86") / "Microsoft" / "Edge Beta" / "Application" / "msedge.exe"
        edge_default = Path(r"C:\Users\Me\AppData\Local") / "Microsoft" / "Edge" / "User Data" / "Default"
        edge_beta_default = Path(r"C:\Users\Me\AppData\Local") / "Microsoft" / "Edge Beta" / "User Data" / "Default"

        def exists(path: Path) -> bool:
            return path in {edge_default, edge_beta_default}

        env = {"LOCALAPPDATA": r"C:\Users\Me\AppData\Local"}
        with patch.dict(os.environ, env, clear=True), \
                patch.object(windows_paths.sys, "platform", "win32"), \
                patch.object(Path, "exists", exists):
            self.assertEqual(windows_paths.browser_default_profile(str(edge_beta_exe)), str(edge_beta_default))


if __name__ == "__main__":
    unittest.main()
