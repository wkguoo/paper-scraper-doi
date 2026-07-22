from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _one_page_pdf(label: str) -> bytes:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.add_metadata({"/Subject": label})
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class OfflineBatchGateway:
    def run_initial(self, rows, _paths, _options):
        return [
            {
                **rows[0],
                "status": "oa_downloaded",
                "source": "oa",
                "file": rows[0]["fixture_pdf"],
                "reason": "",
            },
            *[
                {
                    **row,
                    "status": "no_open_pdf",
                    "source": "oa",
                    "file": "",
                    "reason": "no_legal_open_pdf",
                }
                for row in rows[1:]
            ],
        ]

    def run_retry(self, rows, _paths, _options):
        return [dict(row) for row in rows]


class AllFallbackGateway:
    def run_initial(self, rows, _paths, _options):
        return [
            {
                **row,
                "status": "no_open_pdf",
                "source": "oa",
                "file": "",
                "reason": "no_legal_open_pdf",
            }
            for row in rows
        ]

    def run_retry(self, rows, _paths, _options):
        return [dict(row) for row in rows]


def plugin_result(job, rows: list[dict[str, str]]) -> dict:
    return {
        "schema_version": 1,
        "job_id": job.job_id,
        "payload_sha256": job.payload_sha256,
        "plugin_version": "0.1.0-test",
        "zotero_version": "9.0.6-test",
        "started_at": "2026-07-11T09:06:00Z",
        "finished_at": "2026-07-11T09:07:00Z",
        "rows": rows,
    }


