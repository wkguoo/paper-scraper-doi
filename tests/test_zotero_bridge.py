from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


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


if __name__ == "__main__":
    unittest.main()
