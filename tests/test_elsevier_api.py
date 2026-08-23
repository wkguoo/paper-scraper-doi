from __future__ import annotations

import io
import csv
import os
import socket
import tempfile
import unittest
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request
from unittest.mock import patch

from paper_automation.elsevier_api import (
    API_ROOT,
    ElsevierApiClient,
    ElsevierApiResult,
    ElsevierAttachment,
    ElsevierXmlResult,
    HttpResponse,
    StreamHttpResponse,
)
from paper_automation.pdf_validation import minimal_pdf_bytes
from sd_institutional_skill import IntakeRow, run_elsevier_api_phase, write_elsevier_api_attempt_report


FULL_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<full-text-retrieval-response xmlns:dc="http://purl.org/dc/elements/1.1/"
    xmlns:prism="http://prismstandard.org/namespaces/basic/2.0/"
    xmlns:xocs="http://www.elsevier.com/xml/xocs/dtd">
  <coredata>
    <dc:title>API-first titanium paper</dc:title>
    <dc:creator>Zhang Wei</dc:creator>
    <dc:creator>Li Ming</dc:creator>
    <prism:publicationName>Acta Materialia</prism:publicationName>
    <prism:coverDate>2016-10-15</prism:coverDate>
    <pii>S1359645416306327</pii>
  </coredata>
  <xocs:attachment-metadata-doc>
    <xocs:web-pdf>
      <xocs:web-pdf-purpose>MAIN</xocs:web-pdf-purpose>
      <xocs:attachment-eid>1-s2.0-S1359645416306327-main.pdf</xocs:attachment-eid>
      <xocs:filename>main.pdf</xocs:filename>
    </xocs:web-pdf>
    <xocs:attachment>
      <xocs:eid>1-s2.0-S1359645416306327-mmc1.pdf</xocs:eid>
      <xocs:filename>appendix.pdf</xocs:filename>
      <xocs:type>APPLICATION</xocs:type>
      <xocs:mimetype>application/pdf</xocs:mimetype>
    </xocs:attachment>
  </xocs:attachment-metadata-doc>
</full-text-retrieval-response>"""


META_XML = b"""<?xml version="1.0"?>
<attachment-metadata-response xmlns:a="urn:elsevier:test">
  <a:attachment>
    <a:eid>1-s2.0-S1359645416306327-main.pdf</a:eid>
    <a:filename>main.pdf</a:filename>
    <a:type>IMAGE-WEB-PDF</a:type>
    <a:mimetype>application/pdf</a:mimetype>
  </a:attachment>
  <a:attachment>
    <a:eid>1-s2.0-S1359645416306327-mmc1.pdf</a:eid>
    <a:filename>mmc1.pdf</a:filename>
    <a:type>APPLICATION</a:type>
    <a:mimetype>application/pdf</a:mimetype>
    <a:size>1234</a:size>
  </a:attachment>
  <a:attachment>
    <a:eid>1-s2.0-S1359645416306327-mmc2.zip</a:eid>
    <a:filename>appendix.zip</a:filename>
    <a:type>APPLICATION</a:type>
    <a:mimetype>application/zip</a:mimetype>
  </a:attachment>
  <a:attachment>
    <a:eid>1-s2.0-inline-image.jpg</a:eid>
    <a:filename>figure1.jpg</a:filename>
    <a:type>HIGH-RES</a:type>
    <a:mimetype>image/jpeg</a:mimetype>
  </a:attachment>
  <a:attachment>
    <a:eid>1-s2.0-supp-video.mp4</a:eid>
    <a:filename>supplement-video.mp4</a:filename>
    <a:type>VIDEO</a:type>
    <a:mimetype>video/mp4</a:mimetype>
  </a:attachment>
  <a:attachment>
    <a:eid>1-s2.0-supp-video.mp4</a:eid>
    <a:filename>duplicate.mp4</a:filename>
    <a:type>VIDEO</a:type>
  </a:attachment>
