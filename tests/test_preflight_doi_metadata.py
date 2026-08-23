from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from preflight_doi_metadata import parse_markdown_table, preflight_one


class PreflightDoiMetadataTests(unittest.TestCase):
    def test_parses_rows_without_notes_cell(self) -> None:
        text = """# list
| No. | Journal family | Journal title | Year | Volume | Issue | Pages | Article title | Authors | Material category | Specific alloy/system | Topic tag | DOI | Source checked | Confidence | Notes |
|---:|---|---|---:|---:|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Acta | Acta Materialia | 2024 | 1 | 2 | 3-4 | A <i>β</i> title | Li, A | Titanium | Ti | phase | 10.1016/j.test.2024.1 | crossref | high
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.md"
            path.write_text(text, encoding="utf-8")
            rows = parse_markdown_table(path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_index"], "1")
        self.assertEqual(rows[0]["source_title"], "A <i>β</i> title")
        self.assertEqual(rows[0]["input_doi"], "10.1016/j.test.2024.1")

    def test_crossref_metadata_becomes_download_ready_columns(self) -> None:
        source = {
            "source_index": "1",
            "journal_family": "Acta",
            "source_journal": "Acta Materialia",
            "source_year": "2024",
            "source_volume": "1",
            "source_issue": "2",
            "source_pages": "3-4",
            "source_title": "A beta title",
            "source_authors": "Li, A",
            "source_category": "Titanium",
            "source_system": "Ti",
            "source_topic": "phase",
            "input_doi": "10.1016/j.test.2024.1",
            "source_checked": "crossref",
            "source_confidence": "high",
        }

        def getter(_doi: str, _timeout: int):
            return 200, {
                "message": {
                    "DOI": "10.1016/J.TEST.2024.1",
                    "title": ["A beta title"],
                    "author": [{"family": "Li", "given": "A"}],
                    "container-title": ["Acta Materialia"],
                    "published": {"date-parts": [[2024]]},
                    "publisher": "Elsevier",
                    "type": "journal-article",
                }
            }, {}

        row = preflight_one(source, timeout=1, retries=0, getter=getter)
        self.assertEqual(row["preflight_status"], "verified_crossref")
        self.assertEqual(row["doi"], "10.1016/j.test.2024.1")
        self.assertEqual(row["authors"], "Li A")
        self.assertEqual(row["year"], "2024")


if __name__ == "__main__":
    unittest.main()
