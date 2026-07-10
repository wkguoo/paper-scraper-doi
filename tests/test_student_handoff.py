from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path


class StudentHandoffTests(unittest.TestCase):
    def test_shadow_library_status_is_not_completed(self) -> None:
        from student_handoff import classify_failure

        category = classify_failure(
            status="scihub_downloaded",
            reason="",
            doi="10.1016/j.failed.2024.1",
            source="pdf",
        )

        self.assertEqual(category, "可重试 PDF 失败")

    def test_writes_student_index_readme_xlsx_and_failure_next_steps(self) -> None:
        from doi_batch_utils import PdfDownloadRecord, SupplementDownloadRecord
        from student_handoff import write_student_handoff

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            paths = write_student_handoff(
                out,
                resolved_records=[
                    {"doi": "10.1016/j.actamat.2024.119999", "pii": "S135964542400001X", "title": "Downloaded paper"},
                    {"doi": "10.1016/j.failed.2024.1", "pii": "S135964542400002X", "title": "Failed paper"},
                    {"doi": "10.1016/j.preflight.2024.2", "pii": "", "title": "Preflight paper"},
                ],
                failed_records=[
                    {"row_number": "5", "doi": "10.1038/example", "title": "Nature paper", "reason": "non_sciencedirect"},
                ],
                pdf_records=[
                    PdfDownloadRecord(
                        doi="10.1016/j.actamat.2024.119999",
                        pii="S135964542400001X",
                        title="Downloaded paper",
                        status="success",
                        file="pdfs/2024_Zhang_Downloaded_abcdef12.pdf",
                    ),
                    PdfDownloadRecord(
                        doi="10.1016/j.failed.2024.1",
                        pii="S135964542400002X",
                        title="Failed paper",
                        status="failed",
                        reason="blocked: 403 captcha",
                    ),
                    PdfDownloadRecord(
                        doi="10.1016/j.preflight.2024.2",
                        pii="",
                        title="Preflight paper",
                        status="not_requested",
                        reason="preflight",
                    ),
                ],
                supplement_records=[
                    SupplementDownloadRecord(
                        doi="10.1016/j.actamat.2024.119999",
                        pii="S135964542400001X",
                        article_title="Downloaded paper",
                        article_file="2024_Zhang_Downloaded_abcdef12.pdf",
                        supplement_index=1,
                        supplement_title="Raw data",
                        status="success",
                        file="supplements/2024_Zhang_Downloaded_abcdef12/S01_Raw data.xlsx",
                    ),
                    SupplementDownloadRecord(
                        doi="10.1016/j.failed.2024.1",
                        pii="S135964542400002X",
                        article_title="Failed paper",
                        supplement_index=1,
                        supplement_title="Appendix",
                        status="failed",
                        reason="非附件响应或登录页面",
                    ),
                    SupplementDownloadRecord(
                        doi="10.1016/j.preflight.2024.2",
                        pii="",
                        article_title="Preflight paper",
                        status="not_found",
                        reason="未发现补充材料链接",
                    ),
                ],
            )

            self.assertTrue(paths.student_dir.exists())
            self.assertTrue(paths.readme_path.exists())
            self.assertTrue(paths.paper_index_path.exists())
            self.assertTrue(paths.paper_index_xlsx_path.exists())
            self.assertTrue(paths.failure_next_steps_path.exists())
            self.assertTrue(paths.library_index_path.exists())

            with paths.paper_index_path.open("r", newline="", encoding="utf-8-sig") as f:
                index_rows = list(csv.DictReader(f))
            with paths.failure_next_steps_path.open("r", newline="", encoding="utf-8-sig") as f:
                failure_rows = list(csv.DictReader(f))

            self.assertEqual(len(index_rows), 4)
            downloaded = next(row for row in index_rows if row["DOI"] == "10.1016/j.actamat.2024.119999")
            self.assertEqual(downloaded["PDF状态"], "success")
            self.assertEqual(downloaded["处理类别"], "已完成")
            self.assertEqual(downloaded["正文PDF相对路径"], "pdfs\\2024_Zhang_Downloaded_abcdef12.pdf")
            self.assertIn("success:1", downloaded["补充材料状态汇总"])
            self.assertEqual(downloaded["补充材料数量"], "1")
            self.assertIn("supplements\\2024_Zhang_Downloaded_abcdef12\\S01_Raw data.xlsx", downloaded["补充材料相对路径"])

            categories = {(row["类别"], row["DOI"]) for row in failure_rows}
            self.assertIn(("验证码或限速", "10.1016/j.failed.2024.1"), categories)
            self.assertIn(("非 ScienceDirect", "10.1038/example"), categories)
            self.assertIn(("未请求下载", "10.1016/j.preflight.2024.2"), categories)
            self.assertIn(("补充材料失败", "10.1016/j.failed.2024.1"), categories)

            readme_text = paths.readme_path.read_text(encoding="utf-8")
            self.assertIn("not_found 表示网页中没有检测到可下载附件链接", readme_text)

    def test_reads_existing_reports_and_writes_library_index_alias(self) -> None:
        from student_handoff import write_student_handoff

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            pdf_report = out / "pdf_download_report.csv"
            with pdf_report.open("w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=["doi", "pii", "title", "status", "file", "reason"])
                writer.writeheader()
                writer.writerow({
                    "doi": "10.1016/j.notpdf.2024.1",
                    "pii": "S000000000000001X",
                    "title": "HTML response paper",
                    "status": "failed",
                    "file": "",
                    "reason": "响应非 PDF",
                })

            paths = write_student_handoff(out, pdf_report_path=pdf_report)

            self.assertEqual(
                paths.paper_index_path.read_text(encoding="utf-8-sig"),
                paths.library_index_path.read_text(encoding="utf-8-sig"),
            )
            with paths.failure_next_steps_path.open("r", newline="", encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows[0]["类别"], "响应不是 PDF")


if __name__ == "__main__":
    unittest.main()