</attachment-metadata-response>"""


class QueueTransport:
    def __init__(self, responses: list[HttpResponse | BaseException]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, str], float]] = []

    def __call__(self, url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
        self.calls.append((url, dict(headers), timeout))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class ElsevierApiClientTests(unittest.TestCase):
    def test_xml_only_returns_raw_full_xml_without_pdf_request(self) -> None:
        transport = QueueTransport([HttpResponse(200, {"Content-Type": "text/xml"}, FULL_XML)])
        result = ElsevierApiClient(api_key="key", transport=transport).retrieve_article_xml(
            "10.1016/j.actamat.2016.08.081"
        )

        self.assertIsInstance(result, ElsevierXmlResult)
        self.assertEqual(result.status, "success")
        self.assertEqual(result.xml_bytes, FULL_XML)
        self.assertEqual(result.title, "API-first titanium paper")
        self.assertEqual(result.authors, ("Zhang Wei", "Li Ming"))
        self.assertEqual(result.year, "2016")
        self.assertEqual(len(transport.calls), 1)
        self.assertIn("/content/article/doi/", transport.calls[0][0])
        self.assertNotIn("/content/object/", transport.calls[0][0])

    def test_xml_only_accepts_scopus_id_and_strips_eid_prefix(self) -> None:
        transport = QueueTransport([HttpResponse(200, {"Content-Type": "application/xml"}, FULL_XML)])
        result = ElsevierApiClient(api_key="key", transport=transport).retrieve_article_xml(
            "2-s2.0-0026985040",
            identifier_type="scopus_id",
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.scopus_id, "0026985040")
        self.assertIn("/content/article/scopus_id/0026985040?view=FULL", transport.calls[0][0])

    def test_xml_only_rejects_pdf_html_and_non_article_xml(self) -> None:
        responses = (
            HttpResponse(200, {"Content-Type": "application/pdf"}, minimal_pdf_bytes()),
            HttpResponse(200, {"Content-Type": "text/html"}, b"<html>login</html>"),
            HttpResponse(200, {"Content-Type": "text/xml"}, b"<service-error/>"),
        )
        for response in responses:
            with self.subTest(content_type=response.headers.get("Content-Type")):
                result = ElsevierApiClient(
                    api_key="key", transport=QueueTransport([response])
                ).retrieve_article_xml("10.1016/example")
                self.assertEqual(result.status, "invalid_xml")
                self.assertEqual(result.xml_bytes, b"")

    def test_xml_only_preserves_http_status_mapping(self) -> None:
        for http_status, status in ((401, "unauthorized"), (403, "not_entitled"), (404, "not_found"), (429, "rate_limited"), (503, "network_error")):
            with self.subTest(http_status=http_status):
                result = ElsevierApiClient(
                    api_key="key",
                    transport=QueueTransport([HttpResponse(http_status, {}, b"")]),
                ).retrieve_article_xml("10.1016/example")
                self.assertEqual(result.status, status)
                self.assertEqual(result.http_status, http_status)

    def test_full_xml_selects_main_pdf_and_metadata(self) -> None:
        pdf = minimal_pdf_bytes(b"article")
        transport = QueueTransport(
            [
                HttpResponse(200, {"Content-Type": "text/xml"}, FULL_XML),
                HttpResponse(200, {"Content-Type": "application/pdf"}, pdf),
            ]
        )
        client = ElsevierApiClient(api_key="sentinel-key", transport=transport)

        result = client.download_article("10.1016/j.actamat.2016.08.081", include_supplements=False)

        self.assertEqual(result.status, "success")
        self.assertTrue(result.full_xml_received)
        self.assertEqual(result.attachment_eid, "1-s2.0-S1359645416306327-main.pdf")
        self.assertEqual(result.pii, "S1359645416306327")
        self.assertEqual(result.year, "2016")
        self.assertEqual(result.authors, ("Zhang Wei", "Li Ming"))
        self.assertEqual(result.pdf_bytes, pdf)
        self.assertNotIn("sentinel-key", transport.calls[0][0])

    def test_namespace_change_does_not_break_main_eid_selection(self) -> None:
        xml = FULL_XML.replace(b"http://www.elsevier.com/xml/xocs/dtd", b"urn:changed")
        transport = QueueTransport(
            [
                HttpResponse(200, {"Content-Type": "application/xml"}, xml),
                HttpResponse(200, {"Content-Type": "application/pdf"}, minimal_pdf_bytes()),
            ]
        )
        result = ElsevierApiClient(api_key="key", transport=transport).download_article(
            "10.1016/example", include_supplements=False
        )
        self.assertEqual(result.status, "success")
        self.assertTrue(result.attachment_eid.endswith("-main.pdf"))

    def test_supplement_or_appendix_is_never_selected_as_main_pdf(self) -> None:
        xml = b"""<root><attachment><eid>paper-mmc-main.pdf</eid><filename>appendix.pdf</filename>
        <type>APPLICATION</type></attachment></root>"""
        transport = QueueTransport([HttpResponse(200, {"Content-Type": "text/xml"}, xml)])
        result = ElsevierApiClient(api_key="key", transport=transport).download_article(
            "10.1016/example", include_supplements=False
        )
        self.assertEqual(result.status, "no_main_pdf")
        self.assertEqual(len(transport.calls), 1)

    def test_ambiguous_main_pdf_returns_no_main_pdf(self) -> None:
        xml = b"""<root>
        <web-pdf><web-pdf-purpose>MAIN</web-pdf-purpose><attachment-eid>a-main.pdf</attachment-eid></web-pdf>
        <web-pdf><web-pdf-purpose>MAIN</web-pdf-purpose><attachment-eid>b-main.pdf</attachment-eid></web-pdf>
        </root>"""
        result = ElsevierApiClient(
            api_key="key", transport=QueueTransport([HttpResponse(200, {"Content-Type": "text/xml"}, xml)])
        ).download_article("10.1016/example", include_supplements=False)
        self.assertEqual(result.status, "no_main_pdf")

    def test_article_endpoint_may_return_pdf_directly(self) -> None:
        pdf = minimal_pdf_bytes(b"direct")
        result = ElsevierApiClient(
            api_key="key",
            transport=QueueTransport([HttpResponse(200, {"Content-Type": "application/pdf"}, pdf)]),
        ).download_article("10.1016/example", include_supplements=False)
        self.assertEqual(result.status, "success")
        self.assertEqual(result.pdf_bytes, pdf)
        self.assertFalse(result.full_xml_received)

    def test_html_or_truncated_pdf_is_invalid(self) -> None:
        html_result = ElsevierApiClient(
            api_key="key",
            transport=QueueTransport([HttpResponse(200, {"Content-Type": "text/html"}, b"<html>login</html>")]),
        ).download_article("10.1016/html", include_supplements=False)
        self.assertEqual(html_result.status, "invalid_pdf")

        truncated_transport = QueueTransport(
            [
                HttpResponse(200, {"Content-Type": "text/xml"}, FULL_XML),
                HttpResponse(200, {"Content-Type": "application/pdf"}, b"%PDF-1.7\ntruncated"),
            ]
        )
        truncated_result = ElsevierApiClient(api_key="key", transport=truncated_transport).download_article(
            "10.1016/truncated", include_supplements=False
        )
        self.assertEqual(truncated_result.status, "invalid_pdf")

    def test_http_status_mapping(self) -> None:
        expected = {401: "unauthorized", 403: "not_entitled", 404: "not_found", 429: "rate_limited", 503: "network_error"}
        for http_status, status in expected.items():
            with self.subTest(http_status=http_status):
                result = ElsevierApiClient(
                    api_key="key", transport=QueueTransport([HttpResponse(http_status, {}, b"")])
                ).download_article("10.1016/example")
                self.assertEqual(result.status, status)
                self.assertEqual(result.http_status, http_status)

    def test_timeout_and_network_error_are_safe(self) -> None:
        for error in (socket.timeout("secret details"), OSError("sentinel-key: DNS details")):
            with self.subTest(error=type(error).__name__):
                result = ElsevierApiClient(
                    api_key="sentinel-key", transport=QueueTransport([error])
                ).download_article("10.1016/example")
                self.assertEqual(result.status, "network_error")
                self.assertNotIn("sentinel-key", result.reason)

    def test_api_key_missing_does_not_call_transport(self) -> None:
        transport = QueueTransport([])
        with patch.dict(os.environ, {}, clear=True):
            result = ElsevierApiClient(transport=transport).download_article("10.1016/example")
        self.assertEqual(result.status, "api_key_missing")
        self.assertEqual(transport.calls, [])

    def test_insttoken_header_is_optional_and_credentials_never_enter_url(self) -> None:
        for token, expected in (("", False), ("sentinel-token", True)):
            with self.subTest(insttoken=expected):
                transport = QueueTransport([HttpResponse(404, {}, b"")])
                client = ElsevierApiClient(api_key="sentinel-key", insttoken=token, transport=transport)
                client.download_article("10.1016/example")
                url, headers, _ = transport.calls[0]
                self.assertEqual(headers["X-ELS-APIKey"], "sentinel-key")
                self.assertEqual("X-ELS-Insttoken" in headers, expected)
                self.assertNotIn("sentinel-key", url)
                self.assertNotIn("sentinel-token", url)
                self.assertTrue(url.startswith(API_ROOT + "/"))

    def test_cross_host_redirect_strips_credentials_and_http_redirect_is_rejected(self) -> None:
        from paper_automation.elsevier_api import _CredentialSafeRedirectHandler

        handler = _CredentialSafeRedirectHandler()
        request = Request(
            API_ROOT + "/content/article/doi/example",
            headers={"X-ELS-APIKey": "sentinel-key", "X-ELS-Insttoken": "sentinel-token"},
        )
        redirected = handler.redirect_request(
            request, None, 302, "Found", {}, "https://objects.example.org/article.pdf"
        )
        self.assertIsNotNone(redirected)
        redirected_headers = {key.lower(): value for key, value in redirected.header_items()}
        self.assertNotIn("x-els-apikey", redirected_headers)
        self.assertNotIn("x-els-insttoken", redirected_headers)
        with self.assertRaises(URLError):
            handler.redirect_request(request, None, 302, "Found", {}, "http://api.elsevier.com/insecure")

    def test_meta_filters_main_inline_images_and_duplicates(self) -> None:
        transport = QueueTransport([HttpResponse(200, {"Content-Type": "text/xml"}, META_XML)])
        result = ElsevierApiClient(api_key="key", transport=transport).list_supplements(
            "10.1016/example", main_eid="1-s2.0-S1359645416306327-main.pdf"
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(
            [item.eid for item in result.attachments],
            [
                "1-s2.0-S1359645416306327-mmc1.pdf",
                "1-s2.0-S1359645416306327-mmc2.zip",
                "1-s2.0-supp-video.mp4",
            ],
        )

    def test_official_attachment_field_aliases_are_supported(self) -> None:
        xml = b"""<root><attachment>
        <attachment-eid>1-s2.0-test-mmc1.docx</attachment-eid>
        <attachment-filename>supplement.docx</attachment-filename>
        <attachment-type>APPLICATION</attachment-type>
        <attachment-mime-type>application/vnd.openxmlformats-officedocument.wordprocessingml.document</attachment-mime-type>
        <attachment-size>42</attachment-size>
        </attachment></root>"""
        result = ElsevierApiClient(
            api_key="key", transport=QueueTransport([HttpResponse(200, {"Content-Type": "text/xml"}, xml)])
        ).list_supplements("10.1016/example")
        self.assertEqual(result.status, "success")
        self.assertEqual(result.attachments[0].filename, "supplement.docx")
        self.assertEqual(result.attachments[0].size_bytes, 42)

    def test_xml_body_object_is_excluded_from_supplements(self) -> None:
        xml = b"""<root><attachment><attachment-eid>article.xml</attachment-eid>
        <attachment-filename>article.xml</attachment-filename><attachment-type>APPLICATION</attachment-type>
        <attachment-mime-type>application/xml</attachment-mime-type></attachment></root>"""
        result = ElsevierApiClient(
            api_key="key", transport=QueueTransport([HttpResponse(200, {"Content-Type": "text/xml"}, xml)])
        ).list_supplements("10.1016/example")
        self.assertEqual(result.status, "success")
        self.assertEqual(result.attachments, ())

    def test_stream_attachment_accepts_binary_and_rejects_html(self) -> None:
        attachment = ElsevierAttachment(eid="1-s2.0-mmc1.zip", mime_type="application/zip")

        def binary_stream(url, headers, timeout, sink):
            self.assertNotIn("key", url)
            sink.write(b"PK\x03\x04supplement")
            return StreamHttpResponse(200, {"Content-Type": "application/zip"}, 14, url)

        binary_sink = io.BytesIO()
        binary_result = ElsevierApiClient(api_key="key", stream_transport=binary_stream).stream_attachment(
            attachment, binary_sink
        )
        self.assertEqual(binary_result.status, "success")
        self.assertTrue(binary_sink.getvalue().startswith(b"PK"))

        html_sink = io.BytesIO()
        html_result = ElsevierApiClient(
            api_key="key",
            stream_transport=lambda url, headers, timeout, sink: StreamHttpResponse(
                200, {"Content-Type": "text/html"}, 0, url, True
            ),
        ).stream_attachment(attachment, html_sink)
        self.assertEqual(html_result.status, "invalid_pdf")
        self.assertEqual(html_sink.getvalue(), b"")


class ElsevierApiAdapterTests(unittest.TestCase):
    @staticmethod
    def _row(doi: str, *, title: str = "API-first paper", author: str = "Zhang Wei", year: str = "2024") -> IntakeRow:
        return IntakeRow(
            source="fixture.csv",
            row_number=2,
            input_doi=doi,
            doi=doi,
            input_title=title,
            title=title,
            authors=author,
            year=year,
        )

    def test_api_success_writes_final_name_without_browser_fallback(self) -> None:
        pdf = minimal_pdf_bytes(b"api main")

        class Client:
            api_key = "sentinel-key"
            insttoken = ""

            def download_article(self, doi, *, include_supplements=True):
                self.include_supplements = include_supplements
                return ElsevierApiResult(
                    status="success",
                    doi=doi,
                    http_status=200,
                    pii="S123",
                    attachment_eid="1-s2.0-S123-main.pdf",
                    pdf_bytes=pdf,
                    full_xml_received=True,
                    title="API-first paper",
                    authors=("Zhang Wei",),
                    year="2024",
                    supplement_status="not_requested",
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client = Client()
            phase = run_elsevier_api_phase(
                [self._row("10.1016/api-success")],
                run_dir=root,
                email="",
                download_supplements=False,
                client=client,
            )
            expected = root / "pdfs" / "2024-Zhang-API-first-paper.pdf"

            self.assertTrue(expected.is_file())
            self.assertEqual(phase.fallback_rows, [])
            self.assertEqual(phase.pdf_records[0].status, "success")
            self.assertEqual(phase.pdf_records[0].file, expected.name)
            self.assertTrue(phase.attempts[0].pdf_valid)
            self.assertFalse(client.include_supplements)

    def test_unauthorized_opens_batch_circuit_without_more_api_calls(self) -> None:
        class Client:
            api_key = "key"
            insttoken = "token"

            def __init__(self):
                self.calls = []

            def download_article(self, doi, *, include_supplements=True):
                self.calls.append(doi)
                return ElsevierApiResult(status="unauthorized", doi=doi, http_status=401, reason="http_401")

        rows = [self._row("10.1016/one"), self._row("10.1016/two")]
        with tempfile.TemporaryDirectory() as tmp:
            client = Client()
            phase = run_elsevier_api_phase(
                rows, run_dir=Path(tmp), email="", download_supplements=True, client=client
            )
        self.assertEqual(client.calls, ["10.1016/one"])
        self.assertEqual([row.doi for row in phase.fallback_rows], ["10.1016/one", "10.1016/two"])
        self.assertEqual(phase.attempts[1].status, "unauthorized")
        self.assertEqual(phase.attempts[1].reason, "api_circuit_open_after_unauthorized")

    def test_supplement_partial_failure_does_not_fail_main_pdf(self) -> None:
        pdf = minimal_pdf_bytes(b"main")
        good = ElsevierAttachment(eid="paper-mmc1.pdf", filename="mmc1.pdf", mime_type="application/pdf")
        bad = ElsevierAttachment(eid="paper-mmc2.zip", filename="appendix.zip", mime_type="application/zip")

        class Client:
            api_key = "key"
            insttoken = ""

            def download_article(self, doi, *, include_supplements=True):
                return ElsevierApiResult(
                    status="success",
                    doi=doi,
                    pii="S123",
                    attachment_eid="paper-main.pdf",
                    pdf_bytes=pdf,
                    title="API-first paper",
                    authors=("Zhang Wei",),
                    year="2024",
                    supplements=(good, bad),
                    supplement_status="success",
                )

            def stream_attachment(self, attachment, sink):
                if attachment.eid == good.eid:
                    content = minimal_pdf_bytes(b"supp")
                    sink.write(content)
                    return type("Object", (), {"status": "success", "content_type": "application/pdf", "size_bytes": len(content), "reason": ""})()
                return type("Object", (), {"status": "invalid_pdf", "content_type": "text/html", "size_bytes": 0, "reason": "attachment_response_invalid"})()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            phase = run_elsevier_api_phase(
                [self._row("10.1016/partial")],
                run_dir=root,
                email="",
                download_supplements=True,
                client=Client(),
            )
            supplement_dir = root / "supplements" / "2024-Zhang-API-first-paper"
            temp_files = list(supplement_dir.glob("*.tmp"))

            self.assertEqual(phase.pdf_records[0].status, "success")
            self.assertEqual([record.status for record in phase.supplement_records], ["success", "failed"])
            self.assertEqual(len(list(supplement_dir.glob("*.pdf"))), 1)
            self.assertEqual(temp_files, [])

    def test_supplement_tempfile_failure_does_not_fail_main_pdf(self) -> None:
        pdf = minimal_pdf_bytes(b"main survives tempfile failure")
        attachment = ElsevierAttachment(
            eid="paper-mmc1.zip",
            filename="mmc1.zip",
            mime_type="application/zip",
        )

        class Client:
            api_key = "key"
            insttoken = ""

            def download_article(self, doi, *, include_supplements=True):
                return ElsevierApiResult(
                    status="success",
                    doi=doi,
                    pii="S123",
                    attachment_eid="paper-main.pdf",
                    pdf_bytes=pdf,
                    title="API main paper",
                    authors=("Zhang Wei",),
                    year="2024",
                    supplements=(attachment,),
                    supplement_status="success",
                )

            def stream_attachment(self, attachment, sink):
                raise AssertionError("streaming must not start when tempfile creation fails")

        real_mkstemp = tempfile.mkstemp

        def fail_staging_mkstemp(*args, **kwargs):
            if Path(str(kwargs.get("dir", ""))).name == ".elsevier_api_tmp":
                raise FileNotFoundError("simulated Windows path-length failure")
            return real_mkstemp(*args, **kwargs)

        with tempfile.TemporaryDirectory() as tmp, patch(
            "sd_institutional_skill.tempfile.mkstemp",
            side_effect=fail_staging_mkstemp,
        ):
            phase = run_elsevier_api_phase(
                [self._row("10.1016/tempfile-failure")],
                run_dir=Path(tmp),
                email="",
                download_supplements=True,
                client=Client(),
            )

        self.assertEqual(phase.pdf_records[0].status, "success")
        self.assertEqual(phase.attempts[0].status, "success")
        self.assertFalse(phase.attempts[0].browser_fallback)
        self.assertEqual(phase.supplement_records[0].status, "failed")
        self.assertEqual(
            phase.supplement_records[0].reason,
            "attachment_exception_FileNotFoundError",
        )

    def test_attempt_report_contains_only_boolean_auth_flags(self) -> None:
        from sd_institutional_skill import ElsevierApiAttemptRecord

        with tempfile.TemporaryDirectory() as tmp:
            path = write_elsevier_api_attempt_report(
                [
                    ElsevierApiAttemptRecord(
                        doi="10.1016/example",
                        status="not_entitled",
                        http_status=403,
                        api_key_present=True,
                        insttoken_present=True,
                        browser_fallback=True,
                        reason="http_403",
                    )
                ],
                Path(tmp),
            )
            text = path.read_text(encoding="utf-8-sig")
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                row = next(csv.DictReader(handle))
        self.assertEqual(row["api_key_present"], "True")
        self.assertEqual(row["insttoken_present"], "True")
        self.assertNotIn("sentinel-key", text)
        self.assertNotIn("sentinel-token", text)

    def test_main_all_api_success_never_constructs_browser_or_reads_cookies(self) -> None:
        from sd_institutional_skill import main

        pdf = minimal_pdf_bytes(b"all api")

        class Client:
            api_key = "key"
            insttoken = ""

            def download_article(self, doi, *, include_supplements=True):
                return ElsevierApiResult(
                    status="success",
                    doi=doi,
                    http_status=200,
                    pii="S123",
                    attachment_eid="paper-main.pdf",
                    pdf_bytes=pdf,
                    full_xml_received=True,
                    title="API-first paper",
                    authors=("Zhang Wei",),
                    year="2024",
                    supplement_status="not_requested",
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "papers.csv"
            source.write_text(
                "doi,title,authors,year\n10.1016/api-success,API-first paper,Zhang Wei,2024\n",
                encoding="utf-8",
            )
            with patch("sd_institutional_skill.ElsevierApiClient", return_value=Client()), patch(
                "sd_institutional_skill.make_scraper",
                side_effect=AssertionError("API success must not construct browser scraper"),
            ), patch(
                "sd_institutional_skill.cache_devtools_cookies",
                side_effect=AssertionError("API success must not read browser cookies"),
            ):
                exit_code = main(
                    [
                        "--input",
                        str(source),
                        "--out",
                        str(root),
                        "--run-name",
                        "all_api",
                        "--no-download-supplements",
                    ]
                )
            run_dir = root / "all_api"
            pdf_files = list((run_dir / "pdfs").glob("*.pdf"))
            with (run_dir / "pdf_download_report.csv").open("r", encoding="utf-8-sig") as handle:
                report_rows = list(csv.DictReader(handle))

        self.assertEqual(exit_code, 0)
        self.assertEqual([path.name for path in pdf_files], ["2024-Zhang-API-first-paper.pdf"])
        self.assertEqual(report_rows[0]["status"], "success")

    def test_mixed_main_sends_only_api_failure_to_browser_and_preserves_browser_reason(self) -> None:
        from sd_institutional_skill import main

        pdf = minimal_pdf_bytes(b"api one")
        browser_inputs: list[list[str]] = []

        class Client:
            api_key = "key"
            insttoken = "token"

            def download_article(self, doi, *, include_supplements=True):
                if doi.endswith("api"):
                    return ElsevierApiResult(
                        status="success",
                        doi=doi,
                        http_status=200,
                        pii="SAPI",
                        attachment_eid="api-main.pdf",
                        pdf_bytes=pdf,
                        title="API article",
                        authors=("Zhang Wei",),
                        year="2024",
                        supplement_status="not_requested",
                    )
                return ElsevierApiResult(
                    status="not_entitled", doi=doi, http_status=403, reason="http_403"
                )

        class Browser:
            last_browser_message = ""
            last_download_next_steps = ""

            def resolve_doi_batch(self, input_path):
                with Path(input_path).open("r", encoding="utf-8-sig") as handle:
                    dois = [row["doi"] for row in csv.DictReader(handle)]
                browser_inputs.append(dois)
                return [], [{"row_number": 2, "doi": dois[0], "reason": "browser_permission_denied"}]

            def save_failed_doi_report(self, failures, filename, output_dir):
                from sd_institutional_skill import write_resolve_failed_report

                return write_resolve_failed_report(failures, Path(output_dir) / filename)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "papers.csv"
            source.write_text(
                "doi,title,authors,year\n"
                "10.1016/first-api,API article,Zhang Wei,2024\n"
                "10.1016/browser-only,Browser article,Li Ming,2023\n",
                encoding="utf-8",
            )
            with patch("sd_institutional_skill.ElsevierApiClient", return_value=Client()), patch(
                "sd_institutional_skill.make_scraper", return_value=Browser()
            ):
                exit_code = main(
                    [
                        "--input",
                        str(source),
                        "--out",
                        str(root),
                        "--run-name",
                        "mixed",
                        "--no-download-supplements",
                    ]
                )
            run_dir = root / "mixed"
            with (run_dir / "pdf_download_report.csv").open("r", encoding="utf-8-sig") as handle:
                report_rows = list(csv.DictReader(handle))
            with (run_dir / "elsevier_api_attempts.csv").open("r", encoding="utf-8-sig") as handle:
                audit_rows = list(csv.DictReader(handle))

        self.assertEqual(exit_code, 0)
        self.assertEqual(browser_inputs, [["10.1016/browser-only"]])
        self.assertEqual([row["doi"] for row in report_rows], ["10.1016/first-api", "10.1016/browser-only"])
        self.assertEqual([row["status"] for row in report_rows], ["success", "failed"])
        self.assertEqual(report_rows[1]["reason"], "browser_permission_denied")
        self.assertEqual(audit_rows[1]["status"], "not_entitled")
        self.assertEqual(audit_rows[1]["browser_fallback"], "True")

    def test_unified_paper_batch_publishes_api_pdf_to_delivery_directory(self) -> None:
        import paper_batch

        pdf = minimal_pdf_bytes(b"unified api")

        class Client:
            api_key = "key"
            insttoken = ""

            def download_article(self, doi, *, include_supplements=True):
                return ElsevierApiResult(
                    status="success",
                    doi=doi,
                    http_status=200,
                    pii="S123",
                    attachment_eid="paper-main.pdf",
                    pdf_bytes=pdf,
                    full_xml_received=True,
                    title="Unified API article",
                    authors=("Zhang Wei",),
                    journal="Acta Materialia",
                    year="2024",
                    supplement_status="not_requested",
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("sd_institutional_skill.ElsevierApiClient", return_value=Client()), patch(
                "sd_institutional_skill.make_scraper",
                side_effect=AssertionError("unified API success must not construct browser scraper"),
            ):
                exit_code = paper_batch.main(
                    [
                        "start",
                        "--text",
                        "10.1016/unified-api",
                        "--out",
                        str(root),
                        "--run-name",
                        "unified_api",
                        "--no-doi-preflight",
                        "--no-download-supplements",
                        "--no-auto-zotero",
                    ]
                )
            run_dir = root / "unified_api"
            delivery_pdf_dir = run_dir / "结果" / "pdf"
            delivery_names = [path.name for path in delivery_pdf_dir.glob("*.pdf")]
            manifest_path = run_dir / "结果" / "下载清单.csv"
            with manifest_path.open("r", encoding="utf-8-sig") as handle:
                manifest_rows = list(csv.DictReader(handle))

        self.assertEqual(exit_code, 0)
        self.assertEqual(delivery_names, ["2024-Zhang-Unified-API-article.pdf"])
        self.assertEqual(manifest_rows[0]["状态"], "成功")
        self.assertEqual(manifest_rows[0]["结果文件"], "结果/pdf/2024-Zhang-Unified-API-article.pdf")

    def test_unified_paper_batch_publishes_api_supplement_by_article_stem(self) -> None:
        import paper_batch

        main_pdf = minimal_pdf_bytes(b"main with supplement")
        supplement = ElsevierAttachment(
            eid="paper-mmc1.zip",
            filename="mmc1.zip",
            mime_type="application/zip",
            attachment_type="APPLICATION",
        )

        class Client:
            api_key = "key"
            insttoken = ""

            def download_article(self, doi, *, include_supplements=True):
                self.include_supplements = include_supplements
                return ElsevierApiResult(
                    status="success",
                    doi=doi,
                    pii="S123",
                    attachment_eid="paper-main.pdf",
                    pdf_bytes=main_pdf,
                    title="Unified API article",
                    authors=("Zhang Wei",),
                    year="2024",
                    supplements=(supplement,),
                    supplement_status="success",
                )

            def stream_attachment(self, attachment, sink):
                payload = b"PK\x03\x04supplement"
                sink.write(payload)
                return type(
                    "Object",
                    (),
                    {
                        "status": "success",
                        "content_type": "application/zip",
                        "size_bytes": len(payload),
                        "reason": "",
                    },
                )()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client = Client()
            real_mkdtemp = tempfile.mkdtemp
            mkdtemp_calls = []

            def tracking_mkdtemp(*args, **kwargs):
                mkdtemp_calls.append((args, dict(kwargs)))
                return real_mkdtemp(*args, **kwargs)

            with patch("sd_institutional_skill.ElsevierApiClient", return_value=client), patch(
                "sd_institutional_skill.make_scraper",
                side_effect=AssertionError("API success must not construct browser scraper"),
            ), patch(
                "paper_automation.batch_workflow.tempfile.mkdtemp",
                side_effect=tracking_mkdtemp,
            ):
                exit_code = paper_batch.main(
                    [
                        "start",
                        "--text",
                        "10.1016/unified-supplement",
                        "--out",
                        str(root),
                        "--run-name",
                        "unified_supplement",
                        "--no-doi-preflight",
                        "--no-auto-zotero",
                    ]
                )
            run_dir = root / "unified_supplement"
            delivered_dir = (
                run_dir
                / "结果"
                / "补充材料"
                / "2024-Zhang-Unified-API-article"
            )
            delivered_names = [path.name for path in delivered_dir.glob("*")]
            with (run_dir / "结果" / "下载清单.csv").open("r", encoding="utf-8-sig") as handle:
                manifest_row = next(csv.DictReader(handle))
            delivery_staging_parents = [
                Path(str(kwargs.get("dir", "")))
                for _args, kwargs in mkdtemp_calls
                if kwargs.get("prefix") == ".delivery_"
            ]
            self.assertEqual(len(delivery_staging_parents), 1)
            self.assertTrue(delivery_staging_parents[0].samefile(root))

        self.assertEqual(exit_code, 0)
        self.assertTrue(client.include_supplements)
        self.assertEqual(delivered_names, ["S01_mmc1.zip"])
        self.assertEqual(
            manifest_row["补充材料"],
            "结果/补充材料/2024-Zhang-Unified-API-article",
        )


if __name__ == "__main__":
    unittest.main()
