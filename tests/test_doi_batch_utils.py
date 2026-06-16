from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class DoiBatchUtilsTests(unittest.TestCase):
    def test_preview_reads_csv_with_chinese_doi_alias_and_cleans_url(self) -> None:
        from doi_batch_utils import preview_doi_input

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "papers.csv"
            with path.open("w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=["标题", "DOI号"])
                writer.writeheader()
                writer.writerow({
                    "标题": "Example paper",
                    "DOI号": "https://doi.org/10.1016/j.actamat.2024.119999",
                })

            preview = preview_doi_input(input_path=path, limit=10)

        self.assertEqual(preview.total_doi, 1)
        self.assertEqual(preview.rows[0].doi, "10.1016/j.actamat.2024.119999")
        self.assertEqual(preview.rows[0].title, "Example paper")
        self.assertEqual(preview.doi_column, "DOI号")

    def test_load_records_preserves_empty_and_duplicate_rows_for_reporting(self) -> None:
        from doi_batch_utils import load_doi_records

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "papers.csv"
            with path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["title", "doi"])
                writer.writeheader()
                writer.writerow({"title": "A", "doi": "doi:10.1016/j.scriptamat.2024.115000"})
                writer.writerow({"title": "B", "doi": ""})
                writer.writerow({"title": "C", "doi": "10.1016/j.scriptamat.2024.115000"})

            records = load_doi_records(path)

        self.assertEqual([record.row_number for record in records], [2, 3, 4])
        self.assertEqual(records[0].doi, "10.1016/j.scriptamat.2024.115000")
        self.assertEqual(records[1].doi, "")
        self.assertEqual(records[2].doi, "10.1016/j.scriptamat.2024.115000")

    def test_preview_reads_gbk_csv_exported_from_excel(self) -> None:
        from doi_batch_utils import preview_doi_input

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gbk.csv"
            with path.open("w", newline="", encoding="gbk") as f:
                writer = csv.DictWriter(f, fieldnames=["题名", "doi"])
                writer.writeheader()
                writer.writerow({"题名": "中文标题", "doi": "10.1016/j.jallcom.2025.177000"})

            preview = preview_doi_input(input_path=path)

        self.assertEqual(preview.encoding, "gb18030")
        self.assertEqual(preview.rows[0].title, "中文标题")

    def test_preview_counts_only_valid_doi_values_in_tsv(self) -> None:
        from doi_batch_utils import preview_doi_input

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "papers.tsv"
            path.write_text(
                "title\tdoi\n"
                "A\thttps://doi.org/10.1016/j.actamat.2024.119999\n"
                "B\tbad\n",
                encoding="utf-8",
            )

            preview = preview_doi_input(input_path=path, doi_column="doi")

        self.assertEqual(preview.total_rows, 2)
        self.assertEqual(preview.total_doi, 1)
        self.assertEqual(preview.rows[0].title, "A")
        self.assertEqual(preview.rows[0].doi, "10.1016/j.actamat.2024.119999")

    def test_load_records_reads_requested_xlsx_sheet(self) -> None:
        try:
            from openpyxl import Workbook
        except ImportError:
            self.skipTest("openpyxl is not installed")

        from doi_batch_utils import load_doi_records

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "papers.xlsx"
            wb = Workbook()
            first = wb.active
            first.title = "Wrong"
            first.append(["title", "doi"])
            first.append(["Wrong sheet", "10.1016/j.wrong.2024.1"])
            target = wb.create_sheet("Target")
            target.append(["标题", "DOI"])
            target.append(["Right sheet", "10.1016/j.right.2024.2"])
            wb.save(path)

            records = load_doi_records(path, sheet_name="Target")

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].title, "Right sheet")
        self.assertEqual(records[0].doi, "10.1016/j.right.2024.2")

    def test_preview_extracts_dois_from_pasted_text(self) -> None:
        from doi_batch_utils import preview_doi_input

        preview = preview_doi_input(
            pasted_text="first DOI: 10.1016/j.matchar.2024.113000.\nno doi\n"
            "https://doi.org/10.1016/j.commatsci.2024.112000",
            limit=10,
        )

        self.assertEqual(preview.total_doi, 2)
        self.assertEqual(preview.rows[0].row_number, 1)
        self.assertEqual(preview.rows[0].doi, "10.1016/j.matchar.2024.113000")
        self.assertEqual(preview.rows[1].row_number, 3)


