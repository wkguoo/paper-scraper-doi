from __future__ import annotations

import json
import io
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from paper_automation.batch_stages import BatchOptions


def _row(task_id: str, status: str, *, reason: str = "", doi: str = "10.1000/test") -> dict:
    return {
        "task_id": task_id,
        "source_index": "1",
        "input_doi": doi,
        "input_title": "Test",
        "doi": doi,
        "title": "Test",
        "authors": "Author",
        "journal": "Journal",
        "year": "2026",
        "publisher": "Publisher",
        "status": status,
        "source": "test",
        "file": "",
        "reason": reason,
    }


class Phase3CliPolicyTests(unittest.TestCase):
    def test_zotero_flags_are_mutually_exclusive_and_default_to_nonblocking_auto(self) -> None:
        from paper_batch import build_parser

        parser = build_parser()
        for command in ("start", "retry-failed", "recover-oa"):
            with self.subTest(command=command):
                argv = [command]
                if command == "start":
                    argv += ["--text", "10.1000/test"]
                else:
                    argv += ["--run-dir", "run"]
                args = parser.parse_args(argv)
                self.assertTrue(args.auto_zotero)
                self.assertEqual(args.wait_seconds, 0)
        args = parser.parse_args(["zotero", "--run-dir", "run"])
        self.assertEqual(args.wait_seconds, 0)
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parser.parse_args([
                    "start", "--text", "10.1000/test", "--auto-zotero", "--no-auto-zotero",
                ])

    def test_recover_exit_codes_cover_complete_waiting_unresolved_and_transient(self) -> None:
        from paper_automation.batch_app import recover_oa_exit_code

        success = SimpleNamespace(status="oa_downloaded", attempts=[])
        missing = SimpleNamespace(status="no_oa_pdf", attempts=[])
        timeout = SimpleNamespace(status="recovery_timeout", attempts=[])
        connection = SimpleNamespace(
            status="no_oa_pdf",
            attempts=[SimpleNamespace(result="publisher_unreachable")],
        )
        self.assertEqual(recover_oa_exit_code([]), 0)
        self.assertEqual(recover_oa_exit_code([success]), 0)
        self.assertEqual(recover_oa_exit_code([missing]), 4)
        self.assertEqual(recover_oa_exit_code([timeout]), 5)
        self.assertEqual(recover_oa_exit_code([connection]), 5)
        self.assertEqual(recover_oa_exit_code([missing], bridge_exit_code=3), 3)
        self.assertEqual(recover_oa_exit_code([missing], bridge_exit_code=2), 2)
        self.assertEqual(recover_oa_exit_code([missing], batch_complete=True), 0)

    def test_command_request_is_shared_and_never_adds_wait_to_status(self) -> None:
        from paper_automation.batch_app import BatchCommandRequest

        status = BatchCommandRequest(action="status", run_dir="C:/run").to_argv()
        self.assertEqual(status, ["status", "--run-dir", "C:/run"])
        start = BatchCommandRequest(action="start", input_text="doi").to_argv()
        self.assertIn("--auto-zotero", start)
        self.assertEqual(start[start.index("--wait-seconds") + 1], "0")

    def test_recover_cli_returns_four_or_five_when_auto_queue_is_disabled(self) -> None:
        from paper_batch import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = SimpleNamespace(
                root=root,
                pdfs=root / "pdfs",
                reports=root / "reports",
                zotero_fallback=root / "working" / "zotero_fallback.csv",
            )
            batch_result = SimpleNamespace(
                paths=paths,
                total_count=1,
                success_count=0,
                failed_count=1,
                manual_retry_count=0,
                zotero_fallback_count=1,
            )
            for status, expected in (("no_oa_pdf", 4), ("recovery_timeout", 5)):
                with self.subTest(status=status), patch(
                    "paper_automation.oa_recovery.run_limited_oa_recovery_on_batch",
                    return_value=[SimpleNamespace(
                        doi="10.1000/test", status=status, file="", reason=status,
                        elapsed_s=0.1, attempts=[],
                    )],
                ), patch("paper_batch.paths_from_run_dir", return_value=paths), patch(
                    "paper_batch.load_batch_state", return_value={}
                ), patch("paper_batch.result_from_state", return_value=batch_result), redirect_stdout(io.StringIO()):
                    code = main(["recover-oa", "--run-dir", str(root), "--no-auto-zotero"])
                self.assertEqual(code, expected)


