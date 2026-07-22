from __future__ import annotations

import base64
import io
import json
import os
import tempfile
import unittest
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from paper_automation.batch_stages import BatchOptions
from paper_automation.metadata_cache import LookupOutcome, MetadataCache


def _pdf_bytes(*, pages: int = 1, password: str = "") -> bytes:
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    if password:
        writer.encrypt(password)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def _state(paths, row: dict, *, active_attempts=None, manual_retry_used=True) -> dict:
    return {
        "version": 1,
        "run_dir": str(paths.root),
        "manual_retry_used": manual_retry_used,
        "options": asdict(BatchOptions(auto_oa_recovery=False)),
        "active_attempts": active_attempts or {},
        "rows": [row],
    }


def _attempt_record(task_id: str, *, stage: str, expires: datetime, reason: str) -> dict:
    started = expires - timedelta(minutes=5)
    previous_status = (
        "pending"
        if stage == "start"
        else ("captcha_required" if stage == "resume" else "no_open_pdf")
    )
    return {
        "task_id": task_id,
        "attempt_id": "attempt-old",
        "stage": stage,
        "started_at": started.isoformat().replace("+00:00", "Z"),
        "lease_expires_at": expires.isoformat().replace("+00:00", "Z"),
        "previous_status": previous_status,
        "previous_source": "institutional" if stage == "resume" else "oa",
        "previous_file": "",
        "previous_reason": reason,
    }


