from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class ParserAndDeduplicatorTests(unittest.TestCase):
    def test_parse_mixed_text_extracts_doi_titles_and_review_rows(self) -> None:
        from paper_automation.parser import parse_mixed_text

        text = """
        1. Zhang W, Li Q. Additive manufacturing of gamma-TiAl alloys. Acta Materialia (2024). DOI: 10.1016/j.actamat.2024.119999
        Download PDF | View article
        Microstructure evolution in laser powder bed fused nickel superalloys. Acta Materialia, 2024
        [3] unclear
        https://doi.org/10.1038/s41586-024-07000-1
        """

        candidates = parse_mixed_text(text)

        self.assertEqual(len(candidates), 4)
        self.assertEqual(candidates[0].doi, "10.1016/j.actamat.2024.119999")
        self.assertIn("Additive manufacturing", candidates[0].title)
        self.assertEqual(candidates[1].title, "Microstructure evolution in laser powder bed fused nickel superalloys")
        self.assertEqual(candidates[1].status, "recognized")
        self.assertEqual(candidates[2].status, "needs_review")
        self.assertEqual(candidates[3].doi, "10.1038/s41586-024-07000-1")

    def test_parse_mixed_text_requires_context_for_title_only_matching(self) -> None:
        from paper_automation.parser import parse_mixed_text

        candidates = parse_mixed_text(
            "Microstructure evolution in laser powder bed fused nickel superalloys\n"
            "P8: Ti-Mo beta-Ti stress-induced martensitic transformation 是否包含 SXRD\n"
            "unclear recommendation without enough bibliographic information\n"
            "可能相关/边界/排除参考\n"
            "Microstructure evolution in laser powder bed fused nickel superalloys. Acta Materialia, 2024\n"
            "Zhang W, Li Q. Additive manufacturing of gamma-TiAl alloys. Scripta Materialia 2025\n"
        )

        self.assertEqual(candidates[0].status, "needs_review")
        self.assertEqual(candidates[0].reason, "insufficient_bibliographic_context")
        self.assertEqual(candidates[1].status, "needs_review")
        self.assertEqual(candidates[1].reason, "not_probable_title")
        self.assertEqual(candidates[2].status, "needs_review")
        self.assertEqual(candidates[2].reason, "not_probable_title")
        self.assertEqual(candidates[3].status, "needs_review")
        self.assertEqual(candidates[3].reason, "not_probable_title")
        self.assertEqual(candidates[4].status, "recognized")
        self.assertEqual(candidates[5].status, "recognized")

    def test_parse_mixed_text_merges_adjacent_title_and_metadata_line(self) -> None:
        from paper_automation.parser import parse_mixed_text

        candidates = parse_mixed_text(
            "Microstructure evolution in laser powder bed fused nickel superalloys\n"
            "Acta Materialia, 2024\n"
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].status, "recognized")
        self.assertEqual(candidates[0].title, "Microstructure evolution in laser powder bed fused nickel superalloys")
        self.assertIn("Acta Materialia, 2024", candidates[0].raw_text)

    def test_parse_mixed_text_keeps_two_line_short_citation_context_for_resolution(self) -> None:
        from paper_automation.metadata_resolver import MetadataResolver
        from paper_automation.parser import parse_mixed_text

        def fake_json(url: str, headers: dict[str, str] | None = None, timeout: int = 20) -> dict:
            if "api.crossref.org/works?" in url:
                return {
                    "message": {
                        "items": [
                            {
                                "DOI": "10.1016/j.scriptamat.2012.04.034",
                                "title": [
                                    "Three-dimensional morphology of cementite in steel studied by X-ray phase-contrast tomography"
                                ],
                                "container-title": ["Scripta Materialia"],
                                "volume": "67",
                                "page": "261-264",
                                "published-print": {"date-parts": [[2012]]},
                                "publisher": "Elsevier",
                            }
                        ]
                    }
                }
            return {}

        candidates = parse_mixed_text(
            "X-ray tomography 3D cementite morphology\n"
            "Scripta Materialia 67 261-264 2012"
        )
        metadata = MetadataResolver(http_json=fake_json).resolve_one(candidates[0])

        self.assertEqual(len(candidates), 1)
        self.assertIn("Scripta Materialia 67 261-264 2012", candidates[0].raw_text)
        self.assertEqual(metadata.doi, "10.1016/j.scriptamat.2012.04.034")

    def test_parse_mixed_text_skips_author_et_al_prefix(self) -> None:
        from paper_automation.parser import parse_mixed_text

        candidates = parse_mixed_text(
            "Kostenko A. et al. Three-dimensional morphology of cementite in steel studied by "
            "X-ray phase-contrast tomography. Scripta Materialia 67(3):261-264 2012."
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].status, "recognized")
        self.assertEqual(
            candidates[0].title,
            "Three-dimensional morphology of cementite in steel studied by X-ray phase-contrast tomography",
        )

    def test_parse_mixed_text_preserves_pure_doi_lines(self) -> None:
        from paper_automation.parser import parse_mixed_text

        candidates = parse_mixed_text(
            "10.3390/ma18143270\n"
            "10.1016/j.msea.2021.141489\n"
        )

        self.assertEqual([item.doi for item in candidates], [
            "10.3390/ma18143270",
            "10.1016/j.msea.2021.141489",
        ])
        self.assertEqual([item.status for item in candidates], ["recognized", "recognized"])

    def test_parse_mixed_text_preserves_parenthesized_elsevier_dois(self) -> None:
        from paper_automation.parser import extract_dois, parse_mixed_text

        text = (
            "[10.1016/S1359-6454(00)00218-4](https://doi.org/10.1016/S1359-6454(00)00218-4)\n"
            "10.1016/S1359-6454(02)00134-9\n"
            "(https://doi.org/10.1016/S1359-6454(02)00050-2)"
        )

        self.assertEqual(extract_dois(text), [
            "10.1016/s1359-6454(00)00218-4",
            "10.1016/s1359-6454(02)00134-9",
            "10.1016/s1359-6454(02)00050-2",
        ])
        self.assertEqual([item.doi for item in parse_mixed_text(text)], [
            "10.1016/s1359-6454(00)00218-4",
            "10.1016/s1359-6454(02)00134-9",
            "10.1016/s1359-6454(02)00050-2",
        ])

    def test_deduplicate_uses_doi_then_normalized_title_fuzzy_match(self) -> None:
        from paper_automation.deduplicator import deduplicate_candidates
        from paper_automation.models import PaperCandidate

        candidates = [
            PaperCandidate(source_index=1, raw_text="A", doi="10.1000/ABC", title="γ-TiAl alloy fatigue behavior"),
            PaperCandidate(source_index=2, raw_text="B", doi="https://doi.org/10.1000/abc", title="Different title"),
            PaperCandidate(source_index=3, raw_text="C", doi="", title="Gamma TiAl alloy fatigue behaviour"),
            PaperCandidate(source_index=4, raw_text="D", doi="", title="Completely different paper"),
        ]

        result = deduplicate_candidates(candidates, title_threshold=0.82)

        self.assertEqual([item.source_index for item in result.unique], [1, 4])
        self.assertEqual(len(result.duplicates), 2)
        self.assertEqual(result.duplicates[0].reason, "duplicate_doi")
        self.assertEqual(result.duplicates[0].duplicate_of, 1)
        self.assertEqual(result.duplicates[1].reason, "duplicate_title")
        self.assertEqual(result.duplicates[1].duplicate_of, 1)

    def test_deduplicate_keeps_distinct_dois_with_similar_titles(self) -> None:
        from paper_automation.deduplicator import deduplicate_candidates
        from paper_automation.models import PaperCandidate

        candidates = [
            PaperCandidate(source_index=1, raw_text="A", doi="10.1016/j.actamat.2024.1", title="In situ synchrotron XRD study of Ti alloy"),
            PaperCandidate(source_index=2, raw_text="B", doi="10.1016/j.actamat.2024.2", title="In situ synchrotron XRD study of Ti alloys"),
        ]

        result = deduplicate_candidates(candidates, title_threshold=0.82)

        self.assertEqual([item.source_index for item in result.unique], [1, 2])
        self.assertEqual(result.duplicates, [])