class CookieCheckTests(unittest.TestCase):
    def test_check_cookie_json_accepts_cookie_editor_list(self) -> None:
        from doi_batch_utils import check_cookie_json

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cookies.json"
            path.write_text(
                json.dumps([
                    {
                        "domain": ".sciencedirect.com",
                        "name": "SDMSESSION",
                        "value": "secret-value",
                    }
                ]),
                encoding="utf-8",
            )

            result = check_cookie_json(path)

        self.assertTrue(result.exists)
        self.assertTrue(result.readable)
        self.assertTrue(result.has_sciencedirect_cookie)
        self.assertEqual(result.cookie_count, 1)
        self.assertNotIn("secret-value", result.message)

    def test_check_cookie_json_accepts_wrapped_cookies_shape(self) -> None:
        from doi_batch_utils import check_cookie_json

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cookies.json"
            path.write_text(
                json.dumps({"cookies": [{"domain": ".elsevier.com", "name": "EUID", "value": "secret"}]}),
                encoding="utf-8",
            )

            result = check_cookie_json(path)

        self.assertTrue(result.is_usable)
        self.assertTrue(result.has_sciencedirect_cookie)

    def test_check_cookie_json_reports_invalid_json(self) -> None:
        from doi_batch_utils import check_cookie_json

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("{not json", encoding="utf-8")

            result = check_cookie_json(path)

        self.assertFalse(result.is_usable)
        self.assertIn("JSON", result.message)

    def test_check_cookie_json_reports_empty_cookie_file(self) -> None:
        from doi_batch_utils import check_cookie_json

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.json"
            path.write_text("[]", encoding="utf-8")

            result = check_cookie_json(path)

        self.assertFalse(result.is_usable)
        self.assertEqual(result.cookie_count, 0)


class ReportTests(unittest.TestCase):
    def test_writes_run_summary_and_pdf_download_report_without_cookie_values(self) -> None:
        from doi_batch_utils import (
            PdfDownloadRecord,
            RunSummary,
            write_pdf_download_report,
            write_run_summary,
        )

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            summary = RunSummary(
                input_path="papers.csv",
                output_dir=str(out),
                total_doi=3,
                resolved_count=1,
                failure_reasons={"重复 DOI，已跳过": 1, "非 ScienceDirect 链接": 1},
                pdf_success=1,
                pdf_failed=1,
                pdf_skipped=0,
                resolved_path=str(out / "doi_batch_resolved.xlsx"),
                failed_path=str(out / "doi_batch_failed.csv"),
                pdf_report_path=str(out / "pdf_download_report.csv"),
                cookie_message="已识别 5 个 Cookie，其中 2 个与 ScienceDirect/Elsevier 相关",
            )
            summary_path = write_run_summary(summary)
            report_path = write_pdf_download_report(
                [
                    PdfDownloadRecord(
                        doi="10.1016/example",
                        pii="S123",
                        title="Paper",
                        status="success",
                        file="001_Paper.pdf",
                        reason="",
                    )
                ],
                out,
            )

            summary_text = summary_path.read_text(encoding="utf-8")
            report_text = report_path.read_text(encoding="utf-8-sig")

        self.assertIn("DOI 批量任务报告", summary_text)
        self.assertIn("重复 DOI，已跳过: 1", summary_text)
        self.assertIn("10.1016/example", report_text)


class UiBehaviorTests(unittest.TestCase):
    def test_ui_defaults_to_doi_batch_cookie_json_workflow(self) -> None:
        try:
            from tkinter import Tk
        except Exception as exc:
            self.skipTest(f"tkinter unavailable: {exc}")

        from paper_scraper_ui import PaperScraperUI

        try:
            root = Tk()
        except Exception as exc:
            self.skipTest(f"cannot start Tk root: {exc}")
        root.withdraw()
        try:
            app = PaperScraperUI(root)
            self.assertEqual(app.mode_var.get(), "doi_batch")
            self.assertFalse(app.browser_cookies_var.get())
            self.assertTrue(app.download_pdf_var.get())
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
