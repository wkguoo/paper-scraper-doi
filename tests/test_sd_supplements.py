from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class FakeStreamingResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        chunks: list[bytes] | None = None,
        content: bytes | None = None,
        forbid_content: bool = False,
        iter_error: Exception | None = None,
        iter_error_after_chunks: int = 0,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = list(chunks or [])
        self._content = content
        self._forbid_content = forbid_content
        self._iter_error = iter_error
        self._iter_error_after_chunks = iter_error_after_chunks
        self.content_accessed = False
        self.iter_content_called = False
        self.iter_content_chunk_size = None
        self.iterated_chunks = 0
        self.closed = False

    @property
    def content(self) -> bytes:
        self.content_accessed = True
        if self._forbid_content:
            raise AssertionError("response.content should not be read")
        if self._content is not None:
            return self._content
        return b"".join(self._chunks)

    def iter_content(self, chunk_size: int = 1):
        self.iter_content_called = True
        self.iter_content_chunk_size = chunk_size
        for chunk in self._chunks:
            if self._iter_error is not None and self.iterated_chunks >= self._iter_error_after_chunks:
                raise self._iter_error
            self.iterated_chunks += 1
            yield chunk
        if self._iter_error is not None and self.iterated_chunks >= self._iter_error_after_chunks:
            raise self._iter_error

    def close(self) -> None:
        self.closed = True


class FakeSession:
    def __init__(self, responses: list[FakeStreamingResponse] | None = None) -> None:
        self._responses = list(responses or [])
        self.calls: list[dict] = []

    def get(self, url: str, **kwargs):
        self.calls.append({"url": url, "kwargs": kwargs})
        if not self._responses:
            raise RuntimeError("unexpected GET")
        return self._responses.pop(0)


class MappingLikeHeaders:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values

    def get(self, key: str, default: str = "") -> str:
        for header, value in self.values.items():
            if header.lower() == key.lower():
                return value
        return default


def _sample_article() -> dict[str, str]:
    return {
        "doi": "10.1016/j.actamat.2024.119999",
        "pii": "S1359645424000012",
        "title": "Supplement Test Paper",
        "year": "2024",
        "authors": "Zhang Wei; Li Qiang",
    }


def _article_html(url: str, title: str = "Supplementary dataset") -> str:
    return f'<html><body><a href="{url}">{title}</a></body></html>'


def _download_one(
    *,
    output_dir: Path,
    session,
    url: str = "https://ars.els-cdn.com/content/image/1-s2.0-S1359645424000012-mmc1.xlsx",
    title: str = "Supplementary dataset",
):
    from sd_supplements import download_supplements_for_article, make_article_stem

    article = _sample_article()
    records = download_supplements_for_article(
        article=article,
        article_index=1,
        article_file="paper.pdf",
        article_html=_article_html(url, title),
        article_url="https://www.sciencedirect.com/science/article/pii/S1359645424000012",
        output_dir=output_dir,
        session=session,
    )
    supplement_dir = output_dir / "supplements" / make_article_stem(1, article)
    return records, supplement_dir


