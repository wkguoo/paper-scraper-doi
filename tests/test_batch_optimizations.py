"""Tests for download speed/routing optimizations (opts 1–5, 9–10)."""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from paper_automation.batch_stages import (
    BatchOptions,
    is_elsevier_doi,
    is_gold_oa_doi,
    split_route_rows,
)
from paper_automation.file_manager import make_pdf_filename
from paper_automation.models import MetadataResult
from sd_scraper import ScienceDirectScraper
from sd_supplements import make_article_stem


class SmartRouteTests(unittest.TestCase):
    def test_gold_oa_and_elsevier_classification(self) -> None:
        self.assertTrue(is_gold_oa_doi("10.3390/met10121626"))
        self.assertTrue(is_gold_oa_doi("10.3389/fbioe.2024.1372636"))
        self.assertTrue(is_elsevier_doi("10.1016/j.actamat.2016.04.029"))
        self.assertFalse(is_gold_oa_doi("10.1016/j.actamat.2016.04.029"))
        self.assertFalse(is_elsevier_doi("10.1021/acsami.4c00562"))

    def test_split_route_rows(self) -> None:
        rows = [
            {"task_id": "1", "doi": "10.3390/met1"},
            {"task_id": "2", "doi": "10.1016/j.x.1"},
            {"task_id": "3", "doi": "10.1021/acsami.1"},
        ]
        gold, elsevier, other = split_route_rows(rows)
        self.assertEqual([r["task_id"] for r in gold], ["1"])
        self.assertEqual([r["task_id"] for r in elsevier], ["2"])
        self.assertEqual([r["task_id"] for r in other], ["3"])


class FilenameConventionTests(unittest.TestCase):
    def test_year_author_title_oa_style(self) -> None:
        meta = MetadataResult(
            source_index=1,
            query_title="",
            doi="10.1016/j.actamat.2024.119999",
            title="A B C gamma-TiAl alloy",
            authors=["Zhang Wei", "Li Qiang"],
            year="2024",
        )
        name = make_pdf_filename(meta)
        self.assertTrue(name.startswith("2024-Zhang-"))
        self.assertTrue(name.endswith(".pdf"))
        self.assertNotIn("_", name.split("-", 2)[0])  # year uses hyphen scheme

    def test_article_stem_year_author_title(self) -> None:
        stem = make_article_stem(
            1,
            {
                "year": "2020",
                "authors": "Hao, Yulin; Li, S.",
                "title": "Plastic deformation via hierarchical twinning",
                "doi": "10.1016/j.actamat.2020.04.021",
            },
        )
        self.assertTrue(stem.startswith("2020-Hao-"))
        self.assertIn("Plastic", stem)

    def test_enrich_row_fills_year_author_before_delivery_name(self) -> None:
        from paper_automation.file_manager import (
            enrich_row_metadata_for_delivery,
            make_pdf_filename,
        )
        from paper_automation.models import MetadataResult, PaperCandidate

        def fake_resolver(candidate: PaperCandidate) -> MetadataResult:
            return MetadataResult(
                source_index=candidate.source_index,
                query_title=candidate.title,
                doi=candidate.doi,
                title="Densification behavior of titanium alloy powder during hot pressing",
                authors=["Kim K.T", "Yang H.C"],
                year="2001",
            )

        row = {
            "source_index": "1",
            "doi": "10.1016/S0921-5093(01)01147-9",
            "title": "| 1 | [Densification behavior of titanium alloy powder during hot pressing](url) | junk |",
            "authors": "",
            "year": "",
        }
        enriched = enrich_row_metadata_for_delivery(row, resolver=fake_resolver)
        self.assertEqual(enriched["year"], "2001")
        self.assertIn("Kim", enriched["authors"])
        self.assertNotIn("|", enriched["title"])
        name = make_pdf_filename(
            MetadataResult(
                source_index=1,
                query_title="",
                doi=enriched["doi"],
                title=enriched["title"],
                authors=[p.strip() for p in enriched["authors"].replace(";", "|").split("|") if p.strip()],
                year=enriched["year"],
            )
        )
        self.assertTrue(name.startswith("2001-Kim-"))
        self.assertTrue(name.endswith(".pdf"))
        self.assertNotIn("Unknown", name)
        self.assertNotIn("0000", name)


