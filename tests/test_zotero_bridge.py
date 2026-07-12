from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def bridge_result(job, rows):
    return {
        "schema_version": 1,
        "job_id": job.job_id,
        "payload_sha256": job.payload_sha256,
        "plugin_version": "0.1.0",
        "zotero_version": "9.0.6",
        "started_at": "2026-07-11T09:06:00Z",
        "finished_at": "2026-07-11T09:07:00Z",
        "rows": rows,
    }


class ZoteroBridgeRequestTests(unittest.TestCase):
    def _run(self, root: Path, fallback_count: int = 1) -> Path:
        from paper_automation.batch_stages import BatchOptions
        from paper_automation.batch_workflow import NORMALIZED_FIELDS, create_batch_paths, save_batch_state

        paths = create_batch_paths(root, now=datetime(2026, 7, 11, 9, 0, 0))
        rows = []
        for number in range(1, fallback_count + 1):
            rows.append({
                field: value
                for field, value in zip(
                    NORMALIZED_FIELDS,
                    [
                        f"paper-{number:04d}", str(number), f"10.1000/{number:04d}", "", f"10.1000/{number:04d}",
                        f"Example Paper {number}", "A. Author", "Journal", "2025", "Publisher",
                        "no_open_pdf", "project", "", "no_legal_open_pdf",
                    ],
                )
            })
        save_batch_state(paths, {
            "version": 1,
            "run_dir": str(paths.root),
            "manual_retry_used": False,
            "options": asdict(BatchOptions()),
            "rows": rows,
        })
        with paths.zotero_fallback.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=NORMALIZED_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        return paths.root

    def _fallback_rows(self, run_dir: Path) -> list[dict[str, str]]:
        path = run_dir / "working" / "zotero_fallback.csv"
        with path.open("r", newline="", encoding="utf-8-sig") as handle:
            return list(csv.DictReader(handle))

    @staticmethod
    def _rehash_request(request: dict) -> None:
        payload = {
            key: request[key]
            for key in sorted(request)
            if key != "payload_sha256"
        }
        request["payload_sha256"] = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()

    def test_default_root_uses_local_appdata(self) -> None:
        from paper_automation.zotero_bridge import default_bridge_root

        root = default_bridge_root({"LOCALAPPDATA": r"C:\Users\student\AppData\Local"})
        self.assertEqual(
            root,
            Path(r"C:\Users\student\AppData\Local\PaperScraperDOI\zotero-bridge\v1"),
        )

    def test_read_active_bridge_instance_follows_open_zotero_not_test_default(self) -> None:
        from paper_automation.zotero_bridge import (
            format_active_bridge_target,
            read_active_bridge_instance,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / "active-instance.json"
            marker.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "instance_id": "main-zeterofiles",
                        "data_dir": r"D:\zeterofiles",
                        "profile_dir": r"C:\Profiles\g39b695l.default",
                        "profile_name": "g39b695l.default",
                        "zotero_version": "9.0.6",
                        "plugin_version": "0.1.9",
                        "updated_at": "2026-07-12T12:00:00Z",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            instance = read_active_bridge_instance(
                root,
                now=datetime(2026, 7, 12, 12, 0, 30, tzinfo=timezone.utc),
            )
            self.assertIsNotNone(instance)
            assert instance is not None
            self.assertEqual(instance["data_dir"], r"D:\zeterofiles")
            self.assertEqual(instance["profile_name"], "g39b695l.default")
            text = format_active_bridge_target(instance)
            self.assertIn("当前打开的 Zotero", text)
            self.assertIn(r"D:\zeterofiles", text)
            self.assertNotIn("Zotero-Test-Data", text)

            stale = read_active_bridge_instance(
                root,
                now=datetime(2026, 7, 12, 12, 5, 0, tzinfo=timezone.utc),
            )
            self.assertIsNone(stale)
            self.assertIn("未检测到", format_active_bridge_target(None))

    def test_request_contains_only_current_fallback_metadata(self) -> None:
        from paper_automation.zotero_bridge import build_bridge_request

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self._run(Path(tmp))
            request = build_bridge_request(
                run_dir,
                library_id=1,
                job_id="11111111-1111-4111-8111-111111111111",
                now=datetime(2026, 7, 11, 9, 5, tzinfo=timezone.utc),
            )

        self.assertEqual(request["schema_version"], 1)
        self.assertEqual(request["library_id"], 1)
        self.assertEqual(request["run_id"], run_dir.name)
        self.assertEqual(request["chunk_index"], 1)
        self.assertEqual(request["chunk_count"], 1)
        self.assertEqual(request["items"], [{
            "task_id": "paper-0001",
            "doi": "10.1000/0001",
            "title": "Example Paper 1",
            "authors": "A. Author",
            "year": "2025",
        }])
        self.assertRegex(request["payload_sha256"], r"^[0-9a-f]{64}$")
        self.assertNotIn("file", json.dumps(request))
        self.assertNotIn("reason", json.dumps(request))

    def test_unknown_request_field_and_duplicate_task_are_rejected(self) -> None:
        from paper_automation.zotero_bridge import build_bridge_request, validate_bridge_request

        with tempfile.TemporaryDirectory() as tmp:
            request = build_bridge_request(
                self._run(Path(tmp)),
                library_id=1,
                job_id="11111111-1111-4111-8111-111111111111",
                now=datetime(2026, 7, 11, 9, 5, tzinfo=timezone.utc),
            )
        request["unexpected"] = True
        with self.assertRaisesRegex(ValueError, "^bridge_request_fields_invalid$"):
            validate_bridge_request(request)
        request.pop("unexpected")
        request["items"].append(dict(request["items"][0]))
        with self.assertRaisesRegex(ValueError, "^bridge_task_id_duplicate$"):
            validate_bridge_request(request)

    def test_101_fallback_rows_become_two_stable_chunk_requests(self) -> None:
        from paper_automation.zotero_bridge import build_bridge_requests

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self._run(Path(tmp), fallback_count=101)
            requests = build_bridge_requests(
                run_dir,
                library_id=1,
                job_ids=(
                    "11111111-1111-4111-8111-111111111111",
                    "22222222-2222-4222-8222-222222222222",
                ),
                now=datetime(2026, 7, 11, 9, 5, tzinfo=timezone.utc),
            )

        self.assertEqual([len(value["items"]) for value in requests], [100, 1])
        self.assertEqual([value["chunk_index"] for value in requests], [1, 2])
        self.assertEqual([value["chunk_count"] for value in requests], [2, 2])
        self.assertEqual({value["run_id"] for value in requests}, {run_dir.name})
        self.assertEqual(len({value["collection_name"] for value in requests}), 1)

    def test_supplied_rows_must_equal_the_current_original_chunk_slice(self) -> None:
        from paper_automation.zotero_bridge import build_bridge_request

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self._run(Path(tmp), fallback_count=101)
            fallback_rows = self._fallback_rows(run_dir)
            first_chunk = fallback_rows[:100]

            accepted = build_bridge_request(
                run_dir,
                library_id=1,
                job_id="11111111-1111-4111-8111-111111111111",
                now=datetime(2026, 7, 11, 9, 5, tzinfo=timezone.utc),
                rows=first_chunk,
                chunk_index=1,
                chunk_count=2,
            )

            injected_rows = [dict(row) for row in first_chunk]
            injected_rows[0]["title"] = "Injected metadata"
            invalid_cases = {
                "metadata_injection": injected_rows,
                "wrong_chunk": fallback_rows[100:],
                "wrong_order": list(reversed(first_chunk)),
            }
            for label, rows in invalid_cases.items():
                with self.subTest(label=label):
                    with self.assertRaisesRegex(
                        ValueError,
                        "^bridge_request_rows_invalid$",
                    ):
                        build_bridge_request(
                            run_dir,
                            library_id=1,
                            job_id="11111111-1111-4111-8111-111111111111",
                            now=datetime(2026, 7, 11, 9, 5, tzinfo=timezone.utc),
                            rows=rows,
                            chunk_index=1,
                            chunk_count=2,
                        )

        self.assertEqual(accepted["items"][0]["task_id"], "paper-0001")
        self.assertEqual(accepted["items"][-1]["task_id"], "paper-0100")

    def test_fallback_rows_must_match_the_current_batch_state(self) -> None:
        from paper_automation.batch_workflow import NORMALIZED_FIELDS
        from paper_automation.zotero_bridge import build_bridge_request

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self._run(Path(tmp))
            fallback_rows = self._fallback_rows(run_dir)
            fallback_rows[0]["title"] = "Changed only in fallback CSV"
            path = run_dir / "working" / "zotero_fallback.csv"
            with path.open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=NORMALIZED_FIELDS)
                writer.writeheader()
                writer.writerows(fallback_rows)

            with self.assertRaisesRegex(
                ValueError,
                "^bridge_fallback_state_mismatch$",
            ):
                build_bridge_request(
                    run_dir,
                    library_id=1,
                    job_id="11111111-1111-4111-8111-111111111111",
                    now=datetime(2026, 7, 11, 9, 5, tzinfo=timezone.utc),
                )

    def test_supplied_job_ids_must_match_chunk_count_and_be_unique(self) -> None:
        from paper_automation.zotero_bridge import build_bridge_requests

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self._run(Path(tmp), fallback_count=101)
            with self.subTest("count"):
                with self.assertRaisesRegex(ValueError, "^bridge_job_count_invalid$"):
                    build_bridge_requests(
                        run_dir,
                        library_id=1,
                        job_ids=("11111111-1111-4111-8111-111111111111",),
                        now=datetime(2026, 7, 11, 9, 5, tzinfo=timezone.utc),
                    )
            with self.subTest("duplicate"):
                with self.assertRaisesRegex(
                    ValueError,
                    "^bridge_job_id_duplicate$",
                ):
                    build_bridge_requests(
                        run_dir,
                        library_id=1,
                        job_ids=(
                            "11111111-1111-4111-8111-111111111111",
                            "11111111-1111-4111-8111-111111111111",
                        ),
                        now=datetime(2026, 7, 11, 9, 5, tzinfo=timezone.utc),
                    )

    def test_validate_bridge_request_rejects_invalid_or_non_utc_timestamps(self) -> None:
        from paper_automation.zotero_bridge import build_bridge_request, validate_bridge_request

        with tempfile.TemporaryDirectory() as tmp:
            request = build_bridge_request(
                self._run(Path(tmp)),
                library_id=1,
                job_id="11111111-1111-4111-8111-111111111111",
                now=datetime(2026, 7, 11, 9, 5, tzinfo=timezone.utc),
            )

        invalid_values = (
            "not-an-iso-timestamp",
            "2026-07-11T09:05:00",
            "2026-07-11T09:05:00+00:00",
            "2026-07-11T17:05:00+08:00",
        )
        for value in invalid_values:
            with self.subTest(value=value):
                candidate = dict(request)
                candidate["created_at"] = value
                self._rehash_request(candidate)
                with self.assertRaisesRegex(
                    ValueError,
                    "^bridge_request_time_invalid$",
                ):
                    validate_bridge_request(candidate)

    def test_validate_bridge_request_requires_expiry_after_creation(self) -> None:
        from paper_automation.zotero_bridge import build_bridge_request, validate_bridge_request

        with tempfile.TemporaryDirectory() as tmp:
            request = build_bridge_request(
                self._run(Path(tmp)),
                library_id=1,
                job_id="11111111-1111-4111-8111-111111111111",
                now=datetime(2026, 7, 11, 9, 5, tzinfo=timezone.utc),
            )

        for value in ("2026-07-11T09:05:00Z", "2026-07-11T09:04:59Z"):
            with self.subTest(value=value):
                candidate = dict(request)
                candidate["expires_at"] = value
                self._rehash_request(candidate)
                with self.assertRaisesRegex(
                    ValueError,
                    "^bridge_request_time_invalid$",
                ):
                    validate_bridge_request(candidate)

    def test_boolean_values_are_not_accepted_as_integer_request_fields(self) -> None:
        from paper_automation.zotero_bridge import build_bridge_request, validate_bridge_request

        with tempfile.TemporaryDirectory() as tmp:
            request = build_bridge_request(
                self._run(Path(tmp)),
                library_id=1,
                job_id="11111111-1111-4111-8111-111111111111",
                now=datetime(2026, 7, 11, 9, 5, tzinfo=timezone.utc),
            )

        invalid_values = (
            ("schema_version", True, "bridge_schema_version_invalid"),
            ("library_id", True, "bridge_library_id_invalid"),
            ("chunk_index", True, "bridge_chunk_index_invalid"),
            ("chunk_count", True, "bridge_chunk_index_invalid"),
        )
        for field, value, code in invalid_values:
            with self.subTest(field=field):
                candidate = dict(request)
                candidate[field] = value
                self._rehash_request(candidate)
                with self.assertRaisesRegex(ValueError, f"^{code}$"):
                    validate_bridge_request(candidate)

    def test_queue_publishes_a_stable_two_chunk_manifest(self) -> None:
        from paper_automation.zotero_bridge import queue_bridge_jobs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = self._run(root / "runs", fallback_count=101)
            kwargs = {
                "library_id": 1,
                "bridge_root": root / "bridge",
                "job_ids": (
                    "11111111-1111-4111-8111-111111111111",
                    "22222222-2222-4222-8222-222222222222",
                ),
                "now": datetime(2026, 7, 11, 9, 5, tzinfo=timezone.utc),
            }
            first = queue_bridge_jobs(run_dir, **kwargs)
            second = queue_bridge_jobs(run_dir, **kwargs)
            manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
            requests = [
                json.loads(job.request_path.read_text(encoding="utf-8"))
                for job in first.jobs
            ]
            published_count = len(list((root / "bridge" / "inbox").glob("*.json")))

        self.assertEqual(first, second)
        self.assertEqual([len(value["items"]) for value in requests], [100, 1])
        self.assertEqual([job.chunk_index for job in first.jobs], [1, 2])
        self.assertEqual([job.chunk_count for job in first.jobs], [2, 2])
        self.assertEqual(manifest["jobs"][0]["task_ids"][0], "paper-0001")
        self.assertEqual(manifest["jobs"][1]["task_ids"], ["paper-0101"])
        self.assertTrue(manifest["collection_name"].startswith("Codex下载回退_"))
        self.assertEqual(published_count, 2)

    def test_changed_fallback_after_manifest_fails_closed(self) -> None:
        from paper_automation.zotero_bridge import queue_bridge_jobs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = self._run(root / "runs")
            queue_bridge_jobs(run_dir, bridge_root=root / "bridge", library_id=1)
            fallback = run_dir / "working" / "zotero_fallback.csv"
            fallback.write_text(
                fallback.read_text(encoding="utf-8-sig").replace(
                    "Example Paper 1", "Changed"
                ),
                encoding="utf-8-sig",
            )
            with self.assertRaisesRegex(ValueError, "^bridge_batch_manifest_conflict$"):
                queue_bridge_jobs(run_dir, bridge_root=root / "bridge", library_id=1)

    def test_two_threads_publish_one_complete_manifest_without_temp_files(self) -> None:
        from paper_automation.zotero_bridge import queue_bridge_jobs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = self._run(root / "runs", fallback_count=101)
            kwargs = {
                "library_id": 1,
                "bridge_root": root / "bridge",
                "job_ids": (
                    "11111111-1111-4111-8111-111111111111",
                    "22222222-2222-4222-8222-222222222222",
                ),
                "now": datetime(2026, 7, 11, 9, 5, tzinfo=timezone.utc),
            }
            with ThreadPoolExecutor(max_workers=2) as pool:
                first, second = list(pool.map(lambda _: queue_bridge_jobs(run_dir, **kwargs), range(2)))
            manifest_paths = list((run_dir / "working").glob("zotero_bridge_jobs.json"))
            published = list((root / "bridge" / "inbox").glob("*.json"))
            temporary = list(root.rglob("*.tmp"))
            requests = [json.loads(path.read_text(encoding="utf-8")) for path in published]

        self.assertEqual(first, second)
        self.assertEqual(len(manifest_paths), 1)
        self.assertEqual(len(published), 2)
        self.assertEqual(temporary, [])
        self.assertEqual({value["chunk_count"] for value in requests}, {2})
        self.assertEqual({value["chunk_index"] for value in requests}, {1, 2})


