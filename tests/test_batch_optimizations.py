"""Tests for download speed/routing optimizations (opts 1–5, 9–10)."""
from __future__ import annotations

import csv
import io
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
        self.assertEqual(opts.api_workers, 2)


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
            kept = list((paths.root / USER_DELIVERY_DIR_NAME / "pdf").glob("*.pdf"))
            self.assertEqual(len(kept), 1)
            self.assertEqual(kept[0].read_bytes(), b"%PDF-1.4 orphan content unique-xyz")
            self.assertFalse(list((paths.root / USER_DELIVERY_DIR_NAME).glob("*.pdf")))


class UserDeliveryPackageTests(unittest.TestCase):
    def _success_row(self, paths, source: Path) -> dict[str, str]:
        return {
            "task_id": "paper-0001",
            "doi": "10.1000/example",
            "title": "Example paper",
            "authors": "Example",
            "year": "2024",
            "status": "oa_downloaded",
            "source": "oa",
            "file": str(source),
            "reason": "",
        }

    def test_user_delivery_has_four_items_without_supplements_and_copies_input(self) -> None:
        from paper_automation.batch_workflow import (
            USER_DELIVERY_DIR_NAME,
            USER_INVENTORY_FIELDS,
            USER_INVENTORY_NAME,
            _snapshot_input_source,
            create_batch_paths,
            publish_user_delivery,
        )

        with TemporaryDirectory() as tmp:
            paths = create_batch_paths(tmp, run_name="package_no_supplement", fixed=True)
            source_input = Path(tmp) / "papers.md"
            source_input.write_bytes("# DOI list\n10.1000/example\n".encode("utf-8"))
            _snapshot_input_source(paths, input_text=None, input_path=source_input)
            source_pdf = paths.pdfs / "2024-Example-Example-paper.pdf"
            source_pdf.write_bytes(b"%PDF-1.4 package-test")

            publish_user_delivery(paths, [self._success_row(paths, source_pdf)])
            delivery = paths.root / USER_DELIVERY_DIR_NAME
            self.assertEqual(
                {path.name for path in delivery.iterdir()},
                {source_input.name, USER_INVENTORY_NAME, "pdf", "md"},
            )
            self.assertEqual(
                (delivery / "pdf" / source_pdf.name).read_bytes(),
                source_pdf.read_bytes(),
            )
            self.assertFalse((delivery / "补充材料").exists())
            inventory_path = delivery / USER_INVENTORY_NAME
            raw_inventory = inventory_path.read_bytes()
            self.assertTrue(raw_inventory.startswith(b"\xef\xbb\xbf"))
            reader = csv.DictReader(io.StringIO(raw_inventory.decode("utf-8-sig")))
            self.assertEqual(reader.fieldnames, USER_INVENTORY_FIELDS)
            inventory_rows = list(reader)
            self.assertEqual(inventory_rows[0]["结果文件"], "结果/pdf/2024-Example-Example-paper.pdf")
            self.assertEqual(inventory_rows[0]["补充材料"], "")

    def test_user_delivery_groups_supplements_in_one_directory(self) -> None:
        from paper_automation.batch_workflow import (
            USER_DELIVERY_DIR_NAME,
            create_batch_paths,
            publish_user_delivery,
        )

        with TemporaryDirectory() as tmp:
            paths = create_batch_paths(tmp, run_name="package_supplement", fixed=True)
            source_pdf = paths.pdfs / "2024-Example-Example-paper.pdf"
            source_pdf.write_bytes(b"%PDF-1.4 supplement-test")
            supplement = paths.reports / "sciencedirect" / "supplements" / source_pdf.stem
            supplement.mkdir(parents=True)
            (supplement / "S01-data.xlsx").write_bytes(b"supplement")

            publish_user_delivery(paths, [self._success_row(paths, source_pdf)])
            delivery = paths.root / USER_DELIVERY_DIR_NAME
            target = delivery / "补充材料" / source_pdf.stem / "S01-data.xlsx"
            self.assertEqual(target.read_bytes(), b"supplement")
            self.assertNotIn("_supplements", {path.name for path in delivery.iterdir()})
            inventory = (delivery / "下载清单.csv").read_text(encoding="utf-8-sig")
            self.assertIn(f"结果/补充材料/{source_pdf.stem}", inventory)

    def test_republish_preserves_md_supplements_and_manual_pdf(self) -> None:
        from paper_automation.batch_workflow import (
            USER_DELIVERY_DIR_NAME,
            _snapshot_input_source,
            create_batch_paths,
            publish_user_delivery,
        )

        with TemporaryDirectory() as tmp:
            paths = create_batch_paths(tmp, run_name="package_preserve", fixed=True)
            source_input = Path(tmp) / "papers.csv"
            source_input.write_text("doi\n10.1000/example\n", encoding="utf-8")
            _snapshot_input_source(paths, input_text=None, input_path=source_input)
            source_pdf = paths.pdfs / "2024-Example-Example-paper.pdf"
            source_pdf.write_bytes(b"%PDF-1.4 preserve-test")
            row = self._success_row(paths, source_pdf)
            publish_user_delivery(paths, [row])

            delivery = paths.root / USER_DELIVERY_DIR_NAME
            (delivery / "md" / "nested").mkdir(parents=True)
            (delivery / "md" / "nested" / "paper.md").write_text("# keep", encoding="utf-8")
            (delivery / "补充材料" / "manual").mkdir(parents=True)
            (delivery / "补充材料" / "manual" / "notes.txt").write_text("keep", encoding="utf-8")
            (delivery / "pdf" / "manual.pdf").write_bytes(b"%PDF-1.4 manual")

            publish_user_delivery(paths, [row])
            self.assertEqual((delivery / "md" / "nested" / "paper.md").read_text(encoding="utf-8"), "# keep")
            self.assertEqual((delivery / "补充材料" / "manual" / "notes.txt").read_text(encoding="utf-8"), "keep")
            self.assertEqual((delivery / "pdf" / "manual.pdf").read_bytes(), b"%PDF-1.4 manual")


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

    def test_refresh_scans_pdf_subdirectory_and_maps_failed_doi(self) -> None:
        from paper_automation.batch_workflow import (
            USER_DELIVERY_DIR_NAME,
            create_batch_paths,
            load_batch_state,
            save_batch_state,
        )
        from paper_automation.delivery_refresh import refresh_delivery

        with TemporaryDirectory() as tmp:
            paths = create_batch_paths(tmp, run_name="a3_pdf_subdir", fixed=True)
            pdf_dir = paths.root / USER_DELIVERY_DIR_NAME / "pdf"
            pdf_dir.mkdir(parents=True, exist_ok=True)
            pdf = pdf_dir / "manual-drop.pdf"
            pdf.write_bytes(b"%PDF-1.4 DOI 10.1000/xyz.123")
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
                        "task_id": "paper-0001",
                        "doi": "10.1000/xyz.123",
                        "title": "Manual drop",
                        "status": "no_open_pdf",
                        "source": "zotero",
                        "file": "",
                        "reason": "no_available_pdf",
                    }
                ],
            }
            save_batch_state(paths, state)

            result = refresh_delivery(paths.root, apply_rename=False)
            refreshed = load_batch_state(paths.root)["rows"][0]
            self.assertEqual(refreshed["status"], "manual_imported")
            self.assertEqual(result.mapped_to_row, 1)
            self.assertTrue((paths.root / USER_DELIVERY_DIR_NAME / "pdf" / "manual-drop.pdf").is_file())
            inventory = result.inventory_path.read_text(encoding="utf-8-sig")
            self.assertIn("manual-drop.pdf", inventory)
            self.assertEqual(inventory.count("paper-0001"), 1)


if __name__ == "__main__":
    unittest.main()