class ZoteroBridgeIntegrationTests(unittest.TestCase):
    @staticmethod
    def _start_fallback_run(root: Path, count: int = 2):
        from paper_automation.batch_workflow import start_batch

        normalized = [
            {
                "task_id": f"paper-{number:04d}",
                "source_index": str(number),
                "input_doi": f"10.1000/fallback-{number}",
                "doi": f"10.1000/fallback-{number}",
                "title": f"Fallback Paper {number}",
            }
            for number in range(1, count + 1)
        ]
        return start_batch(
            input_text="fixture",
            input_path=None,
            output_root=root / "runs",
            gateway=AllFallbackGateway(),
            normalizer=lambda **_kwargs: normalized,
            now=datetime(2026, 7, 11, 9, 0, 0),
        )

    def test_bridge_result_finalizes_project_and_zotero_pdfs_without_source_mutation(self) -> None:
        from paper_automation.batch_workflow import load_batch_state, start_batch
        from paper_automation.zotero_bridge import run_zotero_bridge

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_pdf = root / "project-source.pdf"
            project_payload = _one_page_pdf("project integration fixture")
            project_pdf.write_bytes(project_payload)
            zotero_pdf = root / "zotero-source.pdf"
            zotero_payload = _one_page_pdf("zotero integration fixture")
            zotero_pdf.write_bytes(zotero_payload)
            source_bytes = {
                project_pdf: project_pdf.read_bytes(),
                zotero_pdf: zotero_pdf.read_bytes(),
            }
            normalized = [
                {
                    "task_id": "paper-0001",
                    "source_index": "1",
                    "input_doi": "10.1000/project",
                    "doi": "10.1000/project",
                    "title": "Project PDF",
                    "fixture_pdf": str(project_pdf),
                },
                {
                    "task_id": "paper-0002",
                    "source_index": "2",
                    "input_doi": "10.1000/zotero",
                    "doi": "10.1000/zotero",
                    "title": "Zotero PDF",
                },
                {
                    "task_id": "paper-0003",
                    "source_index": "3",
                    "input_doi": "10.1000/missing",
                    "doi": "10.1000/missing",
                    "title": "No PDF",
                },
            ]
            started = start_batch(
                input_text="fixture",
                input_path=None,
                output_root=root / "runs",
                gateway=OfflineBatchGateway(),
                normalizer=lambda **_kwargs: normalized,
                now=datetime(2026, 7, 11, 9, 0, 0),
            )
            bridge_root = root / "bridge"

            queued = run_zotero_bridge(
                started.paths.root,
                bridge_root=bridge_root,
                wait_seconds=0,
            )
            self.assertEqual(queued.status, "awaiting_confirmation")
            self.assertIsNotNone(queued.bridge)
            self.assertEqual(len(queued.bridge.jobs), 1)
            job = queued.bridge.jobs[0]
            request = json.loads(job.request_path.read_text(encoding="utf-8"))
            self.assertEqual(
                [item["task_id"] for item in request["items"]],
                ["paper-0002", "paper-0003"],
            )
            job.result_path.write_text(
                json.dumps(
                    plugin_result(job, [
                        {
                            "task_id": "paper-0002",
                            "zotero_item_id": "304",
                            "attachment_path": str(zotero_pdf.resolve()),
                            "status": "existing_pdf",
                            "reason": "",
                        },
                        {
                            "task_id": "paper-0003",
                            "zotero_item_id": "",
                            "attachment_path": "",
                            "status": "no_pdf",
                            "reason": "no_available_pdf",
                        },
                    ]),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            finalized = run_zotero_bridge(
                started.paths.root,
                bridge_root=bridge_root,
                wait_seconds=0,
            )
            state = load_batch_state(started.paths.root)
            delivered = {path.name: path.read_bytes() for path in started.paths.pdfs.glob("*.pdf")}
            state_before_rerun = started.paths.state.read_bytes()
            csv_reports_before_rerun = {
                path.name: path.read_bytes() for path in started.paths.reports.glob("*.csv")
            }

            rerun = run_zotero_bridge(
                started.paths.root,
                bridge_root=bridge_root,
                wait_seconds=0,
            )

            self.assertEqual(finalized.status, "finalized")
            self.assertIsNotNone(finalized.batch_result)
            self.assertEqual(finalized.batch_result.success_count, 2)
            self.assertEqual(finalized.batch_result.failed_count, 1)
            self.assertEqual(len({row["task_id"] for row in state["rows"]}), 3)
            self.assertEqual(len(delivered), 2)
            self.assertEqual(
                {hashlib.sha256(payload).hexdigest() for payload in delivered.values()},
                {
                    hashlib.sha256(project_payload).hexdigest(),
                    hashlib.sha256(zotero_payload).hexdigest(),
                },
            )
            self.assertTrue((started.paths.reports / "final_manifest.csv").is_file())
            self.assertTrue((started.paths.reports / "final_manifest.xlsx").is_file())
            with (started.paths.reports / "final_manifest.csv").open(
                "r", newline="", encoding="utf-8-sig",
            ) as handle:
                final_rows = list(csv.DictReader(handle))
            self.assertEqual([row["task_id"] for row in final_rows], [
                "paper-0001", "paper-0002", "paper-0003",
            ])
            self.assertEqual(rerun.status, "awaiting_confirmation")
            self.assertEqual(started.paths.state.read_bytes(), state_before_rerun)
            self.assertEqual(
                {path.name: path.read_bytes() for path in started.paths.reports.glob("*.csv")},
                csv_reports_before_rerun,
            )
            self.assertEqual(
                {path.name: path.read_bytes() for path in started.paths.pdfs.glob("*.pdf")},
                delivered,
            )
            for source, payload in source_bytes.items():
                self.assertEqual(source.read_bytes(), payload)

    def test_invalid_plugin_results_leave_batch_state_and_final_pdfs_unchanged(self) -> None:
        from paper_automation.zotero_bridge import run_zotero_bridge

        cases = {
            "mismatched_hash": "bridge_result_identity_invalid",
            "extra_field": "bridge_result_fields_invalid",
            "duplicate_task": "bridge_result_task_duplicate",
            "invalid_local_path": "bridge_result_row_value_invalid",
        }
        for case, expected_error in cases.items():
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                started = self._start_fallback_run(root)
                bridge_root = root / "bridge"
                queued = run_zotero_bridge(
                    started.paths.root,
                    bridge_root=bridge_root,
                    wait_seconds=0,
                )
                self.assertIsNotNone(queued.bridge)
                job = queued.bridge.jobs[0]
                request = json.loads(job.request_path.read_text(encoding="utf-8"))
                rows = [
                    {
                        "task_id": item["task_id"],
                        "zotero_item_id": "",
                        "attachment_path": "",
                        "status": "no_pdf",
                        "reason": "fixture",
                    }
                    for item in request["items"]
                ]
                result = plugin_result(job, rows)
                if case == "mismatched_hash":
                    result["payload_sha256"] = "f" * 64
                elif case == "extra_field":
                    result["unexpected"] = True
                elif case == "duplicate_task":
                    result["rows"][1]["task_id"] = result["rows"][0]["task_id"]
                else:
                    result["rows"][0] = {
                        "task_id": request["items"][0]["task_id"],
                        "zotero_item_id": "304",
                        "attachment_path": "C:\\" + ("x" * 4096),
                        "status": "downloaded",
                        "reason": "",
                    }
                job.result_path.write_text(json.dumps(result), encoding="utf-8")
                state_before = started.paths.state.read_bytes()
                pdfs_before = {
                    path.name: path.read_bytes() for path in started.paths.pdfs.glob("*.pdf")
                }

                with self.assertRaisesRegex(ValueError, f"^{expected_error}$"):
                    run_zotero_bridge(
                        started.paths.root,
                        bridge_root=bridge_root,
                        wait_seconds=0,
                    )

                self.assertEqual(started.paths.state.read_bytes(), state_before)
                self.assertEqual(
                    {path.name: path.read_bytes() for path in started.paths.pdfs.glob("*.pdf")},
                    pdfs_before,
                )

    def test_101_rows_wait_for_both_chunks_then_finalize_once_in_request_order(self) -> None:
        from unittest.mock import patch

        from paper_automation.batch_workflow import finalize_batch
        from paper_automation.zotero_bridge import run_zotero_bridge

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            started = self._start_fallback_run(root, count=101)
            bridge_root = root / "bridge"
            queued = run_zotero_bridge(
                started.paths.root,
                bridge_root=bridge_root,
                wait_seconds=0,
            )
            self.assertIsNotNone(queued.bridge)
            first, second = queued.bridge.jobs
            requests = [
                json.loads(job.request_path.read_text(encoding="utf-8"))
                for job in (first, second)
            ]
            self.assertEqual([request["chunk_index"] for request in requests], [1, 2])
            self.assertEqual([request["chunk_count"] for request in requests], [2, 2])
            self.assertEqual(len(requests[0]["items"]), 100)
            self.assertEqual(len(requests[1]["items"]), 1)
            self.assertEqual(len({request["run_id"] for request in requests}), 1)
            self.assertEqual(len({request["collection_name"] for request in requests}), 1)
            state_before_partial = started.paths.state.read_bytes()
            first.result_path.write_text(
                json.dumps(plugin_result(first, [
                    {
                        "task_id": item["task_id"],
                        "zotero_item_id": "",
                        "attachment_path": "",
                        "status": "no_pdf",
                        "reason": "fixture",
                    }
                    for item in requests[0]["items"]
                ])),
                encoding="utf-8",
            )

            partial = run_zotero_bridge(
                started.paths.root,
                bridge_root=bridge_root,
                wait_seconds=0,
            )

            self.assertEqual(partial.status, "awaiting_confirmation")
            self.assertEqual(started.paths.state.read_bytes(), state_before_partial)
            self.assertFalse(started.paths.zotero_results.exists())
            self.assertEqual(list(started.paths.pdfs.glob("*.pdf")), [])

            second.result_path.write_text(
                json.dumps(plugin_result(second, [{
                    "task_id": requests[1]["items"][0]["task_id"],
                    "zotero_item_id": "",
                    "attachment_path": "",
                    "status": "no_pdf",
                    "reason": "fixture",
                }])),
                encoding="utf-8",
            )
            with patch(
                "paper_automation.zotero_bridge.finalize_batch",
                wraps=finalize_batch,
            ) as finalize:
                completed = run_zotero_bridge(
                    started.paths.root,
                    bridge_root=bridge_root,
                    wait_seconds=0,
                )

            self.assertEqual(completed.status, "finalized")
            self.assertEqual(finalize.call_count, 1)
            self.assertIsNotNone(completed.zotero_results)
            with completed.zotero_results.open("r", newline="", encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(
                [row["task_id"] for row in rows],
                [f"paper-{number:04d}" for number in range(1, 102)],
            )
            self.assertEqual(len({row["task_id"] for row in rows}), 101)
            self.assertEqual(list(started.paths.pdfs.glob("*.pdf")), [])


if __name__ == "__main__":
    unittest.main()