class ZoteroBridgeResultTests(ZoteroBridgeRequestTests):
    def test_public_publish_writes_exact_five_column_csv(self) -> None:
        from paper_automation.zotero_bridge import publish_zotero_results_csv

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self._run(Path(tmp) / "runs")
            csv_path = publish_zotero_results_csv(
                run_dir,
                [{
                    "task_id": "paper-0001",
                    "zotero_item_id": "",
                    "attachment_path": "",
                    "status": "no_pdf",
                    "reason": "fixture",
                }],
                now=datetime(2026, 7, 11, 9, 8, tzinfo=timezone.utc),
            )
            with csv_path.open("r", newline="", encoding="utf-8-sig") as handle:
                records = list(csv.reader(handle, strict=True))

        self.assertEqual(
            records,
            [
                ["task_id", "zotero_item_id", "attachment_path", "status", "reason"],
                ["paper-0001", "", "", "no_pdf", "fixture"],
            ],
        )

    def test_valid_one_job_result_publishes_exact_five_column_csv(self) -> None:
        from paper_automation.zotero_bridge import consume_bridge_batch, queue_bridge_jobs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = self._run(root / "runs")
            bridge = queue_bridge_jobs(run_dir, library_id=1, bridge_root=root / "bridge")
            job = bridge.jobs[0]
            pdf = root / "source.pdf"
            pdf.write_bytes(b"%PDF-1.7\nfixture\n%%EOF\n")
            job.result_path.write_text(
                json.dumps(bridge_result(job, [{
                    "task_id": "paper-0001",
                    "zotero_item_id": "304",
                    "attachment_path": str(pdf.resolve()),
                    "status": "existing_pdf",
                    "reason": "",
                }])),
                encoding="utf-8",
            )
            csv_path = consume_bridge_batch(bridge)
            with csv_path.open("r", newline="", encoding="utf-8-sig") as handle:
                records = list(csv.reader(handle, strict=True))
            csv_name = csv_path.name

        self.assertEqual(
            records[0],
            ["task_id", "zotero_item_id", "attachment_path", "status", "reason"],
        )
        self.assertEqual(records[1][0:2], ["paper-0001", "304"])
        self.assertEqual(csv_name, "zotero_results.csv")

    def test_consumption_resolves_a_request_moved_to_archive(self) -> None:
        from paper_automation.zotero_bridge import (
            consume_bridge_batch,
            get_bridge_paths,
            queue_bridge_jobs,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bridge_root = root / "bridge"
            run_dir = self._run(root / "runs")
            bridge = queue_bridge_jobs(run_dir, library_id=1, bridge_root=bridge_root)
            job = bridge.jobs[0]
            paths = get_bridge_paths(bridge_root)
            job.request_path.replace(paths.archive / job.request_path.name)
            job.result_path.write_text(
                json.dumps(bridge_result(job, [{
                    "task_id": "paper-0001",
                    "zotero_item_id": "",
                    "attachment_path": "",
                    "status": "no_pdf",
                    "reason": "fixture",
                }])),
                encoding="utf-8",
            )
            selected = consume_bridge_batch(bridge)
            selected_exists = selected.is_file()

        self.assertTrue(selected_exists)

    def test_missing_second_chunk_never_publishes_partial_csv(self) -> None:
        from paper_automation.zotero_bridge import consume_bridge_batch, queue_bridge_jobs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = self._run(root / "runs", fallback_count=101)
            bridge = queue_bridge_jobs(run_dir, library_id=1, bridge_root=root / "bridge")
            first, second = bridge.jobs
            first.result_path.write_text(
                json.dumps(bridge_result(first, [
                    {
                        "task_id": f"paper-{number:04d}",
                        "zotero_item_id": "",
                        "attachment_path": "",
                        "status": "no_pdf",
                        "reason": "fixture",
                    }
                    for number in range(1, 101)
                ])),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "^bridge_result_missing$"):
                consume_bridge_batch(bridge)
            partial_exists = (run_dir / "working" / "zotero_results.csv").exists()
            second.result_path.write_text(
                json.dumps(bridge_result(second, [{
                    "task_id": "paper-0101",
                    "zotero_item_id": "",
                    "attachment_path": "",
                    "status": "no_pdf",
                    "reason": "fixture",
                }])),
                encoding="utf-8",
            )
            selected = consume_bridge_batch(bridge)
            line_count = len(selected.read_text(encoding="utf-8-sig").splitlines())

        self.assertFalse(partial_exists)
        self.assertEqual(line_count, 102)

    def test_result_unknown_field_and_existing_canonical_fail_closed(self) -> None:
        from paper_automation.zotero_bridge import consume_bridge_batch, queue_bridge_jobs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = self._run(root / "runs")
            canonical = run_dir / "working" / "zotero_results.csv"
            canonical.write_bytes(b"original")
            bridge = queue_bridge_jobs(run_dir, bridge_root=root / "bridge", library_id=1)
            job = bridge.jobs[0]
            result = bridge_result(job, [{
                "task_id": "paper-0001",
                "zotero_item_id": "",
                "attachment_path": "",
                "status": "no_pdf",
                "reason": "fixture",
            }])
            result["unexpected"] = True
            job.result_path.write_text(json.dumps(result), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "^bridge_result_fields_invalid$"):
                consume_bridge_batch(bridge)
            canonical_bytes = canonical.read_bytes()

        self.assertEqual(canonical_bytes, b"original")

    def test_existing_canonical_is_preserved_and_valid_result_uses_retry_csv(self) -> None:
        from paper_automation.zotero_bridge import consume_bridge_batch, queue_bridge_jobs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = self._run(root / "runs")
            canonical = run_dir / "working" / "zotero_results.csv"
            canonical.write_bytes(b"original")
            bridge = queue_bridge_jobs(run_dir, bridge_root=root / "bridge", library_id=1)
            job = bridge.jobs[0]
            job.result_path.write_text(
                json.dumps(bridge_result(job, [{
                    "task_id": "paper-0001",
                    "zotero_item_id": "",
                    "attachment_path": "",
                    "status": "user_cancelled",
                    "reason": "fixture",
                }])),
                encoding="utf-8",
            )
            selected = consume_bridge_batch(
                bridge,
                now=datetime(2026, 7, 11, 9, 8, tzinfo=timezone.utc),
            )
            canonical_bytes = canonical.read_bytes()
            selected_name = selected.name

        self.assertEqual(canonical_bytes, b"original")
        self.assertEqual(selected_name, "zotero_results_retry_20260711_090800.csv")

    def test_result_csv_is_invisible_until_atomic_publish(self) -> None:
        from paper_automation.zotero_bridge import consume_bridge_batch, queue_bridge_jobs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = self._run(root / "runs")
            canonical = run_dir / "working" / "zotero_results.csv"
            bridge = queue_bridge_jobs(run_dir, bridge_root=root / "bridge", library_id=1)
            job = bridge.jobs[0]
            job.result_path.write_text(
                json.dumps(bridge_result(job, [{
                    "task_id": "paper-0001",
                    "zotero_item_id": "",
                    "attachment_path": "",
                    "status": "no_pdf",
                    "reason": "fixture",
                }])),
                encoding="utf-8",
            )
            entered_publish = threading.Event()
            allow_publish = threading.Event()
            real_link = os.link

            def delayed_link(source, destination):
                if Path(destination) == canonical:
                    entered_publish.set()
                    allow_publish.wait(timeout=5)
                return real_link(source, destination)

            with patch("paper_automation.zotero_bridge.os.link", side_effect=delayed_link):
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(consume_bridge_batch, bridge)
                    try:
                        self.assertTrue(entered_publish.wait(timeout=5))
                        visible_before_publish = canonical.exists()
                    finally:
                        allow_publish.set()
                    selected = future.result(timeout=5)
            records = selected.read_text(encoding="utf-8-sig").splitlines()
            temporary = list(run_dir.rglob("*.tmp"))

        self.assertFalse(visible_before_publish)
        self.assertEqual(len(records), 2)
        self.assertEqual(temporary, [])

    def test_bridge_handoff_defers_malicious_attachment_path_to_finalizer(self) -> None:
        from paper_automation.batch_workflow import finalize_batch, load_batch_state
        from paper_automation.zotero_bridge import consume_bridge_batch, queue_bridge_jobs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = self._run(root / "runs")
            bridge = queue_bridge_jobs(run_dir, bridge_root=root / "bridge", library_id=1)
            job = bridge.jobs[0]
            job.result_path.write_text(
                json.dumps(bridge_result(job, [{
                    "task_id": "paper-0001",
                    "zotero_item_id": "304",
                    "attachment_path": "https://example.invalid/paper.pdf",
                    "status": "downloaded",
                    "reason": "fixture",
                }])),
                encoding="utf-8",
            )
            selected = consume_bridge_batch(bridge)
            finalize_batch(run_dir, selected)
            state = load_batch_state(run_dir)

        self.assertEqual(state["rows"][0]["status"], "not_pdf_response")
        self.assertEqual(state["rows"][0]["file"], "")


class ZoteroBridgeOrchestrationTests(ZoteroBridgeRequestTests):
    def test_run_returns_waiting_without_requeue(self) -> None:
        from paper_automation.zotero_bridge import run_zotero_bridge

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bridge_root = root / "bridge"
            run_dir = self._run(root / "runs", fallback_count=101)
            first = run_zotero_bridge(run_dir, bridge_root=bridge_root, wait_seconds=0)
            second = run_zotero_bridge(run_dir, bridge_root=bridge_root, wait_seconds=0)
            first_ids = [job.job_id for job in first.bridge.jobs] if first.bridge else []
            second_ids = [job.job_id for job in second.bridge.jobs] if second.bridge else []
            published_count = len(list((bridge_root / "inbox").glob("*.json")))

        self.assertEqual(first.status, "awaiting_confirmation")
        self.assertEqual(second.status, "awaiting_confirmation")
        self.assertEqual(second_ids, first_ids)
        self.assertEqual(published_count, 2)

    def test_run_consumes_result_and_finalizes_once(self) -> None:
        from paper_automation.zotero_bridge import run_zotero_bridge

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = self._run(root / "runs", fallback_count=101)
            bridge_root = root / "bridge"
            queued = run_zotero_bridge(run_dir, bridge_root=bridge_root, wait_seconds=0)
            self.assertIsNotNone(queued.bridge)
            for job in queued.bridge.jobs:
                request = json.loads(job.request_path.read_text(encoding="utf-8"))
                job.result_path.write_text(
                    json.dumps(bridge_result(job, [
                        {
                            "task_id": item["task_id"],
                            "zotero_item_id": "",
                            "attachment_path": "",
                            "status": "no_pdf",
                            "reason": "fixture",
                        }
                        for item in request["items"]
                    ])),
                    encoding="utf-8",
                )
            with patch("paper_automation.zotero_bridge.finalize_batch") as finalize:
                outcome = run_zotero_bridge(
                    run_dir,
                    bridge_root=bridge_root,
                    wait_seconds=1,
                )
            zotero_results = outcome.zotero_results

        self.assertEqual(outcome.status, "finalized")
        self.assertIsNotNone(zotero_results)
        finalize.assert_called_once_with(run_dir.resolve(), zotero_results)
        self.assertIsNotNone(outcome.bridge)
        self.assertEqual(len(outcome.bridge.jobs), 2)

    def test_waiting_run_consumes_request_moved_to_archive_after_queueing(self) -> None:
        from paper_automation.zotero_bridge import run_zotero_bridge

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bridge_root = root / "bridge"
            run_dir = self._run(root / "runs")
            published = []

            def publish_result_after_queue(_seconds) -> None:
                if published:
                    return
                request_path = next((bridge_root / "inbox").glob("*.json"))
                request = json.loads(request_path.read_text(encoding="utf-8"))
                request_path.replace(bridge_root / "archive" / request_path.name)
                (bridge_root / "outbox" / f"{request['job_id']}.result.json").write_text(
                    json.dumps({
                        "schema_version": 1,
                        "job_id": request["job_id"],
                        "payload_sha256": request["payload_sha256"],
                        "plugin_version": "0.1.0",
                        "zotero_version": "9.0.6",
                        "started_at": "2026-07-11T09:06:00Z",
                        "finished_at": "2026-07-11T09:07:00Z",
                        "rows": [{
                            "task_id": "paper-0001",
                            "zotero_item_id": "",
                            "attachment_path": "",
                            "status": "no_pdf",
                            "reason": "fixture",
                        }],
                    }),
                    encoding="utf-8",
                )
                published.append(True)

            with patch(
                "paper_automation.zotero_bridge.time.sleep",
                side_effect=publish_result_after_queue,
            ):
                outcome = run_zotero_bridge(
                    run_dir,
                    bridge_root=bridge_root,
                    wait_seconds=1,
                    poll_seconds=0.01,
                )

        self.assertEqual(outcome.status, "finalized")
        self.assertEqual(published, [True])

    def test_no_fallback_writes_current_reports_without_creating_a_job(self) -> None:
        from paper_automation.batch_workflow import (
            load_batch_state,
            paths_from_run_dir,
            result_from_state,
        )
        from paper_automation.zotero_bridge import run_zotero_bridge

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bridge_root = root / "bridge"
            run_dir = self._run(root / "runs", fallback_count=0)
            paths = paths_from_run_dir(run_dir)
            expected = result_from_state(paths, load_batch_state(run_dir))
            outcome = run_zotero_bridge(run_dir, bridge_root=bridge_root, wait_seconds=0)
            report_exists = (paths.reports / "final_manifest.csv").is_file()
            bridge_exists = bridge_root.exists()

        self.assertEqual(outcome.status, "no_fallback")
        self.assertIsNone(outcome.bridge)
        self.assertIsNone(outcome.zotero_results)
        self.assertEqual(outcome.batch_result, expected)
        self.assertTrue(report_exists)
        self.assertFalse(bridge_exists)

    def test_empty_fallback_cannot_bypass_pending_state_rows(self) -> None:
        from paper_automation.batch_workflow import NORMALIZED_FIELDS
        from paper_automation.zotero_bridge import run_zotero_bridge

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = self._run(root / "runs", fallback_count=1)
            fallback = run_dir / "working" / "zotero_fallback.csv"
            fallback.write_text(
                ",".join(NORMALIZED_FIELDS) + "\n",
                encoding="utf-8-sig",
            )
            with self.assertRaisesRegex(ValueError, "^bridge_fallback_state_mismatch$"):
                run_zotero_bridge(run_dir, bridge_root=root / "bridge", wait_seconds=0)

    def test_plugin_failure_results_produce_recoverable_final_report(self) -> None:
        from paper_automation.batch_workflow import load_batch_state
        from paper_automation.zotero_bridge import run_zotero_bridge

        statuses = [
            "user_cancelled",
            "job_expired",
            "job_id_conflict",
            "plugin_error",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = self._run(root / "runs", fallback_count=len(statuses))
            bridge_root = root / "bridge"
            queued = run_zotero_bridge(run_dir, bridge_root=bridge_root, wait_seconds=0)
            self.assertIsNotNone(queued.bridge)
            job = queued.bridge.jobs[0]
            request = json.loads(job.request_path.read_text(encoding="utf-8"))
            job.result_path.write_text(
                json.dumps(bridge_result(job, [
                    {
                        "task_id": item["task_id"],
                        "zotero_item_id": "",
                        "attachment_path": "",
                        "status": status,
                        "reason": "fixture",
                    }
                    for item, status in zip(request["items"], statuses, strict=True)
                ])),
                encoding="utf-8",
            )
            outcome = run_zotero_bridge(run_dir, bridge_root=bridge_root, wait_seconds=0)
            state = load_batch_state(run_dir)
            report_exists = (run_dir / "reports" / "final_manifest.csv").is_file()

        self.assertEqual(outcome.status, "finalized")
        self.assertIsNotNone(outcome.batch_result)
        self.assertEqual(outcome.batch_result.failed_count, len(statuses))
        self.assertEqual([row["status"] for row in state["rows"]], statuses)
        self.assertTrue(report_exists)

    def test_completed_failure_batch_archives_manifest_and_requeues_remaining_rows(self) -> None:
        from paper_automation.zotero_bridge import run_zotero_bridge

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = self._run(root / "runs")
            bridge_root = root / "bridge"
            first = run_zotero_bridge(run_dir, bridge_root=bridge_root, wait_seconds=0)
            self.assertIsNotNone(first.bridge)
            first_job = first.bridge.jobs[0]
            first_job.result_path.write_text(
                json.dumps(bridge_result(first_job, [{
                    "task_id": "paper-0001",
                    "zotero_item_id": "",
                    "attachment_path": "",
                    "status": "plugin_error",
                    "reason": "fixture",
                }])),
                encoding="utf-8",
            )
            finalized = run_zotero_bridge(run_dir, bridge_root=bridge_root, wait_seconds=0)
            archived_manifest_absent = not (
                run_dir / "working" / "zotero_bridge_jobs.json"
            ).exists()
            history = list((run_dir / "working" / "zotero_bridge_history").glob("*.json"))
            resumed = run_zotero_bridge(run_dir, bridge_root=bridge_root, wait_seconds=0)
            new_manifest_exists = (run_dir / "working" / "zotero_bridge_jobs.json").exists()
            resumed_job = resumed.bridge.jobs[0] if resumed.bridge else None

        self.assertEqual(finalized.status, "finalized")
        self.assertEqual(resumed.status, "awaiting_confirmation")
        self.assertTrue(archived_manifest_absent)
        self.assertTrue(new_manifest_exists)
        self.assertEqual(len(history), 1)
        self.assertIsNotNone(resumed_job)
        self.assertNotEqual(resumed_job.job_id, first_job.job_id)

    def test_wait_seconds_rejects_outside_range_and_boolean_values(self) -> None:
        from paper_automation.zotero_bridge import run_zotero_bridge

        with tempfile.TemporaryDirectory() as tmp:
            missing_run = Path(tmp) / "missing"
            for seconds in (-1, 86401, True):
                with self.subTest(seconds=seconds):
                    with self.assertRaisesRegex(ValueError, "^bridge_wait_seconds_invalid$"):
                        run_zotero_bridge(missing_run, wait_seconds=seconds)


if __name__ == "__main__":
    unittest.main()
