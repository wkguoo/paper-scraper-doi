from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