class Phase3StatusTests(unittest.TestCase):
    def _save(self, root: Path, rows: list[dict], attempts: dict | None = None):
        from paper_automation.batch_workflow import create_batch_paths, save_batch_state

        paths = create_batch_paths(root)
        state = {
            "version": 1,
            "run_dir": str(paths.root),
            "manual_retry_used": True,
            "options": asdict(BatchOptions(auto_oa_recovery=False)),
            "active_attempts": attempts or {},
            "rows": rows,
        }
        save_batch_state(paths, state)
        return paths

    def test_status_is_read_only_and_json_contains_only_summary(self) -> None:
        from paper_automation.batch_app import inspect_batch_status

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._save(
                Path(tmp),
                [
                    _row("paper-0001", "oa_downloaded"),
                    _row("paper-0002", "no_open_pdf", reason="no_open_pdf"),
                    _row("paper-0003", "metadata_uncertain", reason="title_conflict"),
                ],
            )
            before = paths.state.read_bytes()
            summary = inspect_batch_status(paths.root)
            after = paths.state.read_bytes()
        self.assertEqual(before, after)
        self.assertEqual(summary.total, 3)
        self.assertEqual(summary.completed, 1)
        self.assertEqual(summary.waiting_zotero, 1)
        self.assertEqual(summary.review, 1)
        self.assertEqual(summary.next_action, "zotero")
        payload = json.loads(summary.to_json())
        self.assertEqual(payload["schema_version"], 1)
        self.assertNotIn("rows", payload)
        self.assertNotIn("cookies", payload)

    def test_status_separates_active_and_expired_leases_without_reclaiming(self) -> None:
        from paper_automation.batch_app import inspect_batch_status

        now = datetime.now(timezone.utc)
        attempts = {}
        rows = []
        for index, expiry in enumerate((now + timedelta(minutes=1), now - timedelta(minutes=1)), 1):
            task_id = f"paper-{index:04d}"
            rows.append(_row(task_id, "attempting"))
            attempts[task_id] = {
                "task_id": task_id,
                "attempt_id": f"attempt-{index}",
                "stage": "retry_failed",
                "started_at": (now - timedelta(minutes=2)).isoformat().replace("+00:00", "Z"),
                "lease_expires_at": expiry.isoformat().replace("+00:00", "Z"),
                "previous_status": "no_open_pdf",
                "previous_source": "oa",
                "previous_file": "",
                "previous_reason": "original",
            }
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._save(Path(tmp), rows, attempts)
            before = paths.state.read_bytes()
            summary = inspect_batch_status(paths.root, now=now)
            self.assertEqual(paths.state.read_bytes(), before)
        self.assertEqual(summary.active, 1)
        self.assertEqual(summary.expired, 1)
        self.assertEqual(summary.next_action, "wait")

    def test_status_cli_supports_human_and_json_output(self) -> None:
        from paper_batch import main

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._save(Path(tmp), [_row("paper-0001", "oa_downloaded")])
            human = io.StringIO()
            with redirect_stdout(human):
                self.assertEqual(main(["status", "--run-dir", str(paths.root)]), 0)
            machine = io.StringIO()
            with redirect_stdout(machine):
                self.assertEqual(main(["status", "--run-dir", str(paths.root), "--json"]), 0)
        self.assertIn("已完成：1/1", human.getvalue())
        self.assertTrue(json.loads(machine.getvalue())["complete"])

    def test_invalid_status_returns_two_without_traceback(self) -> None:
        from paper_batch import main

        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, redirect_stderr(stderr):
            self.assertEqual(main(["status", "--run-dir", tmp]), 2)
        self.assertNotIn("Traceback", stderr.getvalue())


class UnifiedBatchUiServiceTests(unittest.TestCase):
    @staticmethod
    def _var(value: str):
        return SimpleNamespace(get=lambda: value)

    def _ui(self, action: str):
        from paper_scraper_ui import PaperScraperUI

        ui = PaperScraperUI.__new__(PaperScraperUI)
        ui.batch_action_var = self._var(action)
        ui.batch_input_file_var = self._var("C:/papers.txt")
        ui.batch_run_dir_var = self._var("C:/run")
        ui.batch_run_name_var = self._var("run-name")
        ui.batch_login_wait_var = self._var("0")
        ui.batch_library_id_var = self._var("1")
        ui.batch_wait_seconds_var = self._var("0")
        ui.output_var = self._var("C:/results")
        ui.oa_email_var = self._var("reader@example.edu")
        ui.cookies_file_var = self._var("")
        ui._get_batch_text = lambda: ""
        return ui

    def test_unified_ui_maps_all_six_actions_through_shared_request(self) -> None:
        for action in ("start", "resume", "retry-failed", "recover-oa", "zotero", "status"):
            with self.subTest(action=action):
                ui = self._ui(action)
                command = ui._build_paper_batch_command(materialize_paste=False)
                self.assertIn(action, command)
                self.assertEqual(command[command.index(action)], action)
                if action in {"start", "retry-failed", "recover-oa", "zotero"}:
                    self.assertEqual(command[command.index("--wait-seconds") + 1], "0")
                if action == "status":
                    self.assertNotIn("--wait-seconds", command)


