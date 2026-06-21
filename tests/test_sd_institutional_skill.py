from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote_plus
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class InstitutionalSkillIntakeTests(unittest.TestCase):
    def test_main_writes_empty_reports_when_no_valid_doi(self) -> None:
        from sd_institutional_skill import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "invalid.csv"
            with input_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["title", "doi"])
                writer.writeheader()
                writer.writerow({"title": "", "doi": "not-a-doi"})

            exit_code = main([
                "--input",
                str(input_path),
                "--out",
                str(root),
                "--run-name",
                "no_valid",
                "--dry-run",
            ])

            run_dir = root / "no_valid"
            failed_path = run_dir / "doi_batch_failed.csv"
            pdf_report_path = run_dir / "pdf_download_report.csv"
            summary_path = run_dir / "run_summary.txt"

            self.assertNotEqual(exit_code, 0)
            self.assertTrue(failed_path.exists())
            self.assertTrue(pdf_report_path.exists())
            self.assertTrue(summary_path.exists())
            with failed_path.open("r", encoding="utf-8-sig") as f:
                failed_rows = list(csv.DictReader(f))
            self.assertEqual(len(failed_rows), 1)
            self.assertIn("invalid", failed_rows[0]["reason"])
            with pdf_report_path.open("r", encoding="utf-8-sig") as f:
                self.assertEqual(list(csv.DictReader(f)), [])

            summary_text = summary_path.read_text(encoding="utf-8")
            self.assertIn(str(run_dir / "merged_doi_input.csv"), summary_text)
            self.assertIn(str(failed_path), summary_text)
            self.assertIn(str(pdf_report_path), summary_text)
            self.assertIn("识别 DOI 数: 0", summary_text)
            self.assertIn("成功解析数: 0", summary_text)
            self.assertIn("解析失败数: 1", summary_text)
            self.assertIn("- 成功: 0", summary_text)
            self.assertIn("- 失败: 0", summary_text)
            self.assertIn("- 跳过: 0", summary_text)

    def test_build_intake_merges_text_files_and_ignores_output_dirs(self) -> None:
        from sd_institutional_skill import build_intake, iter_input_files

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "sources"
            source_dir.mkdir()
            csv_path = source_dir / "papers.csv"
            with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=["title", "doi"])
                writer.writeheader()
                writer.writerow({"title": "A", "doi": "10.1016/j.actamat.2024.119999"})
                writer.writerow({"title": "Duplicate", "doi": "https://doi.org/10.1016/j.actamat.2024.119999"})
                writer.writerow({"title": "Invalid", "doi": "not-a-doi"})
                writer.writerow({"title": "Empty", "doi": ""})

            ignored = source_dir / "results"
            ignored.mkdir()
            (ignored / "ignored.txt").write_text("10.1016/j.ignored.2024.1", encoding="utf-8")
            (source_dir / "cookies.json").write_text("[]", encoding="utf-8")

            files = [path.name for path in iter_input_files(source_dir)]
            self.assertEqual(files, ["papers.csv"])

            output_dir = root / "out"
            result = build_intake(
                texts=["extra DOI: 10.1016/j.scriptamat.2024.115000"],
                input_paths=[],
                folder_paths=[source_dir],
                output_dir=output_dir,
            )

            self.assertEqual(result.status_counts["valid"], 2)
            self.assertEqual(result.status_counts["duplicate"], 1)
            self.assertEqual(result.status_counts["invalid"], 1)
            self.assertEqual(result.status_counts["needs_review"], 1)
            self.assertEqual(result.valid_count, 2)

            preview_text = result.preview_path.read_text(encoding="utf-8-sig")
            merged_text = result.merged_input_path.read_text(encoding="utf-8-sig")
            self.assertIn("重复 DOI", preview_text)
            self.assertIn("未识别到 DOI", preview_text)
            self.assertIn("metadata_confidence_below_threshold", preview_text)
            self.assertIn("10.1016/j.scriptamat.2024.115000", merged_text)
            self.assertNotIn("10.1016/j.ignored.2024.1", merged_text)

    def test_build_intake_resolves_title_only_text_to_doi_metadata(self) -> None:
        from sd_institutional_skill import build_intake

        def fake_json(url: str, headers: dict[str, str] | None = None, timeout: int = 20) -> dict:
            if "api.crossref.org/works?" in url:
                return {
                    "message": {
                        "items": [
                            {
                                "DOI": "10.1016/j.actamat.2024.119999",
                                "title": ["Additive manufacturing of gamma-TiAl alloys"],
                                "author": [{"family": "Zhang", "given": "Wei"}],
                                "container-title": ["Acta Materialia"],
                                "published-print": {"date-parts": [[2024]]},
                                "publisher": "Elsevier",
                                "URL": "https://doi.org/10.1016/j.actamat.2024.119999",
                            }
                        ]
                    }
                }
            return {}

        with tempfile.TemporaryDirectory() as tmp:
            result = build_intake(
                texts=[
                    "Additive manufacturing of gamma-TiAl alloys\n"
                    "DOI: 10.1016/j.actamat.2024.119999"
                ],
                input_paths=[],
                folder_paths=[],
                output_dir=Path(tmp),
                resolve_metadata=True,
                http_json=fake_json,
            )
            merged_text = result.merged_input_path.read_text(encoding="utf-8-sig")
            preview_text = result.preview_path.read_text(encoding="utf-8-sig")

        self.assertEqual(result.valid_count, 1)
        self.assertEqual(result.status_counts["duplicate"], 1)
        self.assertIn("10.1016/j.actamat.2024.119999", merged_text)
        self.assertIn("Zhang Wei", preview_text)
        self.assertIn("Acta Materialia", preview_text)
        self.assertIn("重复 DOI", preview_text)

    def test_build_intake_title_only_csv_resolves_or_needs_review(self) -> None:
        from sd_institutional_skill import build_intake

        def fake_json(url: str, headers: dict[str, str] | None = None, timeout: int = 20) -> dict:
            decoded_url = unquote_plus(url)
            if "api.crossref.org/works?" in url and "Resolvable title only paper" in decoded_url:
                return {
                    "message": {
                        "items": [
                            {
                                "DOI": "10.1016/j.actamat.2025.120001",
                                "title": ["Resolvable title only paper"],
                                "author": [{"family": "Chen", "given": "Ming"}],
                                "container-title": ["Acta Materialia"],
                                "published-print": {"date-parts": [[2025]]},
                                "publisher": "Elsevier",
                                "URL": "https://doi.org/10.1016/j.actamat.2025.120001",
                            }
                        ]
                    }
                }
            return {}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path = root / "title_only.csv"
            with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=["paper title", "author", "source", "publication year"])
                writer.writeheader()
                writer.writerow({
                    "paper title": "Resolvable title only paper",
                    "author": "Chen Ming",
                    "source": "Acta Materialia",
                    "publication year": "2025",
                })
                writer.writerow({
                    "paper title": "Unmatched title only paper",
                    "author": "Li Qiang",
                    "source": "Scripta Materialia",
                    "publication year": "2024",
                })

            result = build_intake(
                texts=[],
                input_paths=[csv_path],
                folder_paths=[],
                output_dir=root / "out",
                resolve_metadata=True,
                http_json=fake_json,
            )

            preview_text = result.preview_path.read_text(encoding="utf-8-sig")
            merged_text = result.merged_input_path.read_text(encoding="utf-8-sig")

        self.assertEqual(result.valid_count, 1)
        self.assertEqual(result.status_counts["needs_review"], 1)
        self.assertIn("10.1016/j.actamat.2025.120001", merged_text)
        self.assertIn("Resolvable title only paper", preview_text)
        self.assertIn("Unmatched title only paper", preview_text)
        self.assertIn("metadata_confidence_below_threshold", preview_text)

    def test_build_intake_explicit_missing_doi_column_still_fails(self) -> None:
        from sd_institutional_skill import build_intake

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path = root / "title_only.csv"
            with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=["title"])
                writer.writeheader()
                writer.writerow({"title": "Title only should not override requested DOI column"})

            with self.assertRaises(ValueError):
                build_intake(
                    texts=[],
                    input_paths=[csv_path],
                    folder_paths=[],
                    output_dir=root / "out",
                    doi_column="missing_doi",
                    resolve_metadata=True,
                    http_json=lambda *_args, **_kwargs: {},
                )

    def test_build_intake_title_only_xlsx_resolves_when_openpyxl_available(self) -> None:
        try:
            from openpyxl import Workbook
        except ImportError:
            self.skipTest("openpyxl is not installed")

        from sd_institutional_skill import build_intake

        def fake_json(url: str, headers: dict[str, str] | None = None, timeout: int = 20) -> dict:
            decoded_url = unquote_plus(url)
            if "api.crossref.org/works?" in url and "XLSX title only paper" in decoded_url:
                return {
                    "message": {
                        "items": [
                            {
                                "DOI": "10.1016/j.scriptamat.2025.116001",
                                "title": ["XLSX title only paper"],
                                "author": [{"family": "Wang", "given": "Yu"}],
                                "container-title": ["Scripta Materialia"],
                                "published-online": {"date-parts": [[2025]]},
                                "publisher": "Elsevier",
                                "URL": "https://doi.org/10.1016/j.scriptamat.2025.116001",
                            }
                        ]
                    }
                }
            return {}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            xlsx_path = root / "title_only.xlsx"
            wb = Workbook()
            ws = wb.active
            ws.title = "Papers"
            ws.append(["title", "authors", "journal", "year"])
            ws.append(["XLSX title only paper", "Wang Yu", "Scripta Materialia", "2025"])
            wb.save(xlsx_path)
            wb.close()

            result = build_intake(
                texts=[],
                input_paths=[xlsx_path],
                folder_paths=[],
                output_dir=root / "out",
                resolve_metadata=True,
                http_json=fake_json,
            )

            merged_text = result.merged_input_path.read_text(encoding="utf-8-sig")
            preview_text = result.preview_path.read_text(encoding="utf-8-sig")

        self.assertEqual(result.valid_count, 1)
        self.assertIn("10.1016/j.scriptamat.2025.116001", merged_text)
        self.assertIn("XLSX title only paper", preview_text)

    def test_choose_output_root_falls_back_when_dialog_fails(self) -> None:
        from sd_institutional_skill import choose_output_root

        def failing_dialog() -> str:
            raise RuntimeError("no display")

        with tempfile.TemporaryDirectory() as tmp:
            selected = choose_output_root(tmp, dialog_func=failing_dialog)

        self.assertEqual(selected, Path(tmp).resolve())

    def test_build_intake_reads_gbk_csv_and_requested_excel_sheet(self) -> None:
        try:
            from openpyxl import Workbook
        except ImportError:
            self.skipTest("openpyxl is not installed")

        from sd_institutional_skill import build_intake

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path = root / "gbk.csv"
            with csv_path.open("w", newline="", encoding="gbk") as f:
                writer = csv.DictWriter(f, fieldnames=["题名", "DOI号"])
                writer.writeheader()
                writer.writerow({"题名": "中文题名", "DOI号": "10.1016/j.jallcom.2025.177000"})

            xlsx_path = root / "papers.xlsx"
            wb = Workbook()
            first = wb.active
            first.title = "Wrong"
            first.append(["title", "doi"])
            first.append(["Wrong", "10.1016/j.wrong.2024.1"])
            target = wb.create_sheet("Target")
            target.append(["标题", "DOI"])
            target.append(["Right", "10.1016/j.right.2024.2"])
            wb.save(xlsx_path)

            result = build_intake(
                texts=[],
                input_paths=[csv_path, xlsx_path],
                folder_paths=[],
                output_dir=root / "out",
                sheet_name="Target",
            )

            self.assertEqual(result.valid_count, 2)
            merged_text = result.merged_input_path.read_text(encoding="utf-8-sig")
            self.assertIn("中文题名", merged_text)
            self.assertIn("10.1016/j.right.2024.2", merged_text)
            self.assertNotIn("10.1016/j.wrong.2024.1", merged_text)