class AttemptLeaseTests(unittest.TestCase):
    def test_active_attempt_blocks_a_second_batch_process(self) -> None:
        from paper_automation import batch_workflow as workflow

        with tempfile.TemporaryDirectory() as tmp:
            paths = workflow.create_batch_paths(Path(tmp))
            task_id = "paper-0001"
            expires = datetime.now(timezone.utc) + timedelta(minutes=4)
            row = {
                "task_id": task_id,
                "doi": "10.1000/lease",
                "title": "Lease",
                "status": "attempting",
                "source": "oa",
                "file": "",
                "reason": "original_reason",
            }
            state = _state(
                paths,
                row,
                active_attempts={task_id: _attempt_record(task_id, stage="retry_failed", expires=expires, reason="original_reason")},
            )
            workflow.save_batch_state(paths, state)
            before = paths.state.read_bytes()

            with self.assertRaisesRegex(ValueError, "batch_attempt_in_progress"):
                workflow.retry_failed_batch(paths.root, retry_all=True)
            self.assertEqual(paths.state.read_bytes(), before)

    def test_expired_retry_restores_original_reason_before_reprocessing(self) -> None:
        from paper_automation import batch_workflow as workflow

        class Gateway:
            seen: list[dict] = []

            def run_institutional_only(self, rows, _paths, _options):
                self.seen = [dict(row) for row in rows]
                return [
                    {
                        **row,
                        "status": "no_entitlement",
                        "source": "institutional",
                        "file": "",
                        "reason": "no_entitlement",
                    }
                    for row in rows
                ]

        with tempfile.TemporaryDirectory() as tmp:
            paths = workflow.create_batch_paths(Path(tmp))
            task_id = "paper-0001"
            original_reason = "publisher_timeout"
            row = {
                "task_id": task_id,
                "doi": "10.1000/recover",
                "title": "Recover",
                "status": "attempting",
                "source": "oa",
                "file": "",
                "reason": original_reason,
            }
            expired = datetime.now(timezone.utc) - timedelta(seconds=1)
            state = _state(
                paths,
                row,
                active_attempts={task_id: _attempt_record(task_id, stage="retry_failed", expires=expired, reason=original_reason)},
            )
            workflow.save_batch_state(paths, state)
            gateway = Gateway()
            workflow.retry_failed_batch(
                paths.root,
                gateway=gateway,
                skip_oa=True,
            )
            saved = workflow.load_batch_state(paths.root)

        self.assertEqual(gateway.seen[0]["status"], "pending")
        self.assertEqual(gateway.seen[0]["reason"], original_reason)
        self.assertEqual(saved["active_attempts"], {})
        self.assertEqual(saved["rows"][0]["status"], "no_entitlement")

    def test_expired_start_attempt_is_reclaimed_and_run_again(self) -> None:
        from paper_automation import batch_workflow as workflow

        class Gateway:
            seen: list[dict] = []

            def run_initial(self, rows, _paths, _options):
                self.seen = [dict(row) for row in rows]
                return [
                    {
                        **row,
                        "status": "no_open_pdf",
                        "source": "oa",
                        "file": "",
                        "reason": "no_open_pdf",
                    }
                    for row in rows
                ]

        with tempfile.TemporaryDirectory() as tmp:
            paths = workflow.create_batch_paths(Path(tmp))
            task_id = "paper-0001"
            expired = datetime.now(timezone.utc) - timedelta(seconds=1)
            row = {
                "task_id": task_id,
                "doi": "10.1000/start-recover",
                "title": "Start Recovery",
                "status": "attempting",
                "source": "",
                "file": "",
                "reason": "",
            }
            workflow.save_batch_state(
                paths,
                _state(
                    paths,
                    row,
                    active_attempts={
                        task_id: _attempt_record(
                            task_id,
                            stage="start",
                            expires=expired,
                            reason="",
                        )
                    },
                ),
            )
            gateway = Gateway()
            workflow.retry_failed_batch(
                paths.root,
                gateway=gateway,
                skip_oa=False,
            )
            saved = workflow.load_batch_state(paths.root)

        self.assertEqual(gateway.seen[0]["status"], "pending")
        self.assertEqual(saved["active_attempts"], {})
        self.assertEqual(saved["rows"][0]["status"], "no_open_pdf")

    def test_expired_manual_attempt_can_resume_after_manual_flag_was_saved(self) -> None:
        from paper_automation import batch_workflow as workflow

        class Gateway:
            called = False

            def run_retry(self, rows, _paths, _options):
                self.called = True
                return [{**rows[0], "status": "no_entitlement", "reason": "retry_done"}]

        with tempfile.TemporaryDirectory() as tmp:
            paths = workflow.create_batch_paths(Path(tmp))
            task_id = "paper-0001"
            row = {
                "task_id": task_id,
                "doi": "10.1000/manual",
                "title": "Manual",
                "status": "attempting",
                "source": "institutional",
                "file": "",
                "reason": "captcha_required",
            }
            state = _state(
                paths,
                row,
                manual_retry_used=True,
                active_attempts={
                    task_id: _attempt_record(
                        task_id,
                        stage="resume",
                        expires=datetime.now(timezone.utc) - timedelta(seconds=1),
                        reason="captcha_required",
                    )
                },
            )
            workflow.save_batch_state(paths, state)
            gateway = Gateway()
            workflow.resume_batch(paths.root, gateway=gateway)
            saved = workflow.load_batch_state(paths.root)

        self.assertTrue(gateway.called)
        self.assertEqual(saved["active_attempts"], {})
        self.assertEqual(saved["rows"][0]["reason"], "retry_done")

    def test_stale_attempt_result_is_fenced_after_a_new_claim(self) -> None:
        from paper_automation import batch_workflow as workflow

        with tempfile.TemporaryDirectory() as tmp:
            paths = workflow.create_batch_paths(Path(tmp))
            row = {
                "task_id": "paper-0001",
                "doi": "10.1000/fence",
                "title": "Fence",
                "status": "no_open_pdf",
                "source": "oa",
                "file": "",
                "reason": "old_failure",
            }
            state = _state(paths, row)
            workflow.save_batch_state(paths, state)
            with workflow.batch_state_lock(paths.root):
                state = workflow.load_batch_state(paths.root)
                old_expected, _ = workflow._claim_attempts_locked(
                    state,
                    paths,
                    {"paper-0001"},
                    stage="retry_failed",
                    now=datetime.now(timezone.utc),
                    lease_seconds=1,
                )
            with workflow.batch_state_lock(paths.root):
                latest = workflow.load_batch_state(paths.root)
                latest["active_attempts"]["paper-0001"]["lease_expires_at"] = (
                    datetime.now(timezone.utc) - timedelta(seconds=1)
                ).isoformat().replace("+00:00", "Z")
                workflow.save_batch_state(paths, latest)
                workflow._ensure_no_active_attempts_locked(latest, now=datetime.now(timezone.utc))
                new_expected, _ = workflow._claim_attempts_locked(
                    latest,
                    paths,
                    {"paper-0001"},
                    stage="retry_failed",
                    now=datetime.now(timezone.utc),
                )

            with self.assertRaisesRegex(ValueError, "attempt_lease_lost"):
                workflow._finish_fenced_attempts(
                    paths,
                    state,
                    old_expected,
                    returned_updates=[{**row, "status": "oa_downloaded"}],
                )
            saved = workflow.load_batch_state(paths.root)
            self.assertEqual(
                saved["active_attempts"]["paper-0001"]["attempt_id"],
                new_expected["paper-0001"],
            )
            self.assertEqual(saved["rows"][0]["status"], "attempting")