class MetadataAndPdfTests(unittest.TestCase):
    def test_resolver_prefers_doi_and_scores_crossref_title_match(self) -> None:
        from paper_automation.metadata_resolver import MetadataResolver
        from paper_automation.models import PaperCandidate

        calls: list[str] = []

        def fake_json(url: str, headers: dict[str, str] | None = None, timeout: int = 20) -> dict:
            calls.append(url)
            if "api.crossref.org/works/10.1016" in url:
                return {
                    "message": {
                        "DOI": "10.1016/j.actamat.2024.119999",
                        "title": ["Additive manufacturing of gamma-TiAl alloys"],
                        "author": [{"family": "Zhang", "given": "Wei"}],
                        "container-title": ["Acta Materialia"],
                        "published-print": {"date-parts": [[2024]]},
                        "publisher": "Elsevier",
                        "URL": "https://doi.org/10.1016/j.actamat.2024.119999",
                        "link": [{"URL": "https://example.org/file.pdf", "content-type": "application/pdf"}],
                    }
                }
            return {}

        resolver = MetadataResolver(http_json=fake_json)
        metadata = resolver.resolve_one(
            PaperCandidate(
                source_index=1,
                raw_text="raw",
                doi="10.1016/j.actamat.2024.119999",
                title="Additive manufacturing of gamma TiAl alloys",
            )
        )

        self.assertEqual(metadata.doi, "10.1016/j.actamat.2024.119999")
        self.assertEqual(metadata.year, "2024")
        self.assertGreaterEqual(metadata.confidence, 0.9)
        self.assertTrue(any("api.crossref.org" in call for call in calls))

    def test_resolver_accepts_crossref_match_by_citation_fingerprint(self) -> None:
        from paper_automation.metadata_resolver import MetadataResolver
        from paper_automation.models import PaperCandidate

        def fake_json(url: str, headers: dict[str, str] | None = None, timeout: int = 20) -> dict:
            if "api.crossref.org/works?" in url:
                return {
                    "message": {
                        "items": [
                            {
                                "DOI": "10.1016/j.scriptamat.2012.04.034",
                                "title": [
                                    "Three-dimensional morphology of cementite in steel studied by X-ray phase-contrast tomography"
                                ],
                                "container-title": ["Scripta Materialia"],
                                "volume": "67",
                                "page": "261-264",
                                "published-print": {"date-parts": [[2012]]},
                                "publisher": "Elsevier",
                            }
                        ]
                    }
                }
            return {}

        resolver = MetadataResolver(http_json=fake_json)
        metadata = resolver.resolve_one(
            PaperCandidate(
                source_index=1,
                raw_text="X-ray tomography 3D cementite morphology. Scripta Materialia 67 261-264 2012.",
                doi="",
                title="X-ray tomography 3D cementite morphology",
            )
        )

        self.assertEqual(metadata.doi, "10.1016/j.scriptamat.2012.04.034")
        self.assertEqual(metadata.journal, "Scripta Materialia")
        self.assertEqual(metadata.year, "2012")
        self.assertGreaterEqual(metadata.confidence, 0.65)

    def test_resolver_accepts_abbreviated_journal_citation_fingerprint(self) -> None:
        from paper_automation.metadata_resolver import MetadataResolver
        from paper_automation.models import PaperCandidate

        def fake_json(url: str, headers: dict[str, str] | None = None, timeout: int = 20) -> dict:
            if "api.crossref.org/works?" in url:
                return {
                    "message": {
                        "items": [
                            {
                                "DOI": "10.1016/j.scriptamat.2012.04.034",
                                "title": [
                                    "Three-dimensional morphology of cementite in steel studied by X-ray phase-contrast tomography"
                                ],
                                "container-title": ["Scripta Materialia"],
                                "volume": "67",
                                "page": "261-264",
                                "published-print": {"date-parts": [[2012]]},
                                "publisher": "Elsevier",
                            }
                        ]
                    }
                }
            return {}

        resolver = MetadataResolver(http_json=fake_json)
        metadata = resolver.resolve_one(
            PaperCandidate(
                source_index=1,
                raw_text="Scripta Mater. 67, 261-264, 2012 cementite tomography",
                doi="",
                title="Scripta Mater. 67, 261-264, 2012 cementite tomography",
            )
        )

        self.assertEqual(metadata.doi, "10.1016/j.scriptamat.2012.04.034")

    def test_resolver_rejects_citation_fingerprint_with_wrong_pages(self) -> None:
        from paper_automation.metadata_resolver import MetadataResolver
        from paper_automation.models import PaperCandidate

        def fake_json(url: str, headers: dict[str, str] | None = None, timeout: int = 20) -> dict:
            if "api.crossref.org/works?" in url:
                return {
                    "message": {
                        "items": [
                            {
                                "DOI": "10.1016/j.scriptamat.2012.04.034",
                                "title": [
                                    "Three-dimensional morphology of cementite in steel studied by X-ray phase-contrast tomography"
                                ],
                                "container-title": ["Scripta Materialia"],
                                "volume": "67",
                                "page": "261-264",
                                "published-print": {"date-parts": [[2012]]},
                                "publisher": "Elsevier",
                            }
                        ]
                    }
                }
            return {}

        resolver = MetadataResolver(http_json=fake_json)
        metadata = resolver.resolve_one(
            PaperCandidate(
                source_index=1,
                raw_text="Scripta Materialia 67 999-1000 2012 cementite tomography",
                doi="",
                title="Scripta Materialia 67 999-1000 2012 cementite tomography",
            )
        )

        self.assertEqual(metadata.doi, "")

    def test_resolver_uses_search_provider_only_after_crossref_confirmation(self) -> None:
        from paper_automation.metadata_resolver import MetadataResolver
        from paper_automation.models import PaperCandidate

        calls: list[str] = []

        def fake_json(url: str, headers: dict[str, str] | None = None, timeout: int = 20) -> dict:
            calls.append(url)
            if "api.crossref.org/works/10.1016" in url:
                return {
                    "message": {
                        "DOI": "10.1016/j.scriptamat.2026.116999",
                        "title": ["Search verified paper title"],
                        "container-title": ["Scripta Materialia"],
                        "published-print": {"date-parts": [[2026]]},
                        "publisher": "Elsevier",
                    }
                }
            return {}

        def fake_search(query: str, max_results: int) -> list[dict[str, object]]:
            self.assertEqual(max_results, 2)
            return [
                {
                    "title": "Search verified paper title",
                    "externalIds": {"DOI": "10.1016/j.scriptamat.2026.116999"},
                }
            ]

        resolver = MetadataResolver(
            http_json=fake_json,
            search_provider=fake_search,
            max_search_candidates=2,
        )
        metadata = resolver.resolve_one(
            PaperCandidate(1, "Search verified paper title. Scripta Materialia 2026.", "", "Search verified paper title")
        )

        self.assertEqual(metadata.doi, "10.1016/j.scriptamat.2026.116999")
        self.assertEqual(metadata.source, "semantic_scholar+crossref")
        self.assertEqual(metadata.match_basis, "semantic_scholar_crossref_verified")
        self.assertTrue(any("api.crossref.org/works/10.1016" in call for call in calls))

    def test_resolver_rejects_search_provider_candidate_without_crossref_confirmation(self) -> None:
        from paper_automation.metadata_resolver import MetadataResolver
        from paper_automation.models import PaperCandidate

        def fake_search(query: str, max_results: int) -> list[dict[str, object]]:
            return [
                {
                    "title": "Unconfirmed search result",
                    "externalIds": {"DOI": "10.1016/j.scriptamat.2026.116998"},
                }
            ]

        resolver = MetadataResolver(
            http_json=lambda *_args, **_kwargs: {},
            search_provider=fake_search,
        )
        metadata = resolver.resolve_one(
            PaperCandidate(1, "Unconfirmed search result. Scripta Materialia 2026.", "", "Unconfirmed search result")
        )

        self.assertEqual(metadata.doi, "")
        self.assertNotEqual(metadata.source, "semantic_scholar+crossref")

    def test_resolver_rejects_search_provider_candidate_unrelated_to_query(self) -> None:
        from paper_automation.metadata_resolver import MetadataResolver
        from paper_automation.models import PaperCandidate

        def fake_json(url: str, headers: dict[str, str] | None = None, timeout: int = 20) -> dict:
            if "api.crossref.org/works/10.1016" in url:
                return {
                    "message": {
                        "DOI": "10.1016/j.scriptamat.2026.116997",
                        "title": ["Hydrogen embrittlement in aluminum alloys"],
                        "container-title": ["Scripta Materialia"],
                        "published-print": {"date-parts": [[2026]]},
                        "publisher": "Elsevier",
                    }
                }
            return {}

        def fake_search(query: str, max_results: int) -> list[dict[str, object]]:
            return [
                {
                    "title": "Hydrogen embrittlement in aluminum alloys",
                    "externalIds": {"DOI": "10.1016/j.scriptamat.2026.116997"},
                }
            ]

        resolver = MetadataResolver(
            http_json=fake_json,
            search_provider=fake_search,
        )
        metadata = resolver.resolve_one(
            PaperCandidate(1, "X-ray tomography 3D cementite morphology. Scripta Materialia 2012.", "", "X-ray tomography 3D cementite morphology")
        )

        self.assertEqual(metadata.doi, "")
        self.assertNotEqual(metadata.source, "semantic_scholar+crossref")

    def test_pdf_finder_uses_only_oa_candidates_and_preserves_failure_reason(self) -> None:
        from paper_automation.models import MetadataResult
        from paper_automation.pdf_finder import choose_pdf_candidate

        metadata = MetadataResult(
            source_index=1,
            query_title="Paper",
            doi="10.1000/example",
            title="Paper",
            unpaywall={
                "is_oa": True,
                "best_oa_location": {
                    "url_for_pdf": "https://repository.example/paper.pdf",
                    "host_type": "repository",
                    "license": "cc-by",
                },
            },
            openalex={
                "open_access": {"is_oa": True, "oa_url": "https://landing.example/paper"},
                "best_oa_location": {"pdf_url": "https://openalex.example/paper.pdf"},
            },
        )

        chosen = choose_pdf_candidate(metadata)

        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.url, "https://repository.example/paper.pdf")
        self.assertEqual(chosen.source, "unpaywall")

        closed = MetadataResult(source_index=2, query_title="Closed", doi="10.1000/closed", title="Closed")
        self.assertIsNone(choose_pdf_candidate(closed))

    def test_pdf_finder_rejects_landing_page_as_openalex_pdf(self) -> None:
        from paper_automation.models import MetadataResult
        from paper_automation.pdf_finder import choose_pdf_candidate

        metadata = MetadataResult(
            source_index=1,
            query_title="Landing page",
            doi="10.1000/landing",
            title="Landing page",
            openalex={
                "open_access": {"is_oa": True},
                "best_oa_location": {
                    "pdf_url": "https://www.sciencedirect.com/science/article/pii/S0921509321007589",
                },
            },
        )

        self.assertIsNone(choose_pdf_candidate(metadata))

    def test_downloader_sends_browser_like_user_agent(self) -> None:
        from paper_automation.downloader import download_pdf
        from paper_automation.models import DownloadResponse, PdfCandidate

        captured_headers: dict[str, str] = {}

        def fake_getter(url: str, headers: dict[str, str] | None = None, timeout: int = 30) -> DownloadResponse:
            captured_headers.update(headers or {})
            return DownloadResponse(b"%PDF-1.7\n", "application/pdf", url)

        with tempfile.TemporaryDirectory() as tmp:
            result = download_pdf(
                PdfCandidate(url="https://example.org/paper.pdf", source="test"),
                Path(tmp) / "paper.pdf",
                http_bytes=fake_getter,
            )

        self.assertEqual(result.status, "downloaded")
        self.assertIn("Mozilla/5.0", captured_headers.get("User-Agent", ""))


