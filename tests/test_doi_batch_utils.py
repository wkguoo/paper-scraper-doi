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


class _FakeVar:
    def __init__(self, value: object = "") -> None:
        self.value = value

    def get(self) -> object:
        return self.value

    def set(self, value: object) -> None:
        self.value = value


class _FakeStateWidget:
    def __init__(self) -> None:
        self._states: set[str] = set()

    def state(self, changes: list[str] | tuple[str, ...] | None = None) -> tuple[str, ...]:
        if changes is None:
            return tuple(sorted(self._states))
        for change in changes:
            if change.startswith("!"):
                self._states.discard(change[1:])
            else:
                self._states.add(change)
        return tuple(sorted(self._states))


class DoiBatchUtilsTests(unittest.TestCase):
    def test_sd_scraper_parser_accepts_browser_exe(self) -> None:
        import sd_scraper

        args = sd_scraper.build_parser().parse_args([
            "-m",
            "doi_batch",
            "--input",
            "papers.csv",
            "--browser-exe",
            r"C:\Edge\msedge.exe",
        ])

        self.assertEqual(args.browser_exe, r"C:\Edge\msedge.exe")

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

    def test_extract_preserves_parenthesized_elsevier_doi(self) -> None:
        from doi_batch_utils import extract_doi_from_text

        doi = extract_doi_from_text("10.1016/0001-6160(59)90123-4")

        self.assertEqual(doi, "10.1016/0001-6160(59)90123-4")

    def test_preview_does_not_mark_distinct_parenthesized_dois_duplicate(self) -> None:
        from doi_batch_utils import preview_doi_input

        preview = preview_doi_input(
            pasted_text=(
                "10.1016/0001-6160(59)90123-4\n"
                "10.1016/0001-6160(59)90124-6\n"
                "10.1016/0001-6160(59)90123-4\n"
            ),
            limit=10,
        )

        self.assertEqual(preview.total_doi, 2)
        self.assertEqual(preview.status_counts["valid"], 2)
        self.assertEqual(preview.status_counts["duplicate"], 1)
        self.assertEqual([row.status for row in preview.rows], ["valid", "valid", "duplicate"])

    def test_extract_parenthesized_doi_from_markdown_link(self) -> None:
        from doi_batch_utils import extract_doi_from_text

        doi = extract_doi_from_text(
            "[10.1016/0001-6160(59)90123-4](https://doi.org/10.1016/0001-6160(59)90123-4)"
        )

        self.assertEqual(doi, "10.1016/0001-6160(59)90123-4")

    def test_extract_strips_outer_closing_parenthesis_from_wrapped_url(self) -> None:
        from doi_batch_utils import extract_doi_from_text

        doi = extract_doi_from_text("(https://doi.org/10.1016/j.actamat.2024.119999)")

        self.assertEqual(doi, "10.1016/j.actamat.2024.119999")

    def test_preview_classifies_empty_invalid_and_duplicate_rows(self) -> None:
        from doi_batch_utils import preview_doi_input

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "papers.csv"
            with path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["title", "doi"])
                writer.writeheader()
                writer.writerow({"title": "A", "doi": "https://doi.org/10.1016/j.actamat.2024.119999"})
                writer.writerow({"title": "B", "doi": ""})
                writer.writerow({"title": "C", "doi": "not-a-doi"})
                writer.writerow({"title": "D", "doi": "10.1016/j.actamat.2024.119999"})

            preview = preview_doi_input(input_path=path, limit=10)

        self.assertEqual(preview.total_rows, 4)
        self.assertEqual(preview.total_doi, 1)
        self.assertEqual(preview.status_counts, {"valid": 1, "empty": 1, "invalid": 1, "duplicate": 1})
        self.assertEqual([row.status for row in preview.rows], ["valid", "empty", "invalid", "duplicate"])
        self.assertEqual(preview.rows[2].raw_value, "not-a-doi")
        self.assertEqual(preview.rows[2].reason, "未识别到 DOI")

    def test_preview_marks_duplicate_pasted_dois(self) -> None:
        from doi_batch_utils import preview_doi_input

        preview = preview_doi_input(
            pasted_text=(
                "10.1016/j.matchar.2024.113000\n"
                "https://doi.org/10.1016/j.matchar.2024.113000\n"
            ),
            limit=10,
        )

        self.assertEqual(preview.total_doi, 1)
        self.assertEqual(preview.status_counts["valid"], 1)
        self.assertEqual(preview.status_counts["duplicate"], 1)
        self.assertEqual(preview.rows[1].status, "duplicate")


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
                browser_message=r"Edge: C:\Edge\msedge.exe; profile: C:\Edge\User Data\Default; debug_port: 9222",
                download_next_steps="Retry after Edge institutional sign-in.\nUse only legal public sources.",
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
            report_header = report_text.splitlines()[0]

        self.assertIn("DOI 批量任务报告", summary_text)
        self.assertIn("重复 DOI，已跳过: 1", summary_text)
        self.assertIn("Browser: Edge:", summary_text)
        self.assertIn("Retry after Edge institutional sign-in.", summary_text)
        self.assertEqual(report_header, "doi,pii,title,status,file,reason")
        self.assertIn("10.1016/example", report_text)

    def test_collects_retry_rows_from_failed_reports(self) -> None:
        from doi_batch_utils import collect_retry_input_rows, write_retry_input_csv

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            pdf_report = out / "pdf_download_report.csv"
            with pdf_report.open("w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=["doi", "pii", "title", "status", "file", "reason"])
                writer.writeheader()
                writer.writerow({
                    "doi": "10.1016/j.failedpdf.2024.1",
                    "pii": "S1",
                    "title": "PDF failed",
                    "status": "failed",
                    "file": "",
                    "reason": "未捕获PDF",
                })
                writer.writerow({
                    "doi": "10.1016/j.ok.2024.2",
                    "pii": "S2",
                    "title": "OK",
                    "status": "success",
                    "file": "ok.pdf",
                    "reason": "",
                })
                writer.writerow({
                    "doi": "",
                    "pii": "S3",
                    "title": "No DOI",
                    "status": "failed",
                    "file": "",
                    "reason": "无 DOI",
                })

            doi_failed = out / "doi_batch_failed.csv"
            with doi_failed.open("w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=["row_number", "doi", "reason"])
                writer.writeheader()
                writer.writerow({"row_number": "2", "doi": "", "reason": "DOI 为空"})
                writer.writerow({"row_number": "3", "doi": "10.1016/j.dup.2024.3", "reason": "重复 DOI，已跳过"})
                writer.writerow({
                    "row_number": "4",
                    "doi": "10.1016/j.resolvefailed.2024.4",
                    "reason": "DOI 访问失败",
                })

            rows = collect_retry_input_rows(pdf_report, doi_failed)
            retry_path = write_retry_input_csv(rows, out, timestamp="20260617_120000")

            retry_text = retry_path.read_text(encoding="utf-8-sig")

        self.assertEqual(
            [row["doi"] for row in rows],
            ["10.1016/j.failedpdf.2024.1", "10.1016/j.resolvefailed.2024.4"],
        )
        self.assertEqual(retry_path.name, "retry_failed_doi_20260617_120000.csv")
        self.assertIn("source_status", retry_text)
        self.assertIn("PDF failed", retry_text)

    def test_writes_run_event_jsonl_and_run_summary_json(self) -> None:
        from doi_batch_utils import (
            RunEvent,
            RunSummary,
            read_run_events,
            write_run_event,
            write_run_summary_json,
        )

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            event_path = out / "run_events.jsonl"
            write_run_event(
                event_path,
                RunEvent(
                    stage="resolve",
                    status="success",
                    row_number=2,
                    doi="10.1016/j.actamat.2024.119999",
                    title="Paper",
                    pii="S123",
                    counts={"resolved": 1},
                ),
            )
            summary = RunSummary(
                input_path="papers.csv",
                output_dir=str(out),
                total_doi=2,
                resolved_count=1,
                failure_reasons={"DOI 访问失败": 1},
                pdf_success=1,
                pdf_failed=0,
                pdf_skipped=0,
                resolved_path=str(out / "doi_batch_resolved.xlsx"),
                failed_path=str(out / "doi_batch_failed.csv"),
                pdf_report_path=str(out / "pdf_download_report.csv"),
                browser_message="Edge: fake",
                download_next_steps="Inspect failure reports.",
            )
            summary_path = write_run_summary_json(summary, event_path=event_path)

            events = read_run_events(event_path)
            summary_data = json.loads(summary_path.read_text(encoding="utf-8"))

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["stage"], "resolve")
        self.assertEqual(events[0]["status"], "success")
        self.assertEqual(events[0]["counts"]["resolved"], 1)
        self.assertEqual(summary_data["browser_message"], "Edge: fake")
        self.assertEqual(summary_data["download_next_steps"], "Inspect failure reports.")
        self.assertEqual(summary_data["total_doi"], 2)
        self.assertEqual(summary_data["resolved_count"], 1)
        self.assertEqual(summary_data["pdf_success"], 1)
        self.assertEqual(summary_data["event_path"], str(event_path))

    def test_resume_helpers_skip_only_pdf_success_and_merge_failure_rows(self) -> None:
        from doi_batch_utils import (
            collect_failure_table_rows,
            collect_retry_input_rows,
            filter_records_for_resume,
            load_resume_success_dois,
        )

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            pdf_report = out / "pdf_download_report.csv"
            with pdf_report.open("w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=["doi", "pii", "title", "status", "file", "reason"])
                writer.writeheader()
                writer.writerow({
                    "doi": "10.1016/j.done.2024.1",
                    "pii": "S1",
                    "title": "Done",
                    "status": "success",
                    "file": "001_Done.pdf",
                    "reason": "",
                })
                writer.writerow({
                    "doi": "10.1016/j.pdfailed.2024.2",
                    "pii": "S2",
                    "title": "PDF failed",
                    "status": "failed",
                    "file": "",
                    "reason": "未捕获PDF",
                })

            doi_failed = out / "doi_batch_failed.csv"
            with doi_failed.open("w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=["row_number", "doi", "reason"])
                writer.writeheader()
                writer.writerow({
                    "row_number": "4",
                    "doi": "10.1016/j.resolvefailed.2024.3",
                    "reason": "DOI 访问失败",
                })
                writer.writerow({"row_number": "5", "doi": "", "reason": "DOI 为空"})

            success_dois = load_resume_success_dois(out)
            kept, skipped = filter_records_for_resume(
                [
                    {"row_number": 2, "doi": "10.1016/j.done.2024.1", "title": "Done"},
                    {"row_number": 3, "doi": "10.1016/j.pdfailed.2024.2", "title": "PDF failed"},
                    {"row_number": 4, "doi": "10.1016/j.new.2024.4", "title": "New"},
                ],
                success_dois,
            )
            failure_rows = collect_failure_table_rows(pdf_report, doi_failed)
            selected_retry_rows = collect_retry_input_rows(
                pdf_report,
                doi_failed,
                selected_dois={"10.1016/j.resolvefailed.2024.3"},
            )

        self.assertEqual(success_dois, {"10.1016/j.done.2024.1"})
        self.assertEqual([row["doi"] for row in kept], ["10.1016/j.pdfailed.2024.2", "10.1016/j.new.2024.4"])
        self.assertEqual(skipped[0]["reason"], "已在历史结果中成功下载 PDF，断点恢复跳过")
        self.assertEqual(
            [(row["kind"], row["doi"]) for row in failure_rows],
            [("PDF失败", "10.1016/j.pdfailed.2024.2"), ("解析失败", "10.1016/j.resolvefailed.2024.3")],
        )
        self.assertEqual([row["doi"] for row in selected_retry_rows], ["10.1016/j.resolvefailed.2024.3"])

    def test_finds_resume_candidates_by_input_name_and_doi_overlap(self) -> None:
        from doi_batch_utils import find_resume_candidates

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current_input = root / "papers.csv"
            current_input.write_text("doi\n10.1016/j.done.2024.1\n", encoding="utf-8")

            matched = root / "doi_batch_matched"
            matched.mkdir()
            (matched / "run_summary.json").write_text(
                json.dumps({
                    "input_path": str(root / "old" / "papers.csv"),
                    "total_doi": 3,
                    "pdf_report_path": str(matched / "pdf_download_report.csv"),
                }),
                encoding="utf-8",
            )
            with (matched / "pdf_download_report.csv").open("w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=["doi", "pii", "title", "status", "file", "reason"])
                writer.writeheader()
                writer.writerow({"doi": "10.1016/j.done.2024.1", "status": "success"})
                writer.writerow({"doi": "10.1016/j.failed.2024.2", "status": "failed"})

            unrelated = root / "doi_batch_unrelated"
            unrelated.mkdir()
            with (unrelated / "pdf_download_report.csv").open("w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=["doi", "pii", "title", "status", "file", "reason"])
                writer.writeheader()
                writer.writerow({"doi": "10.1016/j.other.2024.1", "status": "success"})

            candidates = find_resume_candidates(
                root,
                input_path=current_input,
                current_dois={"10.1016/j.done.2024.1", "10.1016/j.failed.2024.2"},
            )

        self.assertGreaterEqual(len(candidates), 2)
        self.assertEqual(Path(candidates[0].path).name, "doi_batch_matched")
        self.assertTrue(candidates[0].input_match)
        self.assertEqual(candidates[0].overlap_count, 2)
        self.assertGreater(candidates[0].score, candidates[1].score)

    def test_writes_auto_retry_input_with_stats(self) -> None:
        from doi_batch_utils import write_retry_input_from_reports

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            pdf_report = out / "pdf_download_report.csv"
            with pdf_report.open("w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=["doi", "pii", "title", "status", "file", "reason"])
                writer.writeheader()
                writer.writerow({
                    "doi": "10.1016/j.pdfailed.2024.1",
                    "title": "PDF failed",
                    "status": "failed",
                    "reason": "未捕获PDF",
                })
                writer.writerow({
                    "doi": "10.1016/j.skipped.2024.2",
                    "title": "Skipped",
                    "status": "skipped",
                    "reason": "未请求下载",
                })
            doi_failed = out / "doi_batch_failed.csv"
            with doi_failed.open("w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=["row_number", "doi", "title", "reason"])
                writer.writeheader()
                writer.writerow({
                    "row_number": "2",
                    "doi": "10.1016/j.resolvefailed.2024.3",
                    "title": "Resolve failed",
                    "reason": "DOI 访问失败",
                })
                writer.writerow({"row_number": "3", "doi": "", "title": "Empty", "reason": "DOI 为空"})
                writer.writerow({
                    "row_number": "4",
                    "doi": "10.1016/j.duplicate.2024.4",
                    "title": "Duplicate",
                    "reason": "重复 DOI，已跳过",
                })

            result = write_retry_input_from_reports(pdf_report, doi_failed, out, timestamp="20260617_130000")
            retry_text = Path(result.path).read_text(encoding="utf-8-sig")

        self.assertEqual(result.row_count, 2)
        self.assertGreaterEqual(result.excluded_count, 3)
        self.assertIn("10.1016/j.pdfailed.2024.1", retry_text)
        self.assertIn("10.1016/j.resolvefailed.2024.3", retry_text)
        self.assertNotIn("10.1016/j.skipped.2024.2", retry_text)


class CliBehaviorTests(unittest.TestCase):
    def test_cli_auto_retry_input_generates_retry_csv_without_pdf_retrying(self) -> None:
        import sd_scraper

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "papers.csv"
            input_path.write_text("title,doi\nA,10.1016/j.failed.2024.1\nB,\n", encoding="utf-8")
            output_root = root / "results"

            original_argv = sys.argv[:]
            original_resolve = sd_scraper.ScienceDirectScraper._resolve_doi_to_article
            try:
                sd_scraper.ScienceDirectScraper._resolve_doi_to_article = (
                    lambda self, item: (None, "DOI 访问失败: synthetic")
                )
                sys.argv = [
                    "sd_scraper.py",
                    "-m",
                    "doi_batch",
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_root),
                    "--filename",
                    "run",
                    "--auto-retry-input",
                ]
                sd_scraper.main()
            finally:
                sd_scraper.ScienceDirectScraper._resolve_doi_to_article = original_resolve
                sys.argv = original_argv

            run_dir = output_root / "run"
            retry_files = list(run_dir.glob("retry_failed_doi_*.csv"))
            summary = json.loads((run_dir / "run_summary.json").read_text(encoding="utf-8"))
            retry_text = retry_files[0].read_text(encoding="utf-8-sig") if retry_files else ""

        self.assertEqual(len(retry_files), 1)
        self.assertIn("10.1016/j.failed.2024.1", retry_text)
        self.assertNotIn("DOI 为空", retry_text)
        self.assertEqual(summary["retry_input_count"], 1)
        self.assertEqual(summary["retry_input_path"], str(retry_files[0]))


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
            self.assertTrue(app.download_supplements_var.get())
            self.assertTrue(hasattr(app, "preview_tree"))
            self.assertTrue(hasattr(app, "retry_failed_button"))
        finally:
            root.destroy()

    def test_ui_sciencedirect_supplement_command_defaults_and_disable_flag(self) -> None:
        from paper_scraper_ui import PaperScraperUI

        with tempfile.TemporaryDirectory() as tmp:
            root_dir = Path(tmp)
            input_path = root_dir / "papers.csv"
            input_path.write_text("doi\n10.1016/j.actamat.2024.119999\n", encoding="utf-8")

            app = PaperScraperUI.__new__(PaperScraperUI)
            app.workflow_var = _FakeVar("sciencedirect")
            app.mode_var = _FakeVar("doi_batch")
            app.input_file_var = _FakeVar(str(input_path))
            app.output_var = _FakeVar(str(root_dir / "results"))
            app.doi_column_var = _FakeVar("")
            app.sheet_var = _FakeVar("")
            app.filename_var = _FakeVar("")
            app.resume_from_var = _FakeVar("")
            app.cookies_file_var = _FakeVar("")
            app.browser_cookies_var = _FakeVar(False)
            app.open_login_var = _FakeVar(False)
            app.download_pdf_var = _FakeVar(True)
            app.download_supplements_var = _FakeVar(True)
            app._get_pasted_text = lambda: ""

            default_cmd = app._build_command(materialize_paste=False)
            app.download_supplements_var.set(False)
            disabled_cmd = app._build_command(materialize_paste=False)
            app.download_pdf_var.set(False)
            no_pdf_cmd = app._build_command(materialize_paste=False)

        self.assertIn("--download-pdfs", default_cmd)
        self.assertNotIn("--no-download-supplements", default_cmd)
        self.assertIn("--download-pdfs", disabled_cmd)
        self.assertIn("--no-download-supplements", disabled_cmd)
        self.assertNotIn("--download-pdfs", no_pdf_cmd)
        self.assertNotIn("--no-download-supplements", no_pdf_cmd)

    def test_ui_pdf_toggle_disables_supplement_checkbox_and_preserves_value(self) -> None:
        from paper_scraper_ui import PaperScraperUI

        app = PaperScraperUI.__new__(PaperScraperUI)
        app.download_pdf_var = _FakeVar(True)
        app.download_supplements_var = _FakeVar(False)
        app.download_supplements_checkbuttons = [_FakeStateWidget(), _FakeStateWidget()]

        app.download_pdf_var.set(False)
        app._sync_download_supplements_state()
        off_states = [widget.state() for widget in app.download_supplements_checkbuttons]
        preserved_while_disabled = app.download_supplements_var.get()

        app.download_pdf_var.set(True)
        app._sync_download_supplements_state()
        on_states = [widget.state() for widget in app.download_supplements_checkbuttons]
        preserved_after_reenable = app.download_supplements_var.get()

        self.assertTrue(all("disabled" in state for state in off_states))
        self.assertFalse(preserved_while_disabled)
        self.assertTrue(all("disabled" not in state for state in on_states))
        self.assertFalse(preserved_after_reenable)

    def test_ui_result_summary_displays_supplement_counts_from_json_and_text(self) -> None:
        from paper_scraper_ui import PaperScraperUI

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            supplement_report = out / "supplement_download_report.csv"
            supplement_report.write_text("doi,status\n10.1016/example,skipped\n", encoding="utf-8")
            json_summary_path = out / "run_summary.json"
            json_summary_path.write_text(
                json.dumps(
                    {
                        "output_dir": str(out),
                        "total_doi": 4,
                        "resolved_count": 4,
                        "resolve_failed_count": 0,
                        "failure_reasons": {},
                        "pdf_success": 4,
                        "pdf_failed": 0,
                        "pdf_skipped": 0,
                        "supplement_success": 1,
                        "supplement_failed": 2,
                        "supplement_skipped": 3,
                        "supplement_not_found": 4,
                        "supplement_report_path": str(supplement_report),
                    }
                ),
                encoding="utf-8",
            )
            txt_summary_path = out / "run_summary.txt"
            txt_summary_path.write_text(
                "\n".join(
                    [
                        "DOI 批量任务报告",
                        "==================",
                        "识别 DOI 数: 4",
                        "成功解析数: 4",
                        "解析失败数: 0",
                        "",
                        "解析失败原因:",
                        "- 无",
                        "",
                        "PDF 下载:",
                        "- 成功: 4",
                        "- 失败: 0",
                        "- 跳过: 0",
                        "",
                        "补充材料下载:",
                        "- 成功: 1",
                        "- 失败: 2",
                        "- 跳过: 3",
                        "- 未发现: 4",
                        "",
                        "输出文件:",
                        f"- Supplement 下载报告: {supplement_report}",
                    ]
                ),
                encoding="utf-8",
            )

            app = PaperScraperUI.__new__(PaperScraperUI)
            app.result_summary_var = _FakeVar("")
            app.workflow_var = _FakeVar("sciencedirect")
            app.last_run_output_dir = None
            app.last_failed_report_path = None
            app.last_pdf_report_path = None
            app.last_events_path = None
            app.last_retry_input_path = None
            app.last_summary_path = None

            app.last_summary_json_path = json_summary_path
            app._refresh_result_summary()
            json_result_summary = app.result_summary_var.get()

            app.last_summary_json_path = None
            app.last_summary_path = txt_summary_path
            app._refresh_result_summary()
            txt_result_summary = app.result_summary_var.get()

        for result_summary in (json_result_summary, txt_result_summary):
            self.assertIn("补充材料成功: 1", result_summary)
            self.assertIn("补充材料失败: 2", result_summary)
            self.assertIn("补充材料跳过: 3", result_summary)
            self.assertIn("补充材料未发现: 4", result_summary)

    def test_ui_supplement_summary_uses_current_requested_json_field(self) -> None:
        from paper_scraper_ui import PaperScraperUI

        self.assertTrue(PaperScraperUI._should_show_supplement_summary_from_json({
            "supplement_requested": True,
            "supplement_success": 0,
            "supplement_failed": 0,
            "supplement_skipped": 0,
            "supplement_not_found": 0,
            "supplement_report_path": "",
        }))

    def test_ui_legal_oa_mode_builds_paper_skill_command(self) -> None:
        try:
            from tkinter import Tk
        except Exception as exc:
            self.skipTest(f"tkinter unavailable: {exc}")

        from paper_scraper_ui import PaperScraperUI

        with tempfile.TemporaryDirectory() as tmp:
            root_dir = Path(tmp)
            input_path = root_dir / "papers.md"
            input_path.write_text("DOI: 10.1038/example\n", encoding="utf-8")

            try:
                root = Tk()
            except Exception as exc:
                self.skipTest(f"cannot start Tk root: {exc}")
            root.withdraw()
            try:
                app = PaperScraperUI(root)
                app.workflow_var.set("legal_oa")
                app.oa_input_file_var.set(str(input_path))
                app.output_var.set(str(root_dir / "out"))
                app.oa_email_var.set("researcher@example.com")
                app.oa_limit_var.set("5")
                app.oa_dry_run_var.set(True)
                cmd = app._build_command(materialize_paste=False)
                summary = app.summary_var.get()
            finally:
                root.destroy()

        self.assertTrue(any(part.endswith("paper_skill.py") for part in cmd))
        self.assertIn("--input", cmd)
        self.assertIn(str(input_path), cmd)
        self.assertIn("--out", cmd)
        self.assertIn(str(root_dir / "out"), cmd)
        self.assertIn("--email", cmd)
        self.assertIn("researcher@example.com", cmd)
        self.assertIn("--limit", cmd)
        self.assertIn("5", cmd)
        self.assertIn("--dry-run", cmd)
        self.assertNotIn("--cookies", cmd)
        self.assertNotIn("--browser-cookies", cmd)
        self.assertIn("合法 OA 下载", summary)

    def test_ui_reads_structured_events_summary_and_resume_command(self) -> None:
        try:
            from tkinter import Tk, messagebox
        except Exception as exc:
            self.skipTest(f"tkinter unavailable: {exc}")

        from doi_batch_utils import RunEvent, RunSummary, write_run_event, write_run_summary_json
        from paper_scraper_ui import PaperScraperUI

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            event_path = out / "run_events.jsonl"
            write_run_event(
                event_path,
                RunEvent(
                    stage="pdf",
                    status="failed",
                    doi="10.1016/j.pdfailed.2024.2",
                    title="PDF failed",
                    reason="未捕获PDF",
                    counts={"pdf_success": 1, "pdf_failed": 1, "pdf_skipped": 0},
                ),
            )
            pdf_report = out / "pdf_download_report.csv"
            with pdf_report.open("w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=["doi", "pii", "title", "status", "file", "reason"])
                writer.writeheader()
                writer.writerow({
                    "doi": "10.1016/j.pdfailed.2024.2",
                    "pii": "S2",
                    "title": "PDF failed",
                    "status": "failed",
                    "file": "",
                    "reason": "未捕获PDF",
                })
            failed_report = out / "doi_batch_failed.csv"
            with failed_report.open("w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=["row_number", "doi", "reason"])
                writer.writeheader()
                writer.writerow({"row_number": "3", "doi": "10.1016/j.resolvefailed.2024.3", "reason": "DOI 访问失败"})
            summary_path = write_run_summary_json(
                RunSummary(
                    input_path="papers.csv",
                    output_dir=str(out),
                    total_doi=3,
                    resolved_count=2,
                    failure_reasons={"DOI 访问失败": 1},
                    pdf_success=1,
                    pdf_failed=1,
                    pdf_skipped=0,
                    failed_path=str(failed_report),
                    pdf_report_path=str(pdf_report),
                ),
                event_path=event_path,
            )

            try:
                root = Tk()
            except Exception as exc:
                self.skipTest(f"cannot start Tk root: {exc}")
            root.withdraw()
            original_info = messagebox.showinfo
            original_error = messagebox.showerror
            try:
                messagebox.showinfo = lambda *args, **kwargs: None
                messagebox.showerror = lambda *args, **kwargs: None
                app = PaperScraperUI(root)
                app.input_file_var.set(str(out / "papers.csv"))
                app.resume_from_var.set(str(out))
                cmd = app._build_command(materialize_paste=False)
                app.last_run_output_dir = out
                app.last_events_path = event_path
                app.last_summary_json_path = summary_path
                app.last_pdf_report_path = pdf_report
                app.last_failed_report_path = failed_report

                app._poll_run_events_once()
                app._refresh_result_summary()
                app._load_failure_table()
                first_item = app.failure_tree.get_children()[0]
                app.failure_tree.selection_set(first_item)
                app.create_retry_input_from_reports(selected_only=True)

                retry_path = Path(app.input_file_var.get())
                retry_text = retry_path.read_text(encoding="utf-8-sig")
                failure_count = len(app.failure_tree.get_children())
                current_task = app.current_task_var.get()
                result_summary = app.result_summary_var.get()
            finally:
                messagebox.showinfo = original_info
                messagebox.showerror = original_error
                root.destroy()

        self.assertIn("--resume-from", cmd)
        self.assertIn(str(out), cmd)
        self.assertIn("PDF failed", current_task)
        self.assertIn("PDF 失败: 1", result_summary)
        self.assertEqual(failure_count, 2)
        self.assertIn("10.1016/j.pdfailed.2024.2", retry_text)

    def test_ui_smart_wizard_prepares_resume_login_and_auto_retry(self) -> None:
        try:
            from tkinter import Tk, messagebox
        except Exception as exc:
            self.skipTest(f"tkinter unavailable: {exc}")

        from paper_scraper_ui import PaperScraperUI

        with tempfile.TemporaryDirectory() as tmp:
            root_dir = Path(tmp)
            input_path = root_dir / "papers.csv"
            input_path.write_text(
                "title,doi\n"
                "A,10.1016/j.done.2024.1\n"
                "B,10.1016/j.failed.2024.2\n"
                "C,\n",
                encoding="utf-8",
            )
            history = root_dir / "results" / "doi_batch_old"
            history.mkdir(parents=True)
            (history / "run_summary.json").write_text(
                json.dumps({"input_path": str(root_dir / "old" / "papers.csv"), "total_doi": 2}),
                encoding="utf-8",
            )
            with (history / "pdf_download_report.csv").open("w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=["doi", "pii", "title", "status", "file", "reason"])
                writer.writeheader()
                writer.writerow({"doi": "10.1016/j.done.2024.1", "title": "A", "status": "success"})
            bad_cookie = root_dir / "cookies.json"
            bad_cookie.write_text(
                json.dumps([{"domain": ".example.com", "name": "session", "value": "SECRET_COOKIE_VALUE"}]),
                encoding="utf-8",
            )

            try:
                tk_root = Tk()
            except Exception as exc:
                self.skipTest(f"cannot start Tk root: {exc}")
            tk_root.withdraw()
            original_askyesno = messagebox.askyesno
            original_info = messagebox.showinfo
            original_error = messagebox.showerror
            try:
                messagebox.askyesno = lambda *args, **kwargs: True
                messagebox.showinfo = lambda *args, **kwargs: None
                messagebox.showerror = lambda *args, **kwargs: None
                app = PaperScraperUI(tk_root)
                app.input_file_var.set(str(input_path))
                app.output_var.set(str(root_dir / "results"))
                app.cookies_file_var.set(str(bad_cookie))
                app.download_pdf_var.set(True)
                calls: list[bool] = []
                app.run_scraper = lambda auto_retry_input=False: calls.append(bool(auto_retry_input))  # type: ignore[method-assign]

                app.run_smart_doi_wizard()
                cmd = app._build_command(materialize_paste=False, auto_retry_input=True)
                summary = app.last_smart_wizard_summary
            finally:
                messagebox.askyesno = original_askyesno
                messagebox.showinfo = original_info
                messagebox.showerror = original_error
                tk_root.destroy()

        self.assertTrue(hasattr(app, "smart_run_button"))
        self.assertEqual(calls, [True])
        self.assertIn("--auto-retry-input", cmd)
        self.assertIn("--resume-from", cmd)
        self.assertEqual(app.resume_from_var.get(), str(history))
        self.assertTrue(app.open_login_var.get())
        self.assertIn("有效 DOI: 2", summary)
        self.assertIn("断点恢复: " + str(history), summary)
        self.assertNotIn("SECRET_COOKIE_VALUE", summary)

    def test_ui_auto_retry_after_completion_fills_input_without_rerun(self) -> None:
        try:
            from tkinter import Tk, messagebox
        except Exception as exc:
            self.skipTest(f"tkinter unavailable: {exc}")

        from paper_scraper_ui import PaperScraperUI

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            pdf_report = out / "pdf_download_report.csv"
            with pdf_report.open("w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=["doi", "pii", "title", "status", "file", "reason"])
                writer.writeheader()
                writer.writerow({
                    "doi": "10.1016/j.pdfailed.2024.1",
                    "title": "PDF failed",
                    "status": "failed",
                    "reason": "未捕获PDF",
                })
            failed_report = out / "doi_batch_failed.csv"
            with failed_report.open("w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=["row_number", "doi", "title", "reason"])
                writer.writeheader()
                writer.writerow({"row_number": "3", "doi": "", "title": "Empty", "reason": "DOI 为空"})

            try:
                tk_root = Tk()
            except Exception as exc:
                self.skipTest(f"cannot start Tk root: {exc}")
            tk_root.withdraw()
            original_info = messagebox.showinfo
            original_error = messagebox.showerror
            try:
                messagebox.showinfo = lambda *args, **kwargs: None
                messagebox.showerror = lambda *args, **kwargs: None
                app = PaperScraperUI(tk_root)
                app.last_run_output_dir = out
                app.last_pdf_report_path = pdf_report
                app.last_failed_report_path = failed_report
                app.auto_retry_after_run = True

                app._handle_auto_retry_after_completion()

                retry_path = Path(app.input_file_var.get())
                retry_exists = retry_path.exists()
                retry_text = retry_path.read_text(encoding="utf-8-sig")
                summary = app.result_summary_var.get()
            finally:
                messagebox.showinfo = original_info
                messagebox.showerror = original_error
                tk_root.destroy()

        self.assertTrue(retry_exists)
        self.assertIn("10.1016/j.pdfailed.2024.1", retry_text)
        self.assertIn("已生成重试输入", summary)


if __name__ == "__main__":
    unittest.main()
