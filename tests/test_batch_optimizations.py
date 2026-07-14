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


if __name__ == "__main__":
    unittest.main()