class FileWorkflowTests(unittest.TestCase):
    def test_file_manager_creates_windows_safe_pdf_name(self) -> None:
        from paper_automation.file_manager import make_pdf_filename
        from paper_automation.models import MetadataResult

        metadata = MetadataResult(
            source_index=1,
            query_title="",
            doi="10.1016/j.actamat.2024.119999",
            title="A/B:C*D? gamma-TiAl alloy <test>",
            authors=["Zhang Wei", "Li Qiang"],
            year="2024",
        )

        filename = make_pdf_filename(metadata)

        self.assertTrue(filename.endswith(".pdf"))
        self.assertNotRegex(filename, r'[<>:"/\\|?*]')
        self.assertTrue(filename.startswith("2024_Zhang_"))

    def test_workflow_dry_run_writes_manifest_and_failure_rows(self) -> None:
        from paper_automation.workflow import run_workflow

        def fake_json(url: str, headers: dict[str, str] | None = None, timeout: int = 20) -> dict:
            if "api.crossref.org/works/10.1000" in url:
                return {
                    "message": {
                        "DOI": "10.1000/example",
                        "title": ["Example OA paper"],
                        "author": [{"family": "Wang", "given": "Lin"}],
                        "container-title": ["Journal"],
                        "published-online": {"date-parts": [[2025]]},
                        "publisher": "Publisher",
                        "URL": "https://doi.org/10.1000/example",
                    }
                }
            if "api.unpaywall.org" in url:
                return {
                    "is_oa": True,
                    "best_oa_location": {
                        "url_for_pdf": "https://repository.example/example.pdf",
                        "host_type": "repository",
                    },
                }
            return {}

        with tempfile.TemporaryDirectory() as tmp:
            result = run_workflow(
                input_text="Example OA paper doi:10.1000/example\nExample OA paper https://doi.org/10.1000/example",
                output_dir=Path(tmp),
                email="user@example.com",
                dry_run=True,
                http_json=fake_json,
            )
            manifest_csv = Path(tmp) / "metadata" / "manifest.csv"
            manifest_json = Path(tmp) / "metadata" / "manifest.json"
            duplicates_csv = Path(tmp) / "failed" / "duplicates.csv"

            manifest_text = manifest_csv.read_text(encoding="utf-8-sig")
            manifest_data = json.loads(manifest_json.read_text(encoding="utf-8"))
            duplicate_text = duplicates_csv.read_text(encoding="utf-8-sig")

        self.assertEqual(result.total_input, 2)
        self.assertEqual(result.unique_count, 1)
        self.assertEqual(result.duplicate_count, 1)
        self.assertEqual(result.downloaded_count, 0)
        self.assertIn("dry_run", manifest_text)
        self.assertEqual(manifest_data[0]["download_status"], "dry_run")
        self.assertIn("duplicate_doi", duplicate_text)


if __name__ == "__main__":
    unittest.main()