class InstitutionalSkillCookieTests(unittest.TestCase):
    def test_extract_devtools_cookies_and_cache_filters_relevant_domains(self) -> None:
        from sd_institutional_skill import cache_devtools_cookies

        class FakeResponse:
            def __init__(self, payload: dict[str, object]) -> None:
                self.payload = payload

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps(self.payload).encode("utf-8")

        class FakeWebSocket:
            def send(self, _payload: str) -> None:
                return None

            def recv(self) -> str:
                return json.dumps({
                    "id": 1,
                    "result": {
                        "cookies": [
                            {"domain": ".sciencedirect.com", "name": "SDMSESSION", "value": "secret"},
                            {"domain": ".elsevier.com", "name": "EUID", "value": "secret2"},
                            {"domain": ".example.com", "name": "other", "value": "nope"},
                        ]
                    },
                })

            def close(self) -> None:
                return None

        class FakeScraper:
            CHROME_DBG_PORT = 9222

            def _is_chrome_debug_ready(self) -> bool:
                return True

            def _launch_chrome_with_debug(self) -> None:
                raise AssertionError("Chrome should not be launched when already ready")

        def fake_opener(request: object, timeout: int = 0) -> FakeResponse:
            url = getattr(request, "full_url", str(request))
            if "/json/new" in url:
                return FakeResponse({"id": "tab-1", "webSocketDebuggerUrl": "ws://tab-1"})
            if "/json/close/" in url:
                return FakeResponse({})
            raise AssertionError(f"Unexpected URL: {url}")

        def fake_ws_connect(*_args: object, **_kwargs: object) -> FakeWebSocket:
            return FakeWebSocket()

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "_auth" / "sciencedirect_cookies.json"
            count = cache_devtools_cookies(
                FakeScraper(),
                cache_path,
                opener=fake_opener,
                websocket_connect=fake_ws_connect,
            )
            data = json.loads(cache_path.read_text(encoding="utf-8"))

        self.assertEqual(count, 2)
        self.assertEqual([item["domain"] for item in data], [".sciencedirect.com", ".elsevier.com"])
        self.assertNotIn(".example.com", json.dumps(data))

    def test_cookie_status_message_never_includes_cookie_values(self) -> None:
        from sd_institutional_skill import cookie_status_message, write_cookie_cache

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "sciencedirect_cookies.json"
            write_cookie_cache([
                {"domain": ".sciencedirect.com", "name": "SDMSESSION", "value": "super-secret"}
            ], cache_path)
            message = cookie_status_message(cache_path)

        self.assertIn("已缓存 1 个", message)
        self.assertNotIn("super-secret", message)

    def test_make_scraper_ignores_invalid_cookie_cache(self) -> None:
        from sd_institutional_skill import make_scraper

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "sciencedirect_cookies.json"
            cache_path.write_text("[]", encoding="utf-8")
            with patch("sd_institutional_skill.ScienceDirectScraper") as factory:
                make_scraper(cache_path)

        factory.assert_called_once_with(use_browser_cookies=True)


