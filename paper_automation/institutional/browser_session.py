from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

from sd_scraper import BROWSER_PROFILE_COPY_DIRS, BROWSER_PROFILE_COPY_FILES, _BROWSER_COMPAT_JS, _dt_capture_pdf
from windows_paths import browser_bin, browser_default_profile, browser_display_name, chrome_debug_log, chrome_debug_profile

from .models import PageSnapshot, PdfCaptureResult


class DebugBrowserSession:
    def __init__(self, browser_exe: str | None = None, debug_port: int = 9333) -> None:
        self.browser_exe = browser_bin(browser_exe)
        self.browser_name = browser_display_name(browser_exe)
        self.debug_port = debug_port
        self.debug_profile = chrome_debug_profile(f"institutional_dbg_profile_{debug_port}")
        self.log_path = chrome_debug_log(f"institutional_debug_{debug_port}.log")

    def ensure_ready(self) -> bool:
        if self.is_ready():
            return False
        self._launch()
        deadline = time.time() + 40
        while time.time() < deadline:
            if self.is_ready():
                return True
            time.sleep(1)
        raise RuntimeError(f"browser_debug_port_unavailable:{self.log_path}")

    def is_ready(self) -> bool:
        try:
            urlopen(f"http://127.0.0.1:{self.debug_port}/json/version", timeout=2)
        except OSError:
            return False
        return True

    def open_login_page(self, url: str) -> None:
        self._open_tab(url)

    def load_page(self, url: str, wait_seconds: float = 3.0) -> PageSnapshot:
        tab = self._open_tab("about:blank")
        ws = self._open_websocket(tab["webSocketDebuggerUrl"], timeout=30)
        try:
            self._send(ws, 1, "Page.enable")
            self._send(ws, 2, "Page.addScriptToEvaluateOnNewDocument", {"source": _BROWSER_COMPAT_JS})
            self._send(ws, 3, "Page.navigate", {"url": url})
            deadline = time.time() + wait_seconds + 10
            while time.time() < deadline:
                try:
                    message = self._receive_json(ws, timeout=2)
                except Exception:
                    continue
                if message.get("method") == "Page.loadEventFired":
                    break
            time.sleep(wait_seconds)
            final_url = self._evaluate(ws, "location.href") or url
            html = self._evaluate(ws, "document.documentElement ? document.documentElement.outerHTML : ''")
            text = self._evaluate(ws, "document.body ? document.body.innerText : ''")
            return PageSnapshot(url, final_url, html=html, text=text)
        finally:
            try:
                ws.close()
            finally:
                self._close_tab(tab["id"])

    def capture_pdf(
        self,
        url: str,
        fetch_patterns: tuple[str, ...],
        timeout: int = 45,
    ) -> PdfCaptureResult:
        tab = self._open_tab("about:blank")
        try:
            pdf_bytes, note = _dt_capture_pdf(
                tab["webSocketDebuggerUrl"],
                url,
                timeout=timeout,
                fetch_patterns=self._fetch_pattern_dicts(fetch_patterns),
            )
        finally:
            self._close_tab(tab["id"])
        return PdfCaptureResult(
            requested_url=url,
            pdf_url=note if pdf_bytes else "",
            pdf_bytes=pdf_bytes or b"",
            note="" if pdf_bytes else note,
        )

    def _launch(self) -> None:
        default_profile = browser_default_profile(self.browser_exe)
        target_default = Path(self.debug_profile) / "Default"
        target_default.mkdir(parents=True, exist_ok=True)
        for filename in BROWSER_PROFILE_COPY_FILES:
            source = Path(default_profile) / filename
            target = target_default / filename
            if source.exists():
                try:
                    shutil.copy2(source, target)
                except OSError:
                    continue
        for dirname in BROWSER_PROFILE_COPY_DIRS:
            source_dir = Path(default_profile) / dirname
            target_dir = target_default / dirname
            if source_dir.exists():
                try:
                    shutil.copytree(source_dir, target_dir, dirs_exist_ok=True)
                except OSError:
                    continue
        for lock_name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            lock_path = Path(self.debug_profile) / lock_name
            try:
                if lock_path.exists():
                    lock_path.unlink()
            except OSError:
                continue
        command = [
            self.browser_exe,
            f"--remote-debugging-port={self.debug_port}",
            f"--remote-allow-origins=http://127.0.0.1:{self.debug_port}",
            f"--user-data-dir={self.debug_profile}",
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        with Path(self.log_path).open("w", encoding="utf-8") as log_file:
            subprocess.Popen(command, stdout=log_file, stderr=subprocess.STDOUT)

    def _open_tab(self, url: str) -> dict[str, str]:
        request = Request(
            f"http://127.0.0.1:{self.debug_port}/json/new?{quote(url, safe=':/?&=%')}",
            method="PUT",
        )
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def _close_tab(self, page_id: str) -> None:
        request = Request(f"http://127.0.0.1:{self.debug_port}/json/close/{page_id}")
        with urlopen(request, timeout=10):
            return

    def _open_websocket(self, ws_url: str, timeout: int):
        try:
            import websocket
        except ImportError as exc:
            raise RuntimeError("websocket-client 未安装") from exc
        return websocket.create_connection(ws_url, timeout=timeout, suppress_origin=True)

    def _send(self, ws, message_id: int, method: str, params: dict[str, object] | None = None) -> None:
        ws.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))

    def _receive_json(self, ws, timeout: int) -> dict[str, object]:
        ws.settimeout(timeout)
        raw = ws.recv()
        return json.loads(raw)

    def _evaluate(self, ws, expression: str) -> str:
        self._send(
            ws,
            100,
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True},
        )
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                message = self._receive_json(ws, timeout=2)
            except Exception:
                continue
            if message.get("id") == 100:
                result = message.get("result", {})
                nested = result.get("result", {})
                return str(nested.get("value") or "")
        return ""

    def _fetch_pattern_dicts(self, patterns: tuple[str, ...]) -> list[dict[str, str]]:
        unique = []
        seen: set[str] = set()
        for pattern in patterns or ("*pdf*",):
            if pattern not in seen:
                unique.append({"urlPattern": pattern, "requestStage": "Response"})
                seen.add(pattern)
        return unique
