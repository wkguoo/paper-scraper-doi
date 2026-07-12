"""Small cross-platform path helpers for the scraper scripts."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path


BROWSER_EXE_ENV = "PAPER_SCRAPER_BROWSER_EXE"


def _path_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def _windows_edge_profile_candidates(base: str | None) -> list[Path]:
    if not base:
        return []
    root = Path(base) / "Microsoft"
    return [
        root / "Edge" / "User Data" / "Default",
        root / "Edge Beta" / "User Data" / "Default",
        root / "Edge Dev" / "User Data" / "Default",
        root / "Edge SxS" / "User Data" / "Default",
    ]


def _windows_chrome_profile_candidates(base: str | None) -> list[Path]:
    if not base:
        return []
    return [Path(base) / "Google" / "Chrome" / "User Data" / "Default"]


def browser_candidate_paths() -> list[str]:
    """Return external browser executable candidates in preference order.

    On Windows, Edge is preferred for external login/debug sessions because
    the Codex in-app browser is not directly shareable with the local Python
    downloader. An explicit environment override remains the first choice.
    """
    candidates: list[Path] = []
    override = os.environ.get(BROWSER_EXE_ENV)
    if override:
        candidates.append(Path(override).expanduser())

    if sys.platform.startswith("win"):
        windows_bases = (
            os.environ.get("PROGRAMFILES"),
            os.environ.get("PROGRAMFILES(X86)"),
            os.environ.get("LOCALAPPDATA"),
        )
        edge_relative_paths = (
            Path("Microsoft") / "Edge" / "Application" / "msedge.exe",
            Path("Microsoft") / "Edge Beta" / "Application" / "msedge.exe",
            Path("Microsoft") / "Edge Dev" / "Application" / "msedge.exe",
            Path("Microsoft") / "Edge SxS" / "Application" / "msedge.exe",
        )
        chrome_relative_paths = (
            Path("Google") / "Chrome" / "Application" / "chrome.exe",
        )

        # Keep all Edge channels ahead of every Chrome candidate, regardless
        # of whether the installation is in Program Files or LocalAppData.
        for relative in edge_relative_paths:
            for base in windows_bases:
                if base:
                    candidates.append(Path(base) / relative)
        for base in windows_bases:
            if base:
                candidates.extend(Path(base) / relative for relative in chrome_relative_paths)

        for name in ("msedge.exe", "msedge", "chrome.exe", "chrome", "chromium.exe", "chromium"):
            found = shutil.which(name)
            if found:
                candidates.append(Path(found))

        # Playwright Chromium is the last Windows fallback, after installed
        # Edge/Chrome executables and PATH-resolved browser binaries.
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            playwright_root = Path(local_appdata) / "ms-playwright"
            candidates.extend(
                sorted(
                    playwright_root.glob("chromium-*/chrome-win64/chrome.exe"),
                    reverse=True,
                )
            )
    elif sys.platform == "darwin":
        candidates.append(Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))
    else:
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            found = shutil.which(name)
            if found:
                candidates.append(Path(found))

    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        value = str(candidate)
        key = os.path.normcase(os.path.abspath(os.path.expanduser(value)))
        if key not in seen:
            unique.append(value)
            seen.add(key)
    return unique


def browser_bin(browser_exe: str | None = None) -> str:
    """Return a likely Edge/Chrome external browser executable path."""
    override = browser_exe or os.environ.get(BROWSER_EXE_ENV)
    if override:
        return str(Path(override).expanduser())

    candidates = browser_candidate_paths()
    for candidate in candidates:
        if _path_exists(Path(candidate)):
            return candidate

    return candidates[0] if candidates else "google-chrome"


def chrome_bin() -> str:
    """Compatibility alias for the Edge-first external browser resolver."""
    return browser_bin()


def browser_default_profile(browser_exe: str | None = None) -> str:
    """Return the default Edge/Chrome profile directory for this operating system."""
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA")
        if base:
            selected_browser = browser_bin(browser_exe)
            exe_name = Path(selected_browser).name.lower()
            exe_path = os.path.normcase(selected_browser)
            edge_profiles = _windows_edge_profile_candidates(base)
            if "edge beta" in exe_path:
                ordered = edge_profiles[1:2] + edge_profiles[0:1] + edge_profiles[2:] + _windows_chrome_profile_candidates(base)
            elif "edge dev" in exe_path:
                ordered = edge_profiles[2:3] + edge_profiles[0:2] + edge_profiles[3:] + _windows_chrome_profile_candidates(base)
            elif "edge sxs" in exe_path:
                ordered = edge_profiles[3:] + edge_profiles[:3] + _windows_chrome_profile_candidates(base)
            elif "chrome" in exe_name and "msedge" not in exe_name:
                ordered = _windows_chrome_profile_candidates(base) + _windows_edge_profile_candidates(base)
            else:
                ordered = edge_profiles + _windows_chrome_profile_candidates(base)
            candidates = tuple(ordered)
            for candidate in candidates:
                if _path_exists(candidate):
                    return str(candidate)
            return str(candidates[0])
    if sys.platform == "darwin":
        return str(Path.home() / "Library" / "Application Support" / "Google" / "Chrome" / "Default")
    return str(Path.home() / ".config" / "google-chrome" / "Default")


def chrome_default_profile() -> str:
    """Return the default Chrome profile directory for this operating system."""
    return browser_default_profile()


def browser_display_name(browser_exe: str | None = None) -> str:
    """Return a short display name for the selected browser executable."""
    exe = Path(browser_bin(browser_exe)).name.lower()
    if "msedge" in exe:
        return "Edge"
    if "chrome" in exe:
        return "Chrome/Chromium"
    return "browser"


def chrome_debug_profile(name: str) -> str:
    """Return a writable temp profile path for debug Chrome."""
    return str(Path(tempfile.gettempdir()) / name)


def chrome_debug_log(name: str) -> str:
    """Return a writable temp log path for debug Chrome."""
    return str(Path(tempfile.gettempdir()) / name)