class InstitutionalSkillFilenameTests(unittest.TestCase):
    def test_sciencedirect_filename_uses_metadata_and_doi_hash(self) -> None:
        from sd_scraper import ScienceDirectScraper

        filename = ScienceDirectScraper._make_pdf_filename(
            1,
            {
                "year": "2024",
                "authors": "Zhang Wei; Li Qiang",
                "title": "A/B:C*D? gamma-TiAl alloy <test>",
                "doi": "10.1016/j.actamat.2024.119999",
            },
        )

        self.assertTrue(filename.startswith("2024_Zhang_A B C D gamma-TiAl alloy test_"))
        self.assertTrue(filename.endswith(".pdf"))
        self.assertNotRegex(filename, r'[<>:"/\\|?*]')


class ScienceDirectPdfAccessUrlTests(unittest.TestCase):
    def test_pdf_access_url_accepts_only_real_assets_or_viewer_wrappers(self) -> None:
        from sd_scraper import is_sciencedirect_pdf_access_url

        accepted = [
            "https://pdf.sciencedirectassets.com/271429/1-s2.0-S1359645424000012-main.pdf",
            (
                "chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai/index.html"
                "?src=https%3A%2F%2Fpdf.sciencedirectassets.com%2F271429%2Fmain.pdf"
            ),
            (
                "edge://pdf-viewer/index.html"
                "?src=https%3A%2F%2Fpdf.sciencedirectassets.com%2F271429%2Fmain.pdf"
            ),
            (
                "chrome://pdf-viewer/index.html"
                "?src=https%3A%2F%2Fpdf.sciencedirectassets.com%2F271429%2Fmain.pdf"
            ),
        ]
        rejected = [
            "",
            "http://pdf.sciencedirectassets.com/271429/main.pdf",
            "ftp://pdf.sciencedirectassets.com/271429/main.pdf",
            "https://www.sciencedirect.com/science/article/pii/S1359645424000012/pdfft",
            "https://www.sciencedirect.com/science/article/pii/S1359645424000012",
            "https://id.elsevier.com/as/authorization.oauth2?client_id=sciencedirect",
            "https://cas.example.edu/login?service=https%3A%2F%2Fwww.sciencedirect.com%2F",
            "https://example.com/not-a-real-pdf-route",
            (
                "chrome://settings/?q="
                "https%3A%2F%2Fpdf.sciencedirectassets.com%2F271429%2Fmain.pdf"
            ),
            (
                "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/index.html"
                "?src=https%3A%2F%2Fpdf.sciencedirectassets.com%2F271429%2Fmain.pdf"
            ),
            (
                "chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai/index.html"
                "?src=https%3A%2F%2Fwww.sciencedirect.com%2Fscience%2Farticle%2Fpii%2FS1359645424000012%2Fpdfft"
            ),
        ]

        for url in accepted:
            with self.subTest(url=url):
                self.assertTrue(is_sciencedirect_pdf_access_url(url))
        for url in rejected:
            with self.subTest(url=url):
                self.assertFalse(is_sciencedirect_pdf_access_url(url))


if __name__ == "__main__":
    unittest.main()
