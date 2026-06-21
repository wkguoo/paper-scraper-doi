"""Small cross-platform path helpers for the scraper scripts."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path


BROWSER_EXE_ENV = "PAPER_SCRAPER_BROWSER_EXE"


def browser_candidate_paths() -> list[str]:
    """Return browser executable candidates in preference order."""
    candidates: list[Path] = []
    override = os.environ.get(BROWSER_EXE_ENV)
    if override:
        candidates.append(Path(override).expanduser())

    if sys.platform.startswith("win"):
        for base in (
            os.environ.get("PROGRAMFILES"),
            os.environ.get("PROGRAMFILES(X86)"),
            os.environ.get("LOCALAPPDATA"),
        ):
            if base:
                candidates.append(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe")
        for base in (
            os.environ.get("PROGRAMFILES"),
            os.environ.get("PROGRAMFILES(X86)"),
            os.environ.get("LOCALAPPDATA"),
        ):
            if base:
                candidates.append(Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe")
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            playwright_root = Path(local_appdata) / "ms-playwright"
            candidates.extend(
                sorted(
                    playwright_root.glob("chromium-*/chrome-win64/chrome.exe"),
                    reverse=True,
                )
            )
        for name in ("chrome.exe", "chrome", "msedge.exe", "msedge"):
            found = shutil.which(name)
            if found:
                candidates.append(Path(found))
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


def chrome_bin() -> str:
    """Return a likely Chrome/Edge/Chromium executable path."""
    override = os.environ.get(BROWSER_EXE_ENV)
    if override:
        return str(Path(override).expanduser())

    candidates = browser_candidate_paths()
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate

    return candidates[0] if candidates else "google-chrome"


def chrome_default_profile() -> str:
    """Return the default Chrome profile directory for this operating system."""
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA")
        if base:
            candidates = (
                Path(base) / "Google" / "Chrome" / "User Data" / "Default",
                Path(base) / "Microsoft" / "Edge" / "User Data" / "Default",
            )
            for candidate in candidates:
                if candidate.exists():
                    return str(candidate)
            return str(candidates[0])
    if sys.platform == "darwin":
        return str(Path.home() / "Library" / "Application Support" / "Google" / "Chrome" / "Default")
    return str(Path.home() / ".config" / "google-chrome" / "Default")


def chrome_debug_profile(name: str) -> str:
    """Return a writable temp profile path for debug Chrome."""
    return str(Path(tempfile.gettempdir()) / name)


def chrome_debug_log(name: str) -> str:
    """Return a writable temp log path for debug Chrome."""
    return str(Path(tempfile.gettempdir()) / name)
