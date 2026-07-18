"""Unit tests for failure routing, DOI-only intake filters, and retry whitelist."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from paper_automation.batch_stages import BatchOptions
from paper_automation.batch_workflow import create_batch_paths, normalize_input, retry_failed_batch
from paper_automation.failure_routing import (
    classify_failure_next_hop,
    is_noise_title_line,
    is_retry_eligible,
    is_zotero_eligible,
)


class FailureRoutingTests(unittest.TestCase):
    def test_zotero_requires_doi_and_excludes_metadata_uncertain(self) -> None:
        self.assertFalse(is_zotero_eligible("unsupported_publisher", doi=""))
        self.assertTrue(is_zotero_eligible("unsupported_publisher", doi="10.1000/x"))
        self.assertFalse(is_zotero_eligible("metadata_uncertain", doi="10.1000/x"))
        self.assertTrue(is_zotero_eligible("not_pdf_response", "network_pdf_not_captured", doi="10.1000/x"))

    def test_retry_whitelist_excludes_unsupported(self) -> None:
        self.assertFalse(is_retry_eligible("unsupported_publisher", "unknown_publisher"))
        self.assertTrue(is_retry_eligible("not_pdf_response", "network_pdf_not_captured"))
        self.assertTrue(is_retry_eligible("error", "urlopen error WinError 10061"))
        self.assertTrue(is_retry_eligible("unsupported_publisher", retry_all=True))

    def test_noise_title_lines(self) -> None:
        self.assertTrue(is_noise_title_line("# A · 必补"))
        self.assertTrue(is_noise_title_line("题名检索：Scattering by deformed swollen gels"))
        self.assertTrue(is_noise_title_line("待补文献（题名 + DOI）"))
        self.assertFalse(is_noise_title_line("Deformation of oriented polyethylene"))

    def test_classify_next_hop(self) -> None:
        self.assertEqual(classify_failure_next_hop("institutional_downloaded"), "success")
        self.assertEqual(classify_failure_next_hop("metadata_uncertain"), "review")
        self.assertEqual(
            classify_failure_next_hop("not_pdf_response", "network", doi="10.1000/x"),
            "retry",
        )
        self.assertEqual(
            classify_failure_next_hop("unsupported_publisher", doi="10.1000/x"),
            "zotero",
        )


class IntakeFilterTests(unittest.TestCase):
    def test_markdown_with_sections_keeps_only_dois_by_default(self) -> None:
        text = """# 待补文献（题名 + DOI）

## A · 必补

1. Full-pattern analysis of two-dimensional small-angle scattering
   https://doi.org/10.1016/S0032-3861(96)00631-3

2. Structural implications of the elliptical form
   https://doi.org/10.1021/ma9911501

题名检索：Scattering by deformed swollen gels butterfly
"""
        with tempfile.TemporaryDirectory() as tmp:
            paths = create_batch_paths(Path(tmp), run_name="md-filter")
            rows = normalize_input(
                input_text=text,
                input_path=None,
                paths=paths,
                options=BatchOptions(),
            )
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            {row["doi"] for row in rows},
            {"10.1016/s0032-3861(96)00631-3", "10.1021/ma9911501"},
        )
        self.assertTrue(all(row["status"] == "pending" for row in rows))

    def test_title_only_without_resolve_flag_raises_empty_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = create_batch_paths(Path(tmp), run_name="title-only")
            with self.assertRaises(ValueError) as ctx:
                normalize_input(
                    input_text="Titanium",
                    input_path=None,
                    paths=paths,
                    options=BatchOptions(),
                )
        self.assertEqual(str(ctx.exception), "empty_input")


class RetryFailedWhitelistTests(unittest.TestCase):
    def test_retry_failed_skips_unsupported_by_default(self) -> None:
        from paper_automation.batch_workflow import save_batch_state, batch_state_lock

        with tempfile.TemporaryDirectory() as tmp:
            paths = create_batch_paths(Path(tmp), run_name="retry-filter")
            state = {
                "version": 1,
                "run_dir": str(paths.root),
                "manual_retry_used": True,
                "options": {
                    "email": "",
                    "cookies": "",
                    "browser_exe": "",
                    "login_wait_seconds": 0,
                    "debug_port": 9333,
                    "throttle_seconds": 1.0,
                    "skip_manual_retry": True,
                    "download_supplements": True,
                    "smart_route": True,
                    "session_break_seconds": 60.0,
                    "session_break_every": 8,
                    "resolve_title_metadata": False,
                    "circuit_breaker_threshold": 3,
                    "auto_oa_recovery": False,
                },
                "rows": [
                    {
                        "task_id": "paper-0001",
                        "source_index": "1",
                        "input_doi": "10.1143/jpsj.58.3065",
                        "input_title": "",
                        "doi": "10.1143/jpsj.58.3065",
                        "title": "Onuki",
                        "authors": "",
                        "journal": "",
                        "year": "",
                        "publisher": "",
                        "status": "unsupported_publisher",
                        "source": "non_elsevier",
                        "file": "",
                        "reason": "unknown_publisher",
                    },
                    {
                        "task_id": "paper-0002",
                        "source_index": "2",
                        "input_doi": "10.1000/net",
                        "input_title": "",
                        "doi": "10.1000/net",
                        "title": "Network fail",
                        "authors": "",
                        "journal": "",
                        "year": "",
                        "publisher": "",
                        "status": "not_pdf_response",
                        "source": "non_elsevier",
                        "file": "",
                        "reason": "network_pdf_not_captured",
                    },
                ],
            }
            with batch_state_lock(paths.root):
                save_batch_state(paths, state)

            class Gateway:
                def __init__(self) -> None:
                    self.seen: list[str] = []

                def run_institutional_only(self, rows, paths, options, *, on_updates=None):
                    self.seen = [row["task_id"] for row in rows]
                    updates = []
                    for row in rows:
                        updates.append(
                            {
                                **row,
                                "status": "institutional_downloaded",
                                "file": "x.pdf",
                                "reason": "",
                                "source": "non_elsevier",
                            }
                        )
                    if on_updates:
                        on_updates(updates)
                    return updates

            gateway = Gateway()
            retry_failed_batch(paths.root, gateway=gateway, skip_oa=True)
            self.assertEqual(gateway.seen, ["paper-0002"])


if __name__ == "__main__":
    unittest.main()