class ControlledBrowserIdentityTests(unittest.TestCase):
    def _session(self, root: Path, port: int = 0):
        from paper_automation.institutional.browser_session import DebugBrowserSession

        session = DebugBrowserSession(browser_exe="browser.exe", debug_port=port)
        session.instance_root = root
        session.debug_profile = str(root / "profile")
        session.log_path = str(root / "browser.log")
        session.instance_path = root / "instance.json"
        session.instance_lock_path = root / "instance.lock"
        return session

    def _descriptor(self, session, *, token: str = "owned", port: int = 9555) -> dict:
        return {
            "schema_version": 1,
            "pid": 1234,
            "executable": session._normalize_path(session.browser_exe),
            "profile": session._normalize_path(session.debug_profile),
            "port": port,
            "instance_token": token,
            "started_at": "2026-07-22T00:00:00Z",
        }

    def test_owned_instance_requires_all_identity_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = self._session(Path(tmp))
            profile = Path(session.debug_profile)
            profile.mkdir(parents=True)
            (profile / "DevToolsActivePort").write_text(
                "9555\n/devtools/browser/owned\n", encoding="utf-8",
            )
            descriptor = self._descriptor(session)
            with patch.object(session, "_pid_alive", return_value=True), patch.object(
                session, "_process_executable", return_value=session.browser_exe
            ), patch.object(
                session,
                "_version_payload",
                return_value={"webSocketDebuggerUrl": "ws://127.0.0.1:9555/devtools/browser/owned"},
            ):
                self.assertEqual(session._validate_instance_descriptor(descriptor), "valid")
                bad = dict(descriptor, instance_token="other")
                with self.assertRaisesRegex(RuntimeError, "browser_instance_mismatch"):
                    session._validate_instance_descriptor(bad)

    def test_unknown_fixed_port_is_never_reused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = self._session(Path(tmp), port=9555)
            with patch.object(session, "_read_instance_descriptor", return_value=None), patch.object(
                session,
                "_version_payload",
                return_value={"webSocketDebuggerUrl": "ws://unknown/devtools/browser/other"},
            ), patch.object(session, "_launch") as launch:
                with self.assertRaisesRegex(RuntimeError, "browser_instance_mismatch"):
                    session.ensure_ready()
            launch.assert_not_called()

    def test_dynamic_launch_publishes_descriptor_then_uses_actual_port(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = self._session(Path(tmp), port=0)
            process = Mock(pid=1234)
            descriptor = self._descriptor(session, port=9666)
            with patch.object(session, "_read_instance_descriptor", return_value=None), patch.object(
                session, "_launch", return_value=process
            ), patch.object(
                session, "_wait_for_launched_instance", return_value=descriptor
            ), patch.object(session, "_write_instance_descriptor") as write:
                self.assertTrue(session.ensure_ready())
            write.assert_called_once_with(descriptor)
            self.assertEqual(session.debug_port, 9666)

    def test_instance_lock_serializes_two_session_starters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = self._session(root)
            second = self._session(root)
            entered = threading.Event()
            release = threading.Event()
            order: list[str] = []

            def hold() -> None:
                with first._instance_lock(timeout=2):
                    order.append("first")
                    entered.set()
                    release.wait(2)

            def contend() -> None:
                entered.wait(2)
                with second._instance_lock(timeout=2):
                    order.append("second")

            t1 = threading.Thread(target=hold)
            t2 = threading.Thread(target=contend)
            t1.start()
            t2.start()
            self.assertTrue(entered.wait(1))
            time.sleep(0.05)
            self.assertEqual(order, ["first"])
            release.set()
            t1.join(2)
            t2.join(2)
            self.assertEqual(order, ["first", "second"])


if __name__ == "__main__":
    unittest.main()
