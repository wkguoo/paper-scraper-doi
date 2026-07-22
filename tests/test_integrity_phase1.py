from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr
from dataclasses import asdict
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from paper_automation.artifact_store import (
    make_artifact_filename,
    paper_identity,
    publish_pdf_bytes_atomic,
)
from paper_automation.batch_stages import BatchOptions
from paper_automation import batch_workflow as workflow
from paper_automation.pdf_validation import minimal_pdf_bytes


class _TerminalGateway:
    def run_initial(self, rows, paths, options):
        return [
            {
                **row,
                "status": "duplicate",
                "source": "input",
                "file": "",
                "reason": "test_terminal",
            }
            for row in rows
        ]


def _normalizer_from_text(*, input_text, **_kwargs):
    values = [part.strip().lower() for part in str(input_text or "").split() if part.strip()]
    return [
        {
            "task_id": f"paper-{index:04d}",
            "source_index": str(index),
            "input_doi": doi,
            "doi": doi,
            "title": f"Title {doi}",
            "status": "pending",
        }
        for index, doi in enumerate(values, start=1)
    ]


def _success_row(task_id: str, doi: str, source: Path) -> dict[str, str]:
    return {
        "task_id": task_id,
        "source_index": task_id.rsplit("-", 1)[-1],
        "input_doi": doi,
        "input_title": "Same display title",
        "doi": doi,
        "title": "Same display title",
        "authors": "Zhang Wei",
        "journal": "Journal",
        "year": "2024",
        "publisher": "Publisher",
        "status": "oa_downloaded",
        "source": "oa",
        "file": str(source),
        "reason": "",
    }


def _tree_snapshot(root: Path) -> dict[str, tuple[str, bytes]]:
    snapshot: dict[str, tuple[str, bytes]] = {}
    if not root.exists():
        return snapshot
    for item in sorted(root.rglob("*"), key=lambda path: str(path).casefold()):
        relative = item.relative_to(root).as_posix()
        if item.is_dir() and not item.is_symlink():
            snapshot[relative] = ("dir", b"")
        elif item.is_file() and not item.is_symlink():
            snapshot[relative] = ("file", item.read_bytes())
        else:
            snapshot[relative] = ("special", b"")
    return snapshot