class ScienceDirectSupplementHelperTests(unittest.TestCase):
    def test_extracts_sciencedirect_supplement_links_and_deduplicates_urls(self) -> None:
        from sd_supplements import extract_supplement_candidates

        html = """
        <html><body>
          <a href="https://ars.els-cdn.com/content/image/1-s2.0-S1359645424000012-mmc1.docx">
            Supplementary material 1
          </a>
          <a href="https://ars.els-cdn.com/content/image/1-s2.0-S1359645424000012-mmc1.docx">
            Download
          </a>
          <a href="/science/article/pii/S1359645424000012/mmc2">
            Appendix A. Raw diffraction data
          </a>
          <a href="https://example.com/mmc3.pdf">Supplementary mirror</a>
          <a href="https://www.sciencedirect.com/science/article/pii/S1359645424000012">
            Article page
          </a>
        </body></html>
        """

        candidates = extract_supplement_candidates(
            html,
            "https://www.sciencedirect.com/science/article/pii/S1359645424000012",
        )

        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0].title, "Supplementary material 1")
        self.assertEqual(
            candidates[0].url,
            "https://ars.els-cdn.com/content/image/1-s2.0-S1359645424000012-mmc1.docx",
        )
        self.assertEqual(candidates[1].title, "Appendix A. Raw diffraction data")
        self.assertEqual(
            candidates[1].url,
            "https://www.sciencedirect.com/science/article/pii/S1359645424000012/mmc2",
        )

    def test_extract_ignores_non_supplement_download_links(self) -> None:
        from sd_supplements import extract_supplement_candidates

        html = """
        <html><body>
          <a href="/science/article/pii/S1359645424000012/export?format=ris">
            Download citation
          </a>
          <a href="https://ars.els-cdn.com/content/image/1-s2.0-S1359645424000012-gr1_lrg.jpg">
            Download full-size image
          </a>
          <a href="/science/article/pii/S1359645424000012/pdfft?download=true">
            Download PDF
          </a>
          <a href="https://ars.els-cdn.com/content/image/1-s2.0-S1359645424000012-mmc1.xlsx">
            Supplementary data
          </a>
        </body></html>
        """

        candidates = extract_supplement_candidates(
            html,
            "https://www.sciencedirect.com/science/article/pii/S1359645424000012",
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].title, "Supplementary data")
        self.assertIn("-mmc1.xlsx", candidates[0].url)

    def test_article_stem_and_supplement_filename_are_windows_safe(self) -> None:
        from sd_supplements import SupplementCandidate, make_article_stem, make_supplement_filename

        article = {
            "year": "2024",
            "authors": "Zhang Wei; Li Qiang",
            "title": "A/B:C*D? gamma-TiAl alloy <test>",
            "doi": "10.1016/j.actamat.2024.119999",
        }
        stem = make_article_stem(1, article)
        filename = make_supplement_filename(
            1,
            SupplementCandidate(
                url="https://ars.els-cdn.com/content/image/1-s2.0-S1359645424000012-mmc1.docx",
                title='Supplementary / dataset: "raw"',
            ),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

        self.assertTrue(stem.startswith("2024_Zhang_A B C D gamma-TiAl alloy test_"))
        self.assertNotIn(".pdf", stem)
        self.assertNotRegex(stem, r'[<>:"/\\|?*]')
        self.assertEqual(filename, "S01_Supplementary dataset raw.docx")
        self.assertNotRegex(filename, r'[<>:"/\\|?*]')

    def test_extracts_deduplicates_tracking_query_variants(self) -> None:
        from sd_supplements import extract_supplement_candidates

        html = """
        <html><body>
          <a href="https://ars.els-cdn.com/content/image/1-s2.0-S1359645424000012-mmc1.pdf?download=true&dgcid=raven_sd_via_email">
            Supplementary material 1
          </a>
          <a href="https://ars.els-cdn.com/content/image/1-s2.0-S1359645424000012-mmc1.pdf?download=true&X-Amz-Signature=abc123">
            Supplementary material 1 duplicate
          </a>
        </body></html>
        """

        candidates = extract_supplement_candidates(
            html,
            "https://www.sciencedirect.com/science/article/pii/S1359645424000012",
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(
            candidates[0].url,
            "https://ars.els-cdn.com/content/image/1-s2.0-S1359645424000012-mmc1.pdf?download=true&dgcid=raven_sd_via_email",
        )


class ScienceDirectSupplementDownloadTests(unittest.TestCase):
    def test_existing_exact_file_skips_without_get(self) -> None:
        from sd_supplements import SupplementCandidate, make_article_stem, make_supplement_filename

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            article = _sample_article()
            url = "https://ars.els-cdn.com/content/image/1-s2.0-S1359645424000012-mmc1.xlsx"
            title = "Supplementary dataset"
            stem = make_article_stem(1, article)
            supplement_dir = output_dir / "supplements" / stem
            supplement_dir.mkdir(parents=True)
            filename = make_supplement_filename(1, SupplementCandidate(url=url, title=title), "")
            target = supplement_dir / filename
            target.write_bytes(b"cached bytes")
            session = FakeSession()

            records, _ = _download_one(output_dir=output_dir, session=session, url=url, title=title)

        self.assertEqual(session.calls, [])
        self.assertEqual(records[0].status, "skipped")
        self.assertEqual(Path(records[0].file).name, filename)
        self.assertEqual(records[0].size_bytes, len(b"cached bytes"))
        self.assertTrue(records[0].reason)
        self.assertEqual(records[0].content_type, "")

    def test_empty_existing_file_does_not_skip_without_get(self) -> None:
        from sd_supplements import SupplementCandidate, make_article_stem, make_supplement_filename

        response = FakeStreamingResponse(
            headers={"Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
            chunks=[b"real workbook"],
            forbid_content=True,
        )
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            article = _sample_article()
            url = "https://ars.els-cdn.com/content/image/1-s2.0-S1359645424000012-mmc1.xlsx"
            title = "Supplementary dataset"
            stem = make_article_stem(1, article)
            supplement_dir = output_dir / "supplements" / stem
            supplement_dir.mkdir(parents=True)
            filename = make_supplement_filename(1, SupplementCandidate(url=url, title=title), "")
            target = supplement_dir / filename
            target.write_bytes(b"")
            session = FakeSession([response])

            records, _ = _download_one(output_dir=output_dir, session=session, url=url, title=title)
            target_bytes = target.read_bytes()

        self.assertEqual(len(session.calls), 1)
        self.assertEqual(records[0].status, "success")
        self.assertEqual(records[0].size_bytes, len(b"real workbook"))
        self.assertEqual(target_bytes, b"real workbook")

    def test_existing_extensionless_candidate_skips_by_prefix_without_get(self) -> None:
        from sd_supplements import make_article_stem

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            title = "Appendix A raw data"
            stem = make_article_stem(1, _sample_article())
            supplement_dir = output_dir / "supplements" / stem
            supplement_dir.mkdir(parents=True)
            cached = supplement_dir / "S01_Appendix A raw data.xlsx"
            cached.write_bytes(b"cached workbook")
            session = FakeSession()

            records, _ = _download_one(
                output_dir=output_dir,
                session=session,
                url="https://www.sciencedirect.com/science/article/pii/S1359645424000012/mmc1?download=true",
                title=title,
            )

        self.assertEqual(session.calls, [])
        self.assertEqual(records[0].status, "skipped")
        self.assertEqual(Path(records[0].file).name, cached.name)
        self.assertEqual(records[0].size_bytes, len(b"cached workbook"))
        self.assertTrue(records[0].reason)

    def test_download_streams_chunks_without_reading_response_content(self) -> None:
        response = FakeStreamingResponse(
            headers={"Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
            chunks=[b"abc", b"", b"def"],
            forbid_content=True,
        )
        session = FakeSession([response])

        with tempfile.TemporaryDirectory() as tmp:
            records, supplement_dir = _download_one(output_dir=Path(tmp), session=session)
            saved = supplement_dir / Path(records[0].file).name
            saved_bytes = saved.read_bytes()

        self.assertEqual(records[0].status, "success")
        self.assertEqual(saved_bytes, b"abcdef")
        self.assertFalse(response.content_accessed)
        self.assertTrue(response.iter_content_called)
        self.assertEqual(session.calls[0]["kwargs"].get("stream"), True)

    def test_mapping_like_headers_provide_content_type_and_extension(self) -> None:
        response = FakeStreamingResponse(
            headers=MappingLikeHeaders({"content-type": "application/zip; charset=binary"}),
            chunks=[b"PK\x03\x04dataset"],
            forbid_content=True,
        )
        session = FakeSession([response])

        with tempfile.TemporaryDirectory() as tmp:
            records, supplement_dir = _download_one(
                output_dir=Path(tmp),
                session=session,
                url="https://www.sciencedirect.com/science/article/pii/S1359645424000012/mmc1",
                title="Supplementary archive",
            )
            saved_files = list(supplement_dir.iterdir())

        self.assertEqual(records[0].status, "success")
        self.assertEqual(records[0].content_type, "application/zip")
        self.assertTrue(records[0].file.endswith(".zip"))
        self.assertEqual(saved_files[0].suffix, ".zip")

    def test_html_content_type_is_rejected_without_reading_body(self) -> None:
        response = FakeStreamingResponse(
            headers={"Content-Type": "text/html; charset=utf-8"},
            chunks=[b"<html><title>Sign in</title></html>"],
            forbid_content=True,
        )
        session = FakeSession([response])

        with tempfile.TemporaryDirectory() as tmp:
            records, supplement_dir = _download_one(output_dir=Path(tmp), session=session)
            files = list(supplement_dir.iterdir()) if supplement_dir.exists() else []

        self.assertEqual(records[0].status, "failed")
        self.assertEqual(records[0].content_type, "text/html")
        self.assertEqual(files, [])
        self.assertFalse(response.content_accessed)
        self.assertFalse(response.iter_content_called)
        self.assertTrue(response.closed)

    def test_login_captcha_access_denied_html_is_sniffed_from_non_html_content_type(self) -> None:
        response = FakeStreamingResponse(
            headers={"Content-Type": "application/octet-stream"},
            chunks=[
                b"  <body>Please login to continue. CAPTCHA required. Access denied.</body>",
                b"fake attachment payload",
            ],
            forbid_content=True,
        )
        session = FakeSession([response])

        with tempfile.TemporaryDirectory() as tmp:
            records, supplement_dir = _download_one(output_dir=Path(tmp), session=session)
            files = list(supplement_dir.iterdir()) if supplement_dir.exists() else []

        self.assertEqual(records[0].status, "failed")
        self.assertEqual(files, [])
        self.assertTrue(response.iter_content_called)
        self.assertEqual(response.iterated_chunks, 1)
        self.assertFalse(response.content_accessed)
        self.assertTrue(response.closed)

    def test_plain_access_denied_body_is_rejected_without_html_tags(self) -> None:
        response = FakeStreamingResponse(
            headers={"Content-Type": "application/octet-stream"},
            chunks=[b"AccessDenied: CAPTCHA required before download"],
            forbid_content=True,
        )
        session = FakeSession([response])

        with tempfile.TemporaryDirectory() as tmp:
            records, supplement_dir = _download_one(output_dir=Path(tmp), session=session)
            files = list(supplement_dir.iterdir()) if supplement_dir.exists() else []

        self.assertEqual(records[0].status, "failed")
        self.assertEqual(files, [])
        self.assertTrue(response.iter_content_called)
        self.assertEqual(response.iterated_chunks, 1)
        self.assertFalse(response.content_accessed)
        self.assertTrue(response.closed)

    def test_http_failure_records_failed_and_leaves_no_temp_file(self) -> None:
        response = FakeStreamingResponse(
            status_code=403,
            headers={"Content-Type": "application/pdf"},
            chunks=[b"%PDF"],
            forbid_content=True,
        )
        session = FakeSession([response])

        with tempfile.TemporaryDirectory() as tmp:
            records, supplement_dir = _download_one(output_dir=Path(tmp), session=session)
            temp_files = list(supplement_dir.glob("*.tmp")) if supplement_dir.exists() else []

        self.assertEqual(records[0].status, "failed")
        self.assertIn("HTTP 403", records[0].reason)
        self.assertEqual(records[0].content_type, "application/pdf")
        self.assertEqual(temp_files, [])
        self.assertFalse(response.content_accessed)
        self.assertFalse(response.iter_content_called)
        self.assertTrue(response.closed)

    def test_stream_write_failure_removes_temp_file_and_records_failed(self) -> None:
        response = FakeStreamingResponse(
            headers={"Content-Type": "application/pdf"},
            chunks=[b"%PDF-1.7\n"],
            forbid_content=True,
            iter_error=OSError("stream exploded"),
            iter_error_after_chunks=1,
        )
        session = FakeSession([response])

        with tempfile.TemporaryDirectory() as tmp:
            records, supplement_dir = _download_one(output_dir=Path(tmp), session=session)
            files = list(supplement_dir.iterdir()) if supplement_dir.exists() else []

        self.assertEqual(records[0].status, "failed")
        self.assertIn("stream exploded", records[0].reason)
        self.assertEqual(files, [])
        self.assertTrue(response.iter_content_called)
        self.assertFalse(response.content_accessed)
        self.assertTrue(response.closed)

    def test_success_record_contains_relative_file_content_type_size_and_source_url(self) -> None:
        url = "https://ars.els-cdn.com/content/image/1-s2.0-S1359645424000012-mmc1.zip?download=true"
        response = FakeStreamingResponse(
            headers={"Content-Type": "application/zip"},
            chunks=[b"PK", b"\x03\x04data"],
            forbid_content=True,
        )
        session = FakeSession([response])

        with tempfile.TemporaryDirectory() as tmp:
            records, supplement_dir = _download_one(output_dir=Path(tmp), session=session, url=url)
            saved = supplement_dir / Path(records[0].file).name
            saved_exists = saved.exists()

        record = records[0]
        self.assertEqual(record.status, "success")
        self.assertFalse(Path(record.file).is_absolute())
        self.assertEqual(Path(record.file).parts[0], "supplements")
        self.assertEqual(record.content_type, "application/zip")
        self.assertEqual(record.size_bytes, len(b"PK\x03\x04data"))
        self.assertEqual(record.source_url, url)
        self.assertTrue(saved_exists)


class ScienceDirectSupplementReportTests(unittest.TestCase):
    def test_writes_supplement_report_and_summary_counts(self) -> None:
        from doi_batch_utils import (
            RunSummary,
            SupplementDownloadRecord,
            write_run_summary,
            write_run_summary_json,
            write_supplement_download_report,
        )

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            report_path = write_supplement_download_report(
                [
                    SupplementDownloadRecord(
                        doi="10.1016/j.actamat.2024.119999",
                        pii="S1359645424000012",
                        article_title="Paper",
                        article_file="2024_Zhang_Paper_12345678.pdf",
                        supplement_index=1,
                        supplement_title="Supplementary material",
                        source_url="https://ars.els-cdn.com/content/image/mmc1.docx",
                        status="success",
                        file="supplements/2024_Zhang_Paper_12345678/S01_Supplementary material.docx",
                        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        size_bytes=1234,
                    )
                ],
                out,
            )
            summary = RunSummary(
                input_path="papers.csv",
                output_dir=str(out),
                total_doi=1,
                resolved_count=1,
                failure_reasons={},
                pdf_success=1,
                pdf_failed=0,
                pdf_skipped=0,
                supplement_success=1,
                supplement_failed=0,
                supplement_skipped=0,
                supplement_not_found=0,
                supplement_report_path=str(report_path),
            )
            summary_txt = write_run_summary(summary)
            summary_json = write_run_summary_json(summary)

            with report_path.open("r", encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
            summary_text = summary_txt.read_text(encoding="utf-8")
            summary_data = summary_json.read_text(encoding="utf-8")

        self.assertEqual(rows[0]["status"], "success")
        self.assertEqual(rows[0]["size_bytes"], "1234")
        self.assertIn("补充材料下载:", summary_text)
        self.assertIn("- 成功: 1", summary_text)
        self.assertIn("Supplement 下载报告", summary_text)
        self.assertIn('"supplement_success": 1', summary_data)
        self.assertIn("supplement_download_report.csv", str(report_path))


if __name__ == "__main__":
    unittest.main()
