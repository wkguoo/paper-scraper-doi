from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

from sd_scraper import (
    BROWSER_DEBUG_EXTRA_ARGS,
    BROWSER_PROFILE_COPY_DIRS,
    BROWSER_PROFILE_COPY_FILES,
    _BROWSER_COMPAT_JS,
    _dt_capture_pdf,
)
from windows_paths import browser_bin, browser_default_profile, browser_display_name

from .models import PageSnapshot, PdfCaptureResult


class DebugBrowserSession:
    INSTANCE_SCHEMA_VERSION = 1

    def __init__(self, browser_exe: str | None = None, debug_port: int = 0) -> None:
        self.browser_exe = browser_bin(browser_exe)
        self.browser_name = browser_display_name(browser_exe)
        self.requested_debug_port = int(debug_port)
        self.debug_port = int(debug_port)
        local_root = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir())
        self.instance_root = local_root / "PaperScraperDOI" / "browser-session" / "v1"
        self.debug_profile = str(self.instance_root / "profile")
        self.log_path = str(self.instance_root / "browser.log")
        self.instance_path = self.instance_root / "instance.json"
        self.instance_lock_path = self.instance_root / "instance.lock"

    def ensure_ready(self) -> bool:
        """Ensure debug browser is reachable.

        Returns True if a new browser process was launched, False if an existing
        session on this debug port was reused (optimization #6).
        """

        with self._instance_lock():
            descriptor = self._read_instance_descriptor()
            if descriptor is not None:
                state = self._validate_instance_descriptor(descriptor)
                if state == "valid":
                    self.debug_port = int(descriptor["port"])
                    print(
                        f"[浏览器] 复用受控调试会话 port={self.debug_port} "
                        f"({self.browser_name})"
                    )
                    return False
                if state == "stale":
                    self.instance_path.unlink(missing_ok=True)

            if self.requested_debug_port > 0 and self._version_payload(self.requested_debug_port):
                raise RuntimeError("browser_instance_mismatch")

            process = self._launch()
            descriptor = self._wait_for_launched_instance(process)
            self._write_instance_descriptor(descriptor)
            self.debug_port = int(descriptor["port"])
            return True

    def is_ready(self) -> bool:
        descriptor = self._read_instance_descriptor()
        if descriptor is None:
            return False
        state = self._validate_instance_descriptor(descriptor)
        if state == "valid":
            self.debug_port = int(descriptor["port"])
            return True
        return False

    @contextmanager
    def _instance_lock(self, timeout: float = 10.0):
        self.instance_root.mkdir(parents=True, exist_ok=True)
        handle = self.instance_lock_path.open("a+b")
        acquired = False
        deadline = time.monotonic() + timeout
        try:
            while not acquired:
                try:
                    if os.name == "nt":
                        import msvcrt

                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except (BlockingIOError, OSError) as exc:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("browser_instance_lock_timeout") from exc
                    time.sleep(0.05)
            yield
        finally:
            if acquired:
                try:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
            handle.close()

    def _read_instance_descriptor(self) -> dict[str, object] | None:
        if not self.instance_path.is_file():
            return None
        try:
            payload = json.loads(self.instance_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("browser_instance_state_invalid") from exc
        if not isinstance(payload, dict):
            raise ValueError("browser_instance_state_invalid")
        return payload

    def _validate_instance_descriptor(self, payload: dict[str, object]) -> str:
        required = {
            "schema_version", "pid", "executable", "profile", "port",
            "instance_token", "started_at",
        }
        if set(payload) != required or payload.get("schema_version") != self.INSTANCE_SCHEMA_VERSION:
            raise ValueError("browser_instance_state_invalid")
        try:
            pid = int(payload["pid"])
            port = int(payload["port"])
        except (TypeError, ValueError) as exc:
            raise ValueError("browser_instance_state_invalid") from exc
        if pid <= 0 or not 1 <= port <= 65535:
            raise ValueError("browser_instance_state_invalid")
        if not self._pid_alive(pid):
            return "stale"
        expected_exe = self._normalize_path(self.browser_exe)
        actual_exe = self._process_executable(pid)
        if not actual_exe:
            raise RuntimeError("browser_instance_mismatch")
        if self._normalize_path(str(payload["executable"])) != expected_exe:
            raise RuntimeError("browser_instance_mismatch")
        if self._normalize_path(actual_exe) != expected_exe:
            raise RuntimeError("browser_instance_mismatch")
        if self._normalize_path(str(payload["profile"])) != self._normalize_path(self.debug_profile):
            raise RuntimeError("browser_instance_mismatch")
        if self.requested_debug_port > 0 and port != self.requested_debug_port:
            raise RuntimeError("browser_instance_mismatch")

        active = self._read_devtools_active_port()
        if active is None:
            # A live recorded PID without its profile identity marker is not
            # safe to replace or share.
            raise RuntimeError("browser_instance_mismatch")
        active_port, active_token = active
        if active_port != port or active_token != str(payload["instance_token"]):
            raise RuntimeError("browser_instance_mismatch")
        version = self._version_payload(port)
        if not version:
            raise RuntimeError("browser_instance_mismatch")
        if self._browser_token(version) != str(payload["instance_token"]):
            raise RuntimeError("browser_instance_mismatch")
        return "valid"

    def _wait_for_launched_instance(self, process) -> dict[str, object]:
        deadline = time.time() + 40
        while time.time() < deadline:
            active = self._read_devtools_active_port()
            if active is not None:
                port, token = active
                if self.requested_debug_port > 0 and port != self.requested_debug_port:
                    raise RuntimeError("browser_instance_mismatch")
                version = self._version_payload(port)
                if version and self._browser_token(version) == token:
                    actual_exe = self._process_executable(int(process.pid))
                    if not actual_exe or self._normalize_path(actual_exe) != self._normalize_path(self.browser_exe):
                        raise RuntimeError("browser_instance_mismatch")
                    return {
                        "schema_version": self.INSTANCE_SCHEMA_VERSION,
                        "pid": int(process.pid),
                        "executable": self._normalize_path(actual_exe),
                        "profile": self._normalize_path(self.debug_profile),
                        "port": port,
                        "instance_token": token,
                        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    }
            if getattr(process, "poll", lambda: None)() is not None:
                break
            time.sleep(0.2)
        raise RuntimeError(f"browser_debug_port_unavailable:{self.log_path}")

    def _read_devtools_active_port(self) -> tuple[int, str] | None:
        path = Path(self.debug_profile) / "DevToolsActivePort"
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            port = int(lines[0].strip())
            token = lines[1].strip().rstrip("/").rsplit("/", 1)[-1]
        except (OSError, UnicodeError, ValueError, IndexError):
            return None
        return (port, token) if 1 <= port <= 65535 and token else None

    def _version_payload(self, port: int) -> dict[str, object] | None:
        try:
            with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) and payload.get("webSocketDebuggerUrl") else None

    @staticmethod
    def _browser_token(payload: dict[str, object]) -> str:
        value = str(payload.get("webSocketDebuggerUrl", "") or "")
        return value.rstrip("/").rsplit("/", 1)[-1] if value else ""

    @staticmethod
    def _normalize_path(value: str) -> str:
        return os.path.normcase(os.path.abspath(os.path.expanduser(value)))

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    @staticmethod
    def _process_executable(pid: int) -> str:
        if os.name == "nt":
            try:
                import ctypes
                from ctypes import wintypes

                process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
                if not process:
                    return ""
                try:
                    size = wintypes.DWORD(32768)
                    buffer = ctypes.create_unicode_buffer(size.value)
                    if not ctypes.windll.kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
                        return ""
                    return buffer.value
                finally:
                    ctypes.windll.kernel32.CloseHandle(process)
            except (AttributeError, OSError, ValueError):
                return ""
        try:
            return str(Path(f"/proc/{pid}/exe").resolve(strict=True))
        except OSError:
            return ""

    def _write_instance_descriptor(self, payload: dict[str, object]) -> None:
        self.instance_root.mkdir(parents=True, exist_ok=True)
        temporary = self.instance_root / f".instance-{uuid.uuid4().hex}.tmp"
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.instance_path)
        finally:
            temporary.unlink(missing_ok=True)

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
        target_path: str | Path | None = None,
    ) -> PdfCaptureResult:
        tab = self._open_tab("about:blank")
        try:
            captured, note = _dt_capture_pdf(
                tab["webSocketDebuggerUrl"],
                url,
                timeout=timeout,
                fetch_patterns=self._fetch_pattern_dicts(fetch_patterns),
                output_path=target_path,
            )
        finally:
            self._close_tab(tab["id"])
        return PdfCaptureResult(
            requested_url=url,
            pdf_url=note if captured else "",
            pdf_bytes=captured if isinstance(captured, bytes) else b"",
            pdf_file=str(captured) if isinstance(captured, Path) else "",
            note="" if captured else note,
        )

    def _launch(self):
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
            f"--remote-debugging-port={self.requested_debug_port}",
            "--remote-allow-origins=http://127.0.0.1:*",
            f"--user-data-dir={self.debug_profile}",
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
            *BROWSER_DEBUG_EXTRA_ARGS,
        ]
        with Path(self.log_path).open("w", encoding="utf-8") as log_file:
            return subprocess.Popen(command, stdout=log_file, stderr=subprocess.STDOUT)

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