class InputIdentityV2Tests(unittest.TestCase):
    def test_changed_fixed_input_is_rejected_without_mutating_existing_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            started = workflow.start_batch(
                input_text="10.1000/a\n10.1000/b",
                input_path=None,
                output_root=root,
                run_name="fixed",
                options=BatchOptions(),
                gateway=_TerminalGateway(),
                normalizer=_normalizer_from_text,
                doi_preflight=False,
            )
            state = workflow.load_batch_state(started.paths.root)
            self.assertEqual(state["version"], 2)
            self.assertEqual(state["input_identity"]["input_count"], 2)

            before = {
                "state": started.paths.state.read_bytes(),
                "normalized": started.paths.normalized_input.read_bytes(),
                "delivery": _tree_snapshot(started.paths.root / workflow.USER_DELIVERY_DIR_NAME),
                "inventory": (started.paths.root / workflow.USER_INVENTORY_NAME).read_bytes(),
                "ownership": (started.paths.working / workflow.DELIVERY_OWNED_NAME).read_bytes(),
            }
            with self.assertRaisesRegex(ValueError, "^input_changed_for_existing_run$"):
                workflow.start_batch(
                    input_text="10.1000/c",
                    input_path=None,
                    output_root=root,
                    run_name="fixed",
                    options=BatchOptions(),
                    gateway=_TerminalGateway(),
                    normalizer=_normalizer_from_text,
                    doi_preflight=False,
                )
            after = {
                "state": started.paths.state.read_bytes(),
                "normalized": started.paths.normalized_input.read_bytes(),
                "delivery": _tree_snapshot(started.paths.root / workflow.USER_DELIVERY_DIR_NAME),
                "inventory": (started.paths.root / workflow.USER_INVENTORY_NAME).read_bytes(),
                "ownership": (started.paths.working / workflow.DELIVERY_OWNED_NAME).read_bytes(),
            }
            self.assertEqual(after, before)

            # Whitespace and order changes keep the original task ordering.
            workflow.start_batch(
                input_text=" 10.1000/b   10.1000/a ",
                input_path=None,
                output_root=root,
                run_name="fixed",
                options=BatchOptions(),
                gateway=_TerminalGateway(),
                normalizer=_normalizer_from_text,
                doi_preflight=False,
            )
            resumed = workflow.load_batch_state(started.paths.root)
            self.assertEqual(
                [row["doi"] for row in resumed["rows"]],
                ["10.1000/a", "10.1000/b"],
            )

    def test_v1_start_upgrades_only_after_task_match_and_retry_stays_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            started = workflow.start_batch(
                input_text="10.1000/a 10.1000/b",
                input_path=None,
                output_root=root,
                run_name="legacy",
                options=BatchOptions(),
                gateway=_TerminalGateway(),
                normalizer=_normalizer_from_text,
                doi_preflight=False,
            )
            state = workflow.load_batch_state(started.paths.root)
            state["version"] = 1
            state.pop("input_identity")
            workflow.save_batch_state(started.paths, state)

            workflow.retry_failed_batch(started.paths.root, gateway=_TerminalGateway())
            self.assertEqual(workflow.load_batch_state(started.paths.root)["version"], 1)

            workflow.start_batch(
                input_text="10.1000/b 10.1000/a",
                input_path=None,
                output_root=root,
                run_name="legacy",
                options=BatchOptions(),
                gateway=_TerminalGateway(),
                normalizer=_normalizer_from_text,
                doi_preflight=False,
            )
            upgraded = workflow.load_batch_state(started.paths.root)
            self.assertEqual(upgraded["version"], 2)
            self.assertIn("input_identity", upgraded)

            upgraded["version"] = 1
            upgraded.pop("input_identity")
            workflow.save_batch_state(started.paths, upgraded)
            before = started.paths.state.read_bytes()
            with self.assertRaisesRegex(ValueError, "^input_changed_for_existing_run$"):
                workflow.start_batch(
                    input_text="10.1000/c",
                    input_path=None,
                    output_root=root,
                    run_name="legacy",
                    options=BatchOptions(),
                    gateway=_TerminalGateway(),
                    normalizer=_normalizer_from_text,
                    doi_preflight=False,
                )
            self.assertEqual(started.paths.state.read_bytes(), before)

    def test_cli_reports_changed_fixed_input_with_exit_code_two(self) -> None:
        from paper_batch import main

        stderr = StringIO()
        with patch(
            "paper_batch.start_batch",
            side_effect=ValueError("input_changed_for_existing_run"),
        ), redirect_stderr(stderr):
            exit_code = main(["start", "--text", "10.1000/new"])

        self.assertEqual(exit_code, 2)
        message = stderr.getvalue()
        self.assertIn("input_changed_for_existing_run", message)
        self.assertIn("--fresh", message)
        self.assertIn("--run-name", message)


