"""Tests for bounded OA recovery (no multi-source deep search)."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from paper_automation.models import DownloadResponse, MetadataResult, PaperCandidate
from paper_automation.oa_recovery import (
    HostHealthCache,
    recover_oa_limited,
)


def _minimal_pdf_bytes() -> bytes:
    # Valid enough for is_pdf_bytes: header + %%EOF
    return b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


class FakeResolver:
    def __init__(self, metadata: MetadataResult) -> None:
        self.metadata = metadata

    def resolve_one(self, candidate: PaperCandidate) -> MetadataResult:
        return self.metadata


class LimitedOaRecoveryTests(unittest.TestCase):
    def test_missing_doi(self) -> None:
        result = recover_oa_limited("")
        self.assertEqual(result.status, "missing_doi")

    def test_repo_metadata_only_no_scrape(self) -> None:
        meta = MetadataResult(
            source_index=0,
            query_title="",
            doi="10.1179/003258901666149",
            title="Densification behaviour of titanium alloy powder",
            authors=["Kim K.T"],
            year="2001",
            openalex={
                "open_access": {"is_oa": False, "oa_url": None},
                "locations": [
                    {
                        "pdf_url": None,
                        "landing_page_url": "https://oasis.postech.ac.kr/handle/2014.oak/19544",
                        "source": {"display_name": "POSTECH OASIS"},
                    }
                ],
            },
        )
        calls: list[str] = []

        def http_bytes(url: str, headers=None, timeout: int = 12) -> DownloadResponse:
            calls.append(url)
            raise AssertionError("must not download when only landing URL exists")

        result = recover_oa_limited(
            "10.1179/003258901666149",
            budget_seconds=30,
            resolver=FakeResolver(meta),
            http_bytes=http_bytes,
        )
        self.assertEqual(result.status, "repo_metadata_only")
        self.assertEqual(calls, [])
        self.assertTrue(any(a.result == "metadata_only" for a in result.attempts))

    def test_annotated_oa_pdf_success_and_year_author_name(self) -> None:
        pdf = _minimal_pdf_bytes()
        meta = MetadataResult(
            source_index=0,
            query_title="",
            doi="10.3390/met8070537",
            title="Numerical Simulation of Densification of Cu-Al Mixed Metal Powder",
            authors=["Wang Wenchao"],
            year="2018",
            openalex={
                "open_access": {
                    "is_oa": True,
                    "oa_url": "https://example.test/paper.pdf",
                },
                "best_oa_location": {"pdf_url": "https://example.test/paper.pdf"},
                "locations": [],
            },
        )

        def http_bytes(url: str, headers=None, timeout: int = 12) -> DownloadResponse:
            self.assertIn("example.test", url)
            return DownloadResponse(pdf, "application/pdf", url)

        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            result = recover_oa_limited(
                "10.3390/met8070537",
                budget_seconds=30,
                output_dir=out,
                resolver=FakeResolver(meta),
                http_bytes=http_bytes,
            )
            self.assertEqual(result.status, "oa_downloaded")
            self.assertTrue(result.file)
            path = Path(result.file)
            self.assertTrue(path.is_file())
            self.assertTrue(path.name.startswith("2018-Wang-"))
            self.assertTrue(path.name.endswith(".pdf"))

    def test_host_cache_skips_second_doi_same_host(self) -> None:
        meta = MetadataResult(
            source_index=0,
            query_title="",
            doi="10.1179/example",
            title="Example",
            authors=["Kim"],
            year="2001",
            openalex={
                "open_access": {"is_oa": True, "oa_url": "https://journals.sagepub.com/doi/pdf/10.1179/example"},
                "best_oa_location": {
                    "pdf_url": "https://journals.sagepub.com/doi/pdf/10.1179/example"
                },
            },
        )
        cache = HostHealthCache()
        calls: list[str] = []

        def http_bytes(url: str, headers=None, timeout: int = 12) -> DownloadResponse:
            calls.append(url)
            raise ConnectionError("ERR_CONNECTION_CLOSED")

        first = recover_oa_limited(
            "10.1179/example",
            budget_seconds=20,
            host_cache=cache,
            resolver=FakeResolver(meta),
            http_bytes=http_bytes,
        )
        self.assertIn(first.status, {"publisher_unreachable", "no_oa_pdf"})
        self.assertEqual(len(calls), 1)

        second_meta = MetadataResult(
            source_index=0,
            query_title="",
            doi="10.1179/other",
            title="Other",
            authors=["Kim"],
            year="2001",
            openalex={
                "open_access": {
                    "is_oa": True,
                    "oa_url": "https://journals.sagepub.com/doi/pdf/10.1179/other",
                },
                "best_oa_location": {
                    "pdf_url": "https://journals.sagepub.com/doi/pdf/10.1179/other"
                },
            },
        )
        second = recover_oa_limited(
            "10.1179/other",
            budget_seconds=20,
            host_cache=cache,
            resolver=FakeResolver(second_meta),
            http_bytes=http_bytes,
        )
        # Second DOI must not hit the network for the same host.
        self.assertEqual(len(calls), 1)
        self.assertTrue(any(a.result == "skipped_host_cache" for a in second.attempts))

    def test_budget_timeout(self) -> None:
        meta = MetadataResult(
            source_index=0,
            query_title="",
            doi="10.0/example",
            title="Slow",
            year="2020",
            openalex={
                "open_access": {"is_oa": True, "oa_url": "https://example.test/slow.pdf"},
                "best_oa_location": {"pdf_url": "https://example.test/slow.pdf"},
            },
        )

        def http_bytes(url: str, headers=None, timeout: int = 12) -> DownloadResponse:
            import time

            time.sleep(0.05)
            return DownloadResponse(b"not-a-pdf", "text/html", url)

        result = recover_oa_limited(
            "10.0/example",
            budget_seconds=0.01,
            resolver=FakeResolver(meta),
            http_bytes=http_bytes,
            timeout_per_request=1,
        )
        # Extremely small budget after metadata may yield timeout or no_oa_pdf.
        self.assertIn(result.status, {"recovery_timeout", "no_oa_pdf", "publisher_unreachable"})


if __name__ == "__main__":
    unittest.main()
