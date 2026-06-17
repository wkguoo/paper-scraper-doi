"""Small cross-platform path helpers for the scraper scripts."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path


def chrome_bin() -> str:
    """Return a likely Chrome executable path for Windows/macOS/Linux."""
    candidates: list[Path] = []

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
    elif sys.platform == "darwin":
        candidates.append(Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))
    else:
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            found = shutil.which(name)
            if found:
                return found

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    fallback = shutil.which("chrome") or shutil.which("google-chrome")
    if fallback:
        return fallback

    return str(candidates[0]) if candidates else "google-chrome"


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