class ArtifactPublisherTests(unittest.TestCase):
    def test_identity_priority_and_concurrent_same_name_publication(self) -> None:
        first = {"doi": "10.1000/A", "pii": "S0000", "title": "Same"}
        second = {"doi": "10.1000/B", "pii": "S0000", "title": "Same"}
        self.assertNotEqual(paper_identity(first).digest, paper_identity(second).digest)
        self.assertNotEqual(
            make_artifact_filename(1, first),
            make_artifact_filename(1, second),
        )

        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)
            contents = [minimal_pdf_bytes(b"first"), minimal_pdf_bytes(b"second")]
            with ThreadPoolExecutor(max_workers=2) as pool:
                published = list(
                    pool.map(
                        lambda content: publish_pdf_bytes_atomic(
                            content,
                            destination,
                            "paper-0001_same.pdf",
                        ),
                        contents,
                    )
                )
            self.assertEqual(len({path.name for path in published}), 2)
            self.assertEqual(
                {path.read_bytes() for path in destination.glob("*.pdf")},
                set(contents),
            )
            self.assertEqual(list(destination.glob(".pdf_bytes_*.tmp")), [])
            self.assertEqual(list(destination.glob(".pdf_snapshot_*.tmp")), [])

    def test_invalid_same_name_is_preserved_and_valid_pdf_uses_hash_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)
            occupied = destination / "paper.pdf"
            occupied.write_bytes(b"<html>institution login</html>")
            content = minimal_pdf_bytes(b"verified replacement candidate")

            published = publish_pdf_bytes_atomic(content, destination, occupied.name)

            self.assertEqual(occupied.read_bytes(), b"<html>institution login</html>")
            self.assertNotEqual(published, occupied)
            self.assertEqual(published.read_bytes(), content)
            self.assertIn(hashlib.sha256(content).hexdigest()[:8], published.stem)

    def test_copy_rejects_a_symlink_source_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            actual = root / "actual.pdf"
            actual.write_bytes(minimal_pdf_bytes(b"symlink source"))
            link = root / "source-link.pdf"
            try:
                link.symlink_to(actual)
            except OSError as exc:
                self.skipTest(f"symlink_not_available:{exc}")

            with self.assertRaisesRegex(ValueError, "reparse_point"):
                workflow.copy_pdf_safely(link, root / "published", "paper.pdf")
            self.assertFalse(list((root / "published").glob("*.pdf")))

    def test_unified_stage_copy_uses_task_and_identity_not_display_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_a = root / "stage-a.pdf"
            source_b = root / "stage-b.pdf"
            source_a.write_bytes(minimal_pdf_bytes(b"stage a"))
            source_b.write_bytes(minimal_pdf_bytes(b"stage b"))
            paths = workflow.create_batch_paths(root, run_name="artifacts", fixed=True)
            rows = [
                {**_success_row("paper-0001", "10.1000/a", source_a), "status": "downloaded"},
                {**_success_row("paper-0002", "10.1000/b", source_b), "status": "downloaded"},
            ]
            copied = [workflow._copy_successful_pdf(row, paths) for row in rows]
            names = [Path(row["file"]).name for row in copied]
            self.assertEqual(names[0], make_artifact_filename(1, rows[0]))
            self.assertEqual(names[1], make_artifact_filename(2, rows[1]))
            self.assertNotEqual(names[0], names[1])

    def test_supplements_match_identity_when_stage_index_differs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = workflow.create_batch_paths(root, run_name="supplements", fixed=True)
            row = _success_row("paper-0099", "10.1000/supplement", root / "source.pdf")
            identity = paper_identity(row)
            stage_folder = (
                paths.reports
                / "sciencedirect"
                / "supplements"
                / f"paper-0001_{identity.digest}"
            )
            stage_folder.mkdir(parents=True)
            (stage_folder / "supporting.zip").write_bytes(b"supplement")

            self.assertEqual(workflow._collect_supplement_dirs(row, paths), [stage_folder])

    def test_zotero_does_not_reuse_identical_bytes_across_paper_identities(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            attachment = root / "attachment.pdf"
            attachment.write_bytes(minimal_pdf_bytes(b"identical attachment bytes"))
            paths = workflow.create_batch_paths(root, run_name="zotero-identity", fixed=True)
            rows = [
                _success_row("paper-0001", "10.1000/a", attachment),
                _success_row("paper-0002", "10.1000/b", attachment),
            ]

            published = [
                workflow._copy_zotero_attachment(row, str(attachment), paths)
                for row in rows
            ]

            self.assertNotEqual(published[0], published[1])
            self.assertEqual(
                {path.name for path in published},
                {
                    make_artifact_filename(1, rows[0]),
                    make_artifact_filename(2, rows[1]),
                },
            )

    def test_oa_institutional_and_sciencedirect_identity_names_are_distinct(self) -> None:
        from paper_automation import workflow as oa_workflow
        from paper_automation.institutional.models import InstitutionalPaper
        from paper_automation.institutional.workflow import _make_filename
        from paper_automation.models import DownloadResponse, MetadataResult, PdfCandidate
        from sd_scraper import ScienceDirectScraper

        def resolve(candidate):
            return MetadataResult(
                source_index=candidate.source_index,
                query_title="Same display title",
                doi=candidate.doi,
                title="Same display title",
                authors=["Zhang Wei"],
                year="2024",
                is_oa=True,
            )

        with tempfile.TemporaryDirectory() as temporary, patch.object(
            oa_workflow.MetadataResolver,
            "resolve_one",
            side_effect=resolve,
        ), patch.object(
            oa_workflow,
            "choose_pdf_candidate",
            return_value=PdfCandidate("https://example.test/paper.pdf", "repository"),
        ):
            result = oa_workflow.run_workflow(
                "10.1000/a\n10.1000/b",
                temporary,
                artifact_filenames=True,
                http_bytes=lambda *_args, **_kwargs: DownloadResponse(
                    minimal_pdf_bytes(b"same body"),
                    "application/pdf",
                ),
            )
            oa_names = sorted(path.name for path in Path(result.output_dir, "pdfs").glob("*.pdf"))
        self.assertEqual(len(oa_names), 2)
        self.assertNotEqual(oa_names[0], oa_names[1])

        institutional_papers = [
            InstitutionalPaper(
                row_number=index + 1,
                input_doi=doi,
                doi=doi,
                title="Same display title",
                authors=("Zhang Wei",),
                year="2024",
            )
            for index, doi in enumerate(("10.1000/a", "10.1000/b"), start=1)
        ]
        institutional_names = [
            _make_filename(paper, artifact_filenames=True)
            for paper in institutional_papers
        ]
        self.assertNotEqual(institutional_names[0], institutional_names[1])

        scraper = object.__new__(ScienceDirectScraper)
        scraper.artifact_filenames = True
        sd_articles = [
            {
                "doi": doi,
                "pii": "SAMEPII",
                "title": "Same display title",
                "authors": ["Zhang Wei"],
                "year": "2024",
            }
            for doi in ("10.1000/a", "10.1000/b")
        ]
        sd_names = [scraper._pdf_filename(index, article) for index, article in enumerate(sd_articles, 1)]
        self.assertNotEqual(sd_names[0], sd_names[1])
        self.assertEqual(
            {paper_identity({"doi": doi}).digest for doi in ("10.1000/a", "10.1000/b")},
            {Path(name).stem.rsplit("_", 1)[-1] for name in sd_names},
        )


class DeliveryIntegrityTests(unittest.TestCase):
    def test_final_revalidation_downgrades_invalid_success_and_persists_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bad = root / "login.pdf"
            bad.write_bytes(b"<html>login</html>")
            paths = workflow.create_batch_paths(root, run_name="revalidate", fixed=True)
            row = _success_row("paper-0001", "10.1000/a", bad)
            state = {
                "version": 1,
                "run_dir": str(paths.root),
                "manual_retry_used": True,
                "options": asdict(BatchOptions()),
                "rows": [row],
            }
            workflow.save_batch_state(paths, state)
            workflow._write_latest_state_outputs(
                paths,
                state,
                pending_manual_retry_used=True,
            )
            saved = workflow.load_batch_state(paths.root)["rows"][0]
            self.assertEqual(saved["status"], "not_pdf_response")
            self.assertEqual(saved["file"], "")
            self.assertEqual(saved["reason"], "delivery_pdf_revalidation_failed")
            with (paths.root / workflow.USER_INVENTORY_NAME).open(
                "r", newline="", encoding="utf-8-sig"
            ) as handle:
                inventory = list(csv.DictReader(handle))
            self.assertEqual(inventory[0]["状态"], "失败")
            self.assertEqual(inventory[0]["结果文件"], "")

    def test_identity_collision_manual_files_and_empty_directories_survive_republish(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_a = root / "source-a.pdf"
            source_b = root / "source-b.pdf"
            original_a = minimal_pdf_bytes(b"source-a")
            original_b = minimal_pdf_bytes(b"source-b")
            source_a.write_bytes(original_a)
            source_b.write_bytes(original_b)
            paths = workflow.create_batch_paths(root, run_name="delivery", fixed=True)
            rows = [
                _success_row("paper-0001", "10.1000/a", source_a),
                _success_row("paper-0002", "10.1000/b", source_b),
            ]
            workflow.publish_user_delivery(paths, rows)
            manifest_path = paths.working / workflow.DELIVERY_OWNED_NAME
            first_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            program_pdfs = [
                item for item in first_manifest["files"] if item["file_type"] == "pdf"
            ]
            self.assertEqual(len(program_pdfs), 2)
            for row, item in zip(rows, program_pdfs):
                self.assertIn(paper_identity(row).digest, Path(item["relative_path"]).name)

            results = paths.root / workflow.USER_DELIVERY_DIR_NAME
            first_program = paths.root.joinpath(*program_pdfs[0]["relative_path"].split("/"))
            user_modified = minimal_pdf_bytes(b"user modified program file")
            first_program.write_bytes(user_modified)
            nested = results / "manual" / "nested"
            nested.mkdir(parents=True)
            (nested / "hand.pdf").write_bytes(b"manual non-validated pdf")
            (nested / "notes.txt").write_text("keep me", encoding="utf-8")
            (results / "supplement.zip").write_bytes(b"zip-like user payload")
            (results / "empty-folder").mkdir()
            inventory_path = paths.root / workflow.USER_INVENTORY_NAME
            user_inventory = inventory_path.read_bytes() + b"\r\nuser note"
            inventory_path.write_bytes(user_inventory)

            workflow.publish_user_delivery(paths, rows)
            second_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(second_manifest["generation"], 2)
            self.assertTrue((nested / "hand.pdf").is_file())
            self.assertEqual((nested / "notes.txt").read_text(encoding="utf-8"), "keep me")
            self.assertEqual((results / "supplement.zip").read_bytes(), b"zip-like user payload")
            self.assertTrue((results / "empty-folder").is_dir())
            manualized = list(first_program.parent.glob(f"{first_program.stem}_manual_*{first_program.suffix}"))
            self.assertEqual(len(manualized), 1)
            self.assertEqual(manualized[0].read_bytes(), user_modified)
            self.assertEqual(first_program.read_bytes(), original_a)
            manual_inventories = list(paths.root.glob("下载清单_manual_*.csv"))
            self.assertEqual(len(manual_inventories), 1)
            self.assertEqual(manual_inventories[0].read_bytes(), user_inventory)

    def test_each_delivery_publish_failure_rolls_back_all_three_targets(self) -> None:
        for target_kind in ("results", "inventory", "manifest"):
            with self.subTest(target_kind=target_kind), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / "source.pdf"
                source.write_bytes(minimal_pdf_bytes(b"generation one"))
                paths = workflow.create_batch_paths(root, run_name="rollback", fixed=True)
                rows = [_success_row("paper-0001", "10.1000/a", source)]
                workflow.publish_user_delivery(paths, rows)
                results = paths.root / workflow.USER_DELIVERY_DIR_NAME
                inventory = paths.root / workflow.USER_INVENTORY_NAME
                manifest = paths.working / workflow.DELIVERY_OWNED_NAME
                targets = {
                    "results": results,
                    "inventory": inventory,
                    "manifest": manifest,
                }
                before = (_tree_snapshot(results), inventory.read_bytes(), manifest.read_bytes())
                source.write_bytes(minimal_pdf_bytes(b"generation two"))
                real_replace = workflow.os.replace
                failed_once = False

                def fail_selected_publish(source_path, destination_path):
                    nonlocal failed_once
                    if Path(destination_path) == targets[target_kind] and not failed_once:
                        failed_once = True
                        raise OSError(f"synthetic {target_kind} publish failure")
                    return real_replace(source_path, destination_path)

                with patch.object(workflow.os, "replace", side_effect=fail_selected_publish):
                    with self.assertRaisesRegex(OSError, f"synthetic {target_kind} publish failure"):
                        workflow.publish_user_delivery(paths, rows)
                after = (_tree_snapshot(results), inventory.read_bytes(), manifest.read_bytes())
                self.assertTrue(failed_once)
                self.assertEqual(after, before)

    def test_legacy_inventory_owns_only_its_exact_result_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = workflow.create_batch_paths(root, run_name="legacy-delivery", fixed=True)
            results = paths.root / workflow.USER_DELIVERY_DIR_NAME
            results.mkdir()
            old_program = results / "old-program.pdf"
            old_program.write_bytes(minimal_pdf_bytes(b"old program"))
            manual = results / "manual" / "keep.pdf"
            manual.parent.mkdir()
            manual.write_bytes(b"manual payload")
            note = results / "notes.txt"
            note.write_text("keep note", encoding="utf-8")
            inventory = paths.root / workflow.USER_INVENTORY_NAME
            with inventory.open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=workflow.USER_INVENTORY_FIELDS)
                writer.writeheader()
                writer.writerow(
                    {
                        "序号": "1",
                        "状态": "成功",
                        "结果文件": f"{workflow.USER_DELIVERY_DIR_NAME}/old-program.pdf",
                    }
                )

            workflow.publish_user_delivery(paths, [])
            self.assertFalse(old_program.exists())
            self.assertEqual(manual.read_bytes(), b"manual payload")
            self.assertEqual(note.read_text(encoding="utf-8"), "keep note")
            manifest = json.loads(
                (paths.working / workflow.DELIVERY_OWNED_NAME).read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["generation"], 1)

    def test_unowned_symlink_aborts_before_delivery_switch_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = workflow.create_batch_paths(root, run_name="reparse", fixed=True)
            results = paths.root / workflow.USER_DELIVERY_DIR_NAME
            results.mkdir()
            external = root / "external.pdf"
            external.write_bytes(minimal_pdf_bytes(b"external"))
            link = results / "manual-link.pdf"
            try:
                link.symlink_to(external)
            except OSError as exc:
                self.skipTest(f"symlink_not_available:{exc}")
            before = _tree_snapshot(results)
            with self.assertRaisesRegex(ValueError, "delivery_unowned_reparse_point"):
                workflow.publish_user_delivery(paths, [])
            self.assertEqual(_tree_snapshot(results), before)
            self.assertFalse((paths.root / workflow.USER_INVENTORY_NAME).exists())


if __name__ == "__main__":
    unittest.main()
