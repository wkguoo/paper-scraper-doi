from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class BatchFileTests(unittest.TestCase):
    def test_paths_and_state_are_created_under_new_run_directory(self) -> None:
        from paper_automation.batch_workflow import create_batch_paths, load_batch_state, save_batch_state

        with tempfile.TemporaryDirectory() as tmp:
            paths = create_batch_paths(Path(tmp), now=datetime(2026, 7, 10, 17, 0, 0))
            save_batch_state(paths, {"version": 1, "rows": []})

            self.assertEqual(paths.root.name, "paper_batch_20260710_170000")
            self.assertTrue(paths.pdfs.is_dir())
            self.assertTrue(paths.reports.is_dir())
            self.assertEqual(load_batch_state(paths.root)["version"], 1)

    def test_custom_run_name_is_cleaned_and_always_timestamped(self) -> None:
        from paper_automation.batch_workflow import create_batch_paths

        with tempfile.TemporaryDirectory() as tmp:
            paths = create_batch_paths(
                Path(tmp),
                run_name="Ti alloy batch",
                now=datetime(2026, 7, 10, 17, 0, 0),
            )

            self.assertEqual(paths.root.name, "Ti_alloy_batch_20260710_170000")

    def test_same_timestamp_creates_unique_run_directories(self) -> None:
        from paper_automation.batch_workflow import create_batch_paths

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            now = datetime(2026, 7, 10, 17, 0, 0)

            first = create_batch_paths(root, now=now)
            second = create_batch_paths(root, now=now)

            self.assertEqual(first.root.name, "paper_batch_20260710_170000")
            self.assertEqual(second.root.name, "paper_batch_20260710_170000_2")
            self.assertNotEqual(first.root, second.root)

    def test_run_name_rejects_absolute_and_traversal_paths(self) -> None:
        from paper_automation.batch_workflow import create_batch_paths

        with tempfile.TemporaryDirectory() as tmp:
            sandbox = Path(tmp)
            output_root = sandbox / "output"
            invalid_names = [
                str(sandbox / "absolute"),
                "..",
                "../escape",
                r"..\escape",
            ]

            for run_name in invalid_names:
                with self.subTest(run_name=run_name):
                    with self.assertRaisesRegex(ValueError, "invalid_run_name"):
                        create_batch_paths(output_root, run_name=run_name)

    def test_pdf_validation_and_copy_are_non_destructive_and_deduplicated(self) -> None:
        from paper_automation.batch_workflow import copy_pdf_safely, is_valid_pdf

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.pdf"
            source.write_bytes(b"%PDF-1.7\nvalid payload")
            destination = root / "pdfs"

            first = copy_pdf_safely(source, destination, "paper.pdf")
            second = copy_pdf_safely(source, destination, "paper.pdf")

            self.assertTrue(is_valid_pdf(first))
            self.assertEqual(first, second)
            self.assertTrue(source.exists())
            self.assertEqual(len(list(destination.glob("*.pdf"))), 1)

    def test_copy_rejects_absolute_and_traversal_filenames(self) -> None:
        from paper_automation.batch_workflow import copy_pdf_safely

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.pdf"
            source.write_bytes(b"%PDF-1.7\nvalid payload")
            destination = root / "pdfs"
            (destination / "nested").mkdir(parents=True)
            invalid_names = [
                str(root / "outside.pdf"),
                "../outside.pdf",
                r"..\outside.pdf",
                "nested/paper.pdf",
                r"nested\paper.pdf",
            ]

            for filename in invalid_names:
                with self.subTest(filename=filename):
                    with self.assertRaisesRegex(ValueError, "invalid_filename"):
                        copy_pdf_safely(source, destination, filename)

    def test_different_pdf_content_uses_hash_suffix_without_overwriting(self) -> None:
        from paper_automation.batch_workflow import copy_pdf_safely

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_source = root / "first.pdf"
            second_source = root / "second.pdf"
            first_payload = b"%PDF-1.7\nfirst payload"
            second_payload = b"%PDF-1.7\nsecond payload"
            first_source.write_bytes(first_payload)
            second_source.write_bytes(second_payload)
            destination = root / "pdfs"

            first = copy_pdf_safely(first_source, destination, "paper.pdf")
            second = copy_pdf_safely(second_source, destination, "paper.pdf")

            short_hash = hashlib.sha256(second_payload).hexdigest()[:8]
            self.assertEqual(first.name, "paper.pdf")
            self.assertEqual(second.name, f"paper_{short_hash}.pdf")
            self.assertEqual(first.read_bytes(), first_payload)
            self.assertEqual(second.read_bytes(), second_payload)

    def test_occupied_hash_candidate_gets_numeric_suffix_without_overwriting(self) -> None:
        from paper_automation.batch_workflow import copy_pdf_safely

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.pdf"
            source_payload = b"%PDF-1.7\nnew source payload"
            requested_payload = b"%PDF-1.7\nrequested target payload"
            occupied_payload = b"%PDF-1.7\noccupied hash payload"
            source.write_bytes(source_payload)
            destination = root / "pdfs"
            destination.mkdir()
            requested = destination / "paper.pdf"
            requested.write_bytes(requested_payload)
            short_hash = hashlib.sha256(source_payload).hexdigest()[:8]
            occupied = destination / f"paper_{short_hash}.pdf"
            occupied.write_bytes(occupied_payload)

            copied = copy_pdf_safely(source, destination, "paper.pdf")

            self.assertEqual(copied.name, f"paper_{short_hash}_2.pdf")
            self.assertEqual(requested.read_bytes(), requested_payload)
            self.assertEqual(occupied.read_bytes(), occupied_payload)
            self.assertEqual(copied.read_bytes(), source_payload)

    def test_non_pdf_is_rejected(self) -> None:
        from paper_automation.batch_workflow import copy_pdf_safely

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "login.pdf"
            source.write_text("<html>login</html>", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not_pdf_response"):
                copy_pdf_safely(source, Path(tmp) / "pdfs", "paper.pdf")
