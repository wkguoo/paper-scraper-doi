from __future__ import annotations

import csv
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class FakeSuccessBrowserSession:
    browser_name = "Edge"

    def __init__(self, browser_exe: str | None = None, debug_port: int = 9333) -> None:
        self.browser_exe = browser_exe
        self.debug_port = debug_port

    def ensure_ready(self) -> bool:
        return False

    def open_login_page(self, _url: str) -> None:
        return None

    def load_page(self, url: str, wait_seconds: float = 3.0):
        from paper_automation.institutional.models import PageSnapshot

        return PageSnapshot(
            requested_url=url,
            final_url="https://www.nature.com/articles/s41467-020-16791-8",
            html=(
                '<html><head>'
                '<meta name="citation_pdf_url" content="https://www.nature.com/articles/s41467-020-16791-8.pdf">'
                "</head><body>Download PDF</body></html>"
            ),
            text="Download PDF",
        )

    def capture_pdf(self, url: str, fetch_patterns: tuple[str, ...], timeout: int = 45):
        from paper_automation.institutional.models import PdfCaptureResult

        del fetch_patterns, timeout
        return PdfCaptureResult(requested_url=url, pdf_url=url, pdf_bytes=b"%PDF-1.7\nsuccess")


class FakeAuthRequiredBrowserSession:
    browser_name = "Edge"

    def __init__(self, browser_exe: str | None = None, debug_port: int = 9333) -> None:
        self.browser_exe = browser_exe
        self.debug_port = debug_port

    def ensure_ready(self) -> bool:
        return False

    def open_login_page(self, _url: str) -> None:
        return None

    def load_page(self, url: str, wait_seconds: float = 3.0):
        from paper_automation.institutional.models import PageSnapshot

        del wait_seconds
        return PageSnapshot(
            requested_url=url,
            final_url=url,
            html="<html><body>Access through your institution</body></html>",
            text="Access through your institution",
        )

    def capture_pdf(self, url: str, fetch_patterns: tuple[str, ...], timeout: int = 45):
        from paper_automation.institutional.models import PdfCaptureResult

        del fetch_patterns, timeout
        return PdfCaptureResult(requested_url=url, note="network_pdf_not_captured")


class InstitutionalWorkflowTests(unittest.TestCase):
    def test_cli_writes_report_pdf_and_manifest_update_with_fake_browser(self) -> None:
        from institutional_paper_skill import main
        from paper_automation.models import MetadataResult

        def fake_resolve_one(_self: object, candidate: object) -> MetadataResult:
            doi = candidate.doi if hasattr(candidate, "doi") else ""
            title = candidate.title if hasattr(candidate, "title") else ""
            if doi == "10.1038/s41467-020-16791-8":
                return MetadataResult(
                    source_index=1,
                    query_title=title,
                    doi=doi,
                    title="Nature communications paper",
                    journal="Nature Communications",
                    year="2020",
                    publisher="Springer Nature",
                    url="https://www.nature.com/articles/s41467-020-16791-8",
                    source="crossref",
                )
            return MetadataResult(
                source_index=2,
                query_title=title,
                doi=doi,
                title="Science paper",
                journal="Science",
                year="2020",
                publisher="AAAS",
                url="https://www.science.org/doi/10.1126/science.aaz0122",
                source="crossref",
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "papers.csv"
            manifest_path = root / "final_manifest.csv"
            with input_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["doi", "title"])
                writer.writeheader()
                writer.writerow({"doi": "10.1038/s41467-020-16791-8", "title": "Nature communications paper"})
                writer.writerow({"doi": "10.1126/science.aaz0122", "title": "Science paper"})
            with manifest_path.open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=["doi", "title"])
                writer.writeheader()
                writer.writerow({"doi": "10.1038/s41467-020-16791-8", "title": "Nature communications paper"})
                writer.writerow({"doi": "10.1126/science.aaz0122", "title": "Science paper"})

            stdout = io.StringIO()
            with patch("paper_automation.institutional.workflow.MetadataResolver.resolve_one", fake_resolve_one), patch(
                "paper_automation.institutional.workflow.DebugBrowserSession",
                FakeSuccessBrowserSession,
            ), redirect_stdout(stdout):
                exit_code = main(
                    [
                        "--input",
                        str(input_path),
                        "--out",
                        str(root),
                        "--merge-manifest",
                        str(manifest_path),
                    ]
                )

            self.assertEqual(exit_code, 0)
            report_path = root / "non_elsevier_institutional" / "institutional_pdf_download_report.csv"
            summary_path = root / "non_elsevier_institutional" / "run_summary.json"
            merged_manifest_path = root / "non_elsevier_institutional" / "final_manifest_institutional_update.csv"
            pdf_dir = root / "non_elsevier_institutional" / "pdfs"

            self.assertTrue(report_path.exists())
            self.assertTrue(summary_path.exists())
            self.assertTrue(merged_manifest_path.exists())
            self.assertEqual(len(list(pdf_dir.glob("*.pdf"))), 1)

            with report_path.open("r", encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["status"], "pdf_downloaded")
            self.assertEqual(rows[1]["status"], "unsupported_publisher")

            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["downloaded_count"], 1)
            self.assertEqual(summary["status_counts"]["unsupported_publisher"], 1)

            with merged_manifest_path.open("r", encoding="utf-8-sig") as handle:
                merged_rows = list(csv.DictReader(handle))
            self.assertEqual(merged_rows[0]["institutional_status"], "pdf_downloaded")
            self.assertEqual(merged_rows[1]["institutional_status"], "unsupported_publisher")
            self.assertIn("Downloaded PDFs: 1", stdout.getvalue())

    def test_workflow_reports_auth_required(self) -> None:
        from paper_automation.institutional.workflow import run_institutional_workflow
        from paper_automation.models import MetadataResult

        def fake_resolve_one(_self: object, candidate: object) -> MetadataResult:
            doi = candidate.doi if hasattr(candidate, "doi") else ""
            return MetadataResult(
                source_index=1,
                query_title="IUCr paper",
                doi=doi,
                title="IUCr paper",
                journal="Journal of Applied Crystallography",
                year="2015",
                publisher="International Union of Crystallography",
                url="https://journals.iucr.org/j/issues/2015/03/00/ab1234/index.html",
                source="crossref",
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "papers.csv"
            with input_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["doi", "title"])
                writer.writeheader()
                writer.writerow({"doi": "10.1107/s1600576715004306", "title": "IUCr paper"})

            with patch("paper_automation.institutional.workflow.MetadataResolver.resolve_one", fake_resolve_one):
                result = run_institutional_workflow(
                    input_path=input_path,
                    output_dir=root,
                    session_factory=lambda _exe, _port: FakeAuthRequiredBrowserSession(),
                )

            self.assertEqual(result.status_counts["auth_required"], 1)
            with Path(result.report_path).open("r", encoding="utf-8-sig") as handle:
                report_rows = list(csv.DictReader(handle))
            self.assertEqual(report_rows[0]["status"], "auth_required")


if __name__ == "__main__":
    unittest.main()