class MetadataCacheTests(unittest.TestCase):
    def test_long_and_short_ttl_with_fake_clock(self) -> None:
        clock = [1000.0]
        with tempfile.TemporaryDirectory() as tmp:
            cache = MetadataCache(Path(tmp) / "metadata_cache.jsonl", now=lambda: clock[0])
            ok = LookupOutcome("crossref", "doi", "10.1000/A", "ok", {"DOI": "10.1000/a"})
            transient = LookupOutcome("openalex", "doi", "10.1000/A", "timeout")
            cache.put(ok)
            cache.put(transient)
            clock[0] += 301
            self.assertIsNotNone(cache.get("crossref", "doi", "10.1000/a"))
            self.assertIsNone(cache.get("openalex", "doi", "10.1000/a"))
            clock[0] += 30 * 24 * 60 * 60
            self.assertIsNone(cache.get("crossref", "doi", "10.1000/a"))

    def test_trailing_partial_is_ignored_and_repaired_but_middle_corruption_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "metadata_cache.jsonl"
            cache = MetadataCache(path)
            cache.put(LookupOutcome("crossref", "doi", "10.1000/a", "not_found"))
            with path.open("ab") as handle:
                handle.write(b'{"partial":')
            self.assertEqual(cache.get("crossref", "doi", "10.1000/a").status, "not_found")
            cache.put(LookupOutcome("openalex", "doi", "10.1000/a", "timeout"))
            self.assertTrue(path.read_bytes().endswith(b"\n"))
            path.write_bytes(b"not-json\n" + path.read_bytes())
            with self.assertRaisesRegex(ValueError, "metadata_cache_corrupt:line=1"):
                cache.get("crossref", "doi", "10.1000/a")

    def test_doi_only_preflight_performs_zero_network_calls(self) -> None:
        from paper_automation.doi_preflight import preflight_rows
        from paper_automation.metadata_resolver import MetadataResolver

        calls = []

        def fail_if_called(*args, **kwargs):
            calls.append(args[0])
            raise AssertionError("network should not be called")

        rows = [{"task_id": "paper-0001", "doi": "https://doi.org/10.1000/ABC", "title": "", "status": "pending"}]
        updated, changes = preflight_rows(rows, resolver=MetadataResolver(http_json=fail_if_called))
        self.assertEqual(calls, [])
        self.assertEqual(changes, [])
        self.assertEqual(updated[0]["doi"], "10.1000/abc")

    def test_structured_lookup_errors_and_cache_reuse(self) -> None:
        from paper_automation.metadata_resolver import MetadataResolver
        from paper_automation.models import PaperCandidate

        counts = {"crossref": 0, "openalex": 0, "unpaywall": 0}

        def getter(url, _headers, _timeout):
            if "crossref" in url:
                counts["crossref"] += 1
                return {"message": {"DOI": "10.1000/cache", "title": ["Cached paper"]}}
            if "openalex" in url:
                counts["openalex"] += 1
                return {"results": [{"doi": "https://doi.org/10.1000/cache", "title": "Cached paper"}]}
            counts["unpaywall"] += 1
            return {"doi": "10.1000/cache", "is_oa": False}

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "metadata_cache.jsonl"
            candidate = PaperCandidate(1, "10.1000/cache", doi="10.1000/cache", title="Cached paper")
            first = MetadataResolver(email="a@example.org", http_json=getter, cache_path=cache_path).resolve_one(candidate)
            second = MetadataResolver(email="a@example.org", http_json=getter, cache_path=cache_path).resolve_one(candidate)
            self.assertEqual(counts, {"crossref": 1, "openalex": 1, "unpaywall": 1})
            self.assertTrue(any(outcome.cached for outcome in second.lookup_outcomes.values()))
            self.assertTrue(all(outcome.status == "ok" for outcome in first.lookup_outcomes.values()))

    def test_http_429_timeout_dns_and_invalid_response_have_distinct_statuses(self) -> None:
        from paper_automation.metadata_resolver import MetadataResolver
        from paper_automation.models import PaperCandidate

        failures = [
            (HTTPError("https://api.crossref.org", 429, "rate", {}, None), "rate_limited"),
            (TimeoutError("slow"), "timeout"),
            (URLError(OSError("dns")), "network_error"),
        ]
        for error, expected in failures:
            with self.subTest(expected=expected):
                resolver = MetadataResolver(http_json=lambda *_args, _error=error: (_ for _ in ()).throw(_error))
                result = resolver.resolve_one(PaperCandidate(1, "10.1000/x", doi="10.1000/x"))
                statuses = {outcome.status for outcome in result.lookup_outcomes.values()}
                self.assertIn(expected, statuses)
        invalid = MetadataResolver(http_json=lambda *_args: ["not", "an", "object"])
        result = invalid.resolve_one(PaperCandidate(1, "10.1000/x", doi="10.1000/x"))
        self.assertIn("invalid_response", {item.status for item in result.lookup_outcomes.values()})