class CheckpointTests(unittest.TestCase):
    def test_checkpoint_roundtrip(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "pdf_download_checkpoint.jsonl"
            ScienceDirectScraper._append_pdf_checkpoint(
                path, doi="10.1016/j.x", status="success", file="a.pdf"
            )
            ScienceDirectScraper._append_pdf_checkpoint(
                path, doi="10.3390/y", status="failed", reason="x"
            )
            done = ScienceDirectScraper._load_pdf_checkpoint_dois(path)
            self.assertIn("10.1016/j.x", done)
            self.assertNotIn("10.3390/y", done)


class BatchOptionsDefaultsTests(unittest.TestCase):
    def test_optimized_defaults(self) -> None:
        opts = BatchOptions()
        self.assertTrue(opts.download_supplements)
        self.assertTrue(opts.smart_route)
        self.assertEqual(opts.session_break_seconds, 60.0)
        self.assertEqual(opts.session_break_every, 8)
        self.assertFalse(opts.resolve_title_metadata)
        self.assertTrue(opts.auto_oa_recovery)
        self.assertTrue(opts.iucr_short_try)


class FilenameSanitizeB5Tests(unittest.TestCase):
    def test_strips_html_mathml_and_tag_residues(self) -> None:
        from paper_automation.file_manager import clean_title_for_filename, make_pdf_filename

        cleaned = clean_title_for_filename(
            "An <i>in situ</i> USAXS of Ti<sub>2</sub> with MathML altimg junk"
        )
        self.assertNotIn("<", cleaned)
        self.assertNotIn("MathML", cleaned)
        self.assertNotIn("altimg", cleaned)
        self.assertIn("in situ", cleaned.lower().replace("-", " "))

        residue = clean_title_for_filename("An iin-situ-i USAXS of Ti-sub2-sub")
        self.assertNotIn("iin", residue.lower())
        self.assertNotIn("sub2", residue.lower())
        name = make_pdf_filename(
            MetadataResult(
                source_index=1,
                query_title="",
                doi="10.1/x",
                title="An iin-situ-i USAXS of Ti-sub2-sub",
                authors=["Andrews"],
                year="2017",
            )
        )
        self.assertTrue(name.startswith("2017-Andrews-"))
        self.assertNotIn("iin", name.lower())
        self.assertNotIn("sub2", name.lower())


class IucrShortTryC6Tests(unittest.TestCase):
    def test_is_iucr_doi(self) -> None:
        from paper_automation.batch_stages import is_iucr_doi

        self.assertTrue(is_iucr_doi("10.1107/S1600576715007347"))
        self.assertFalse(is_iucr_doi("10.1016/j.actamat.2020.01.001"))


class MergeSafeDeliveryA1Tests(unittest.TestCase):
    def test_publish_preserves_orphan_pdf(self) -> None:
        from paper_automation.batch_workflow import (
            USER_DELIVERY_DIR_NAME,
            create_batch_paths,
            publish_user_delivery,
        )

        with TemporaryDirectory() as tmp:
            paths = create_batch_paths(tmp, run_name="a1_merge", fixed=True)
            delivery = paths.root / USER_DELIVERY_DIR_NAME
            delivery.mkdir(parents=True, exist_ok=True)
            orphan = delivery / "CRPHYS_manual.pdf"
            orphan.write_bytes(b"%PDF-1.4 orphan content unique-xyz")

            # No success rows — orphan must survive republish.
            publish_user_delivery(paths, [])
            kept = list((paths.root / USER_DELIVERY_DIR_NAME).glob("*.pdf"))
            self.assertEqual(len(kept), 1)
            self.assertEqual(kept[0].read_bytes(), b"%PDF-1.4 orphan content unique-xyz")


class RefreshDeliveryA3Tests(unittest.TestCase):
    def test_refresh_renames_orphan_and_maps_failed_doi(self) -> None:
        from paper_automation.batch_workflow import (
            USER_DELIVERY_DIR_NAME,
            create_batch_paths,
            save_batch_state,
        )
        from paper_automation.delivery_refresh import refresh_delivery

        with TemporaryDirectory() as tmp:
            paths = create_batch_paths(tmp, run_name="a3_refresh", fixed=True)
            (paths.working).mkdir(parents=True, exist_ok=True)
            delivery = paths.root / USER_DELIVERY_DIR_NAME
            delivery.mkdir(parents=True, exist_ok=True)
            # Pre-named in year-author-title form so rename is stable without Crossref.
            pdf = delivery / "2012-De-Geuser-Precipitate-characterisation.pdf"
            pdf.write_bytes(b"%PDF-1.4 refresh-test-bytes")

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
                    "auto_oa_recovery": True,
                    "iucr_short_try": True,
                },
                "rows": [
                    {
                        "task_id": "t1",
                        "doi": "10.1016/j.crhy.2011.12.008",
                        "title": "Precipitate characterisation",
                        "authors": "De Geuser",
                        "year": "2012",
                        "status": "metadata_uncertain",
                        "source": "zotero",
                        "file": "",
                        "reason": "metadata_uncertain",
                    }
                ],
            }
            save_batch_state(paths, state)

            # Without DOI in PDF, refresh keeps external; still rewrites inventory.
            result = refresh_delivery(paths.root, apply_rename=True)
            self.assertTrue(result.inventory_path.is_file())
            self.assertTrue((paths.root / USER_DELIVERY_DIR_NAME).exists())
            inv = result.inventory_path.read_text(encoding="utf-8-sig")
            self.assertIn("外部补入", inv)


if __name__ == "__main__":
    unittest.main()