class StreamingAndParserTests(unittest.TestCase):
    def test_english_compat_http_path_streams_without_response_content(self) -> None:
        from sd_scraper_en import _publish_curl_pdf_response

        payload = _pdf_bytes()

        class Response:
            status_code = 200
            headers = {"Content-Length": str(len(payload))}
            closed = False

            @property
            def content(self):
                raise AssertionError("response.content must not be read")

            def iter_content(self, chunk_size):
                self.chunk_size = chunk_size
                midpoint = len(payload) // 2
                yield payload[:midpoint]
                yield payload[midpoint:]

            def close(self):
                self.closed = True

        response = Response()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "compat.pdf"
            published = _publish_curl_pdf_response(response, target)
            saved = published.read_bytes()

        self.assertEqual(saved, payload)
        self.assertTrue(response.closed)

    def test_stream_limits_and_interruption_preserve_existing_file_and_clean_temp(self) -> None:
        from paper_automation.artifact_store import publish_pdf_stream_atomic

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            target = directory / "paper.pdf"
            original = _pdf_bytes()
            target.write_bytes(original)

            def interrupted():
                yield b"%PDF-1.7\n"
                raise ConnectionError("cut")

            with self.assertRaises(ConnectionError):
                publish_pdf_stream_atomic(interrupted(), directory, target.name, max_bytes=1024)
            self.assertEqual(target.read_bytes(), original)
            self.assertEqual(list(directory.glob(".pdf_stream_*.tmp")), [])
            with self.assertRaisesRegex(ValueError, "response_too_large"):
                publish_pdf_stream_atomic([b"%PDF-", b"x" * 20], directory, "large.pdf", max_bytes=10)
            self.assertFalse((directory / "large.pdf").exists())

            consumed = False

            def should_not_be_read():
                nonlocal consumed
                consumed = True
                yield original

            with self.assertRaisesRegex(ValueError, "response_too_large"):
                publish_pdf_stream_atomic(
                    should_not_be_read(),
                    directory,
                    "declared-large.pdf",
                    content_length=2048,
                    max_bytes=1024,
                )
            self.assertFalse(consumed)
            with self.assertRaisesRegex(ValueError, "response_length_mismatch"):
                publish_pdf_stream_atomic(
                    [original],
                    directory,
                    "truncated.pdf",
                    content_length=len(original) + 1,
                    max_bytes=2048,
                )

    def test_parser_accepts_one_page_and_rejects_zero_page_corrupt_and_password_pdf(self) -> None:
        from paper_automation.pdf_validation import validate_pdf_with_parser

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            samples = {
                "one.pdf": (_pdf_bytes(pages=1), True),
                "zero.pdf": (_pdf_bytes(pages=0), False),
                "broken.pdf": (b"%PDF-1.7\nbroken\n%%EOF\n", False),
                "encrypted.pdf": (_pdf_bytes(pages=1, password="secret"), False),
            }
            for name, (content, expected) in samples.items():
                path = root / name
                path.write_bytes(content)
                valid, _detail = validate_pdf_with_parser(path)
                self.assertEqual(valid, expected, name)

    def test_parser_failure_downgrades_owned_success_and_logs_internal_detail(self) -> None:
        from paper_automation import batch_workflow as workflow

        with tempfile.TemporaryDirectory() as tmp:
            paths = workflow.create_batch_paths(Path(tmp))
            broken = paths.pdfs / "paper-0001_deadbeef.pdf"
            broken.write_bytes(b"%PDF-1.7\nbroken xref\n%%EOF\n")
            row = {
                "task_id": "paper-0001",
                "doi": "10.1000/broken",
                "title": "Broken",
                "status": "oa_downloaded",
                "source": "oa",
                "file": str(broken),
                "reason": "",
            }
            rows = [row]
            self.assertTrue(workflow._revalidate_success_rows(paths, rows))
            self.assertEqual(row["status"], "not_pdf_response")
            self.assertEqual(row["file"], "")
            self.assertEqual(row["reason"], "delivery_pdf_revalidation_failed")
            log = paths.working / "delivery_pdf_validation_failures.jsonl"
            self.assertIn("parser_", log.read_text(encoding="utf-8"))

    def test_devtools_capture_uses_fetch_stream_and_io_reads(self) -> None:
        from sd_scraper import _dt_capture_pdf

        pdf = _pdf_bytes()

        class FakeWebSocket:
            def __init__(self):
                self.messages = []
                self.methods = []
                self.read_index = 0

            def settimeout(self, _timeout):
                return None

            def send(self, raw):
                request = json.loads(raw)
                method = request["method"]
                self.methods.append(method)
                request_id = request["id"]
                if method == "Page.navigate":
                    self.messages.append({
                        "method": "Fetch.requestPaused",
                        "params": {
                            "requestId": "fetch-1",
                            "request": {"url": "https://example.test/paper.pdf"},
                            "responseStatusCode": 200,
                            "responseHeaders": [
                                {"name": "Content-Type", "value": "application/pdf"},
                                {"name": "Content-Length", "value": str(len(pdf))},
                            ],
                        },
                    })
                elif method == "Fetch.takeResponseBodyAsStream":
                    self.messages.append({"id": request_id, "result": {"stream": "io-1"}})
                elif method == "IO.read":
                    split = len(pdf) // 2
                    chunks = (pdf[:split], pdf[split:])
                    chunk = chunks[self.read_index]
                    self.read_index += 1
                    self.messages.append({
                        "id": request_id,
                        "result": {
                            "data": base64.b64encode(chunk).decode("ascii"),
                            "base64Encoded": True,
                            "eof": self.read_index == len(chunks),
                        },
                    })

            def recv(self):
                if not self.messages:
                    raise TimeoutError("no message")
                return json.dumps(self.messages.pop(0))

            def close(self):
                return None

        fake = FakeWebSocket()
        with tempfile.TemporaryDirectory() as tmp, patch(
            "websocket.create_connection", return_value=fake
        ):
            target = Path(tmp) / "paper.pdf"
            captured, note = _dt_capture_pdf(
                "ws://test",
                "https://example.test/paper.pdf",
                output_path=target,
                timeout=2,
            )
            self.assertEqual(Path(captured), target)
            self.assertTrue(target.is_file())
            self.assertEqual(note, "https://example.test/paper.pdf")
        self.assertIn("Fetch.takeResponseBodyAsStream", fake.methods)
        self.assertIn("IO.read", fake.methods)
        self.assertNotIn("Fetch.getResponseBody", fake.methods)
        self.assertNotIn("Network.getResponseBody", fake.methods)

    def test_devtools_stream_unavailable_is_explicit(self) -> None:
        from sd_scraper import _dt_capture_pdf

        class FakeWebSocket:
            def __init__(self):
                self.messages = []

            def settimeout(self, _timeout):
                return None

            def send(self, raw):
                request = json.loads(raw)
                if request["method"] == "Page.navigate":
                    self.messages.append({
                        "method": "Fetch.requestPaused",
                        "params": {
                            "requestId": "fetch-1",
                            "request": {"url": "https://example.test/paper.pdf"},
                            "responseStatusCode": 200,
                            "responseHeaders": [{"name": "Content-Type", "value": "application/pdf"}],
                        },
                    })
                elif request["method"] == "Fetch.takeResponseBodyAsStream":
                    self.messages.append({"id": request["id"], "error": {"message": "unknown method"}})

            def recv(self):
                if not self.messages:
                    raise TimeoutError
                return json.dumps(self.messages.pop(0))

            def close(self):
                return None

        with patch("websocket.create_connection", return_value=FakeWebSocket()):
            captured, note = _dt_capture_pdf("ws://test", "https://example.test/paper.pdf", timeout=2)
        self.assertIsNone(captured)
        self.assertEqual(note, "cdp_stream_unavailable")


if __name__ == "__main__":
    unittest.main()
