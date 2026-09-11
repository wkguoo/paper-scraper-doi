from __future__ import annotations

import csv
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from paper_automation import batch_workflow as workflow
from paper_automation.batch_stages import BatchOptions


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/paper-download/scripts/collect_existing_pdfs.py"
spec = importlib.util.spec_from_file_location("collect_existing_pdfs", SCRIPT)
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


def paper(key="PAPER001", doi="10.1016/0956-716X(92)90275-J"):
    return {"key": key, "data": {"itemType": "journalArticle", "DOI": doi}}


def attachment(key="ATTACH01", title="Full Text", filename="main.pdf"):
    return {"key": key, "data": {
        "itemType": "attachment", "contentType": "application/pdf",
        "title": title, "filename": filename,
    }}


def row(task="paper-0001", doi="10.1016/0956-716x(92)90275-j"):
    return dict(zip(workflow.NORMALIZED_FIELDS, [
        task, task[-1], doi, "Densification study", doi, "Densification study",
        "Smith", "Journal", "2024", "Publisher", "unsupported_publisher",
        "institutional", "", "original_institutional_reason",
    ]))


def fixture(root, rows):
    paths = workflow.create_batch_paths(root, run_name="fixture", fixed=True)
    workflow.save_batch_state(paths, {
        "version": 1, "run_dir": str(paths.root), "manual_retry_used": True,
        "options": asdict(BatchOptions()), "rows": rows,
    })
    workflow._write_pending_files(paths, rows, manual_retry_used=True)
    return paths


class ExistingPDFTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pdf = self.root / "中文 空格.pdf"
        self.pdf.write_bytes(b"%PDF-1.7\n" + b"test fixture\n" * 100 + b"%%EOF\n")
        self.calls = []
        self.data = {
            "/api/users/0/items/top?includeTrashed=0": [paper()],
            "/api/users/0/items/PAPER001/children": [attachment()],
            "/api/users/0/items/ATTACH01/file/view/url": self.pdf.as_uri(),
        }

    def read(self, path):
        self.calls.append(path)
        value = self.data[path]
        if isinstance(value, Exception):
            raise value
        return value

    def test_exact_doi_case_parentheses_and_scoped_key(self):
        successes, reports = collector.lookup([row()], self.read)
        self.assertEqual(successes[0]["zotero_item_id"], "users/0/items/PAPER001")
        self.assertEqual(Path(successes[0]["attachment_path"]), self.pdf)
        self.assertEqual(reports[0]["prior_reason"], "original_institutional_reason")
        self.assertEqual(len(self.calls), 3)

    def test_non_exact_and_duplicate_doi_matches_are_not_selected(self):
        self.data[self.calls_path] = [paper(doi=row()["doi"] + "extra")]
        successes, reports = collector.lookup([row()], self.read)
        self.assertEqual(successes, [])
        self.assertEqual(reports[0]["status"], "not_found")
        self.data[self.calls_path] = [paper(), paper("PAPER002")]
        successes, reports = collector.lookup([row()], self.read)
        self.assertEqual(successes, [])
        self.assertEqual(reports[0]["reason"], "multiple_doi_matches")
        self.assertEqual(len(json.loads(reports[0]["candidates"])), 2)
        self.assertTrue(all(path == self.calls_path for path in self.calls))

    calls_path = "/api/users/0/items/top?includeTrashed=0"

    def test_missing_invalid_and_nonlocal_files_do_not_succeed(self):
        invalid = self.root / "invalid.pdf"
        invalid.write_text("not a PDF")
        for url in ((self.root / "missing.pdf").as_uri(), invalid.as_uri(), "https://example.org/paper.pdf", "file://server/shared/paper.pdf"):
            with self.subTest(url=url):
                self.data["/api/users/0/items/ATTACH01/file/view/url"] = url
                successes, reports = collector.lookup([row()], self.read)
                self.assertEqual(successes, [])
                self.assertEqual(reports[0]["status"], "no_pdf")

    def test_supplement_is_excluded_and_distinct_main_pdfs_are_ambiguous(self):
        extra = self.root / "second.pdf"
        extra.write_bytes(self.pdf.read_bytes().replace(b"test fixture", b"other paper!"))
        self.data["/api/users/0/items/PAPER001/children"].append(
            attachment("ATTACH02", "PDF", "supplementary_information.pdf"),
        )
        self.data["/api/users/0/items/ATTACH02/file/view/url"] = extra.as_uri()
        successes, reports = collector.lookup([row()], self.read)
        self.assertEqual(len(successes), 1)
        self.assertEqual(json.loads(reports[0]["candidates"])[1]["status"], "supplement_excluded")
        self.data["/api/users/0/items/PAPER001/children"][1] = attachment("ATTACH02")
        successes, reports = collector.lookup([row()], self.read)
        self.assertEqual(successes, [])
        self.assertEqual(reports[0]["reason"], "multiple_distinct_pdfs")
        extra.write_bytes(self.pdf.read_bytes())
        successes, _ = collector.lookup([row()], self.read)
        self.assertEqual(len(successes), 1)

    def test_child_api_error_is_reported_without_losing_sibling_success(self):
        self.data[self.calls_path].append(paper("PAPER002", "10.1000/second"))
        self.data["/api/users/0/items/PAPER002/children"] = RuntimeError("zotero_api_http_403")
        successes, reports = collector.lookup([row(), row("paper-0002", "10.1000/second")], self.read)
        self.assertEqual(len(successes), 1)
        self.assertEqual(reports[1]["reason"], "zotero_api_http_403")

    def test_publisher_supplements_are_excluded_with_present_or_missing_main(self):
        supplement = self.root / "supplement.pdf"
        supplement.write_bytes(self.pdf.read_bytes().replace(b"test fixture", b"supplement!!"))
        self.data["/api/users/0/items/ATTACH02/file/view/url"] = supplement.as_uri()
        for stem in (
            "1-s2.0-S1359645425009097-mmc1",
            "41586_2026_10265_MOESM1_ESM",
            "(☆)FeZrNb-supplementary",
        ):
            # Zotero 可能只在标题或文件名中保留原始补充材料标识。
            for title, filename in (("PDF", stem + ".pdf"), (stem, "renamed.pdf")):
                for main_exists in (True, False):
                    with self.subTest(title=title, filename=filename, main_exists=main_exists):
                        self.calls.clear()
                        self.data["/api/users/0/items/PAPER001/children"] = [
                            attachment(), attachment("ATTACH02", title, filename),
                        ]
                        main = self.pdf if main_exists else self.root / "missing-main.pdf"
                        self.data["/api/users/0/items/ATTACH01/file/view/url"] = main.as_uri()
                        successes, reports = collector.lookup([row()], self.read)
                        candidates = json.loads(reports[0]["candidates"])
                        self.assertEqual(candidates[1]["status"], "supplement_excluded")
                        self.assertNotIn("/api/users/0/items/ATTACH02/file/view/url", self.calls)
                        if main_exists:
                            self.assertEqual(len(successes), 1)
                            self.assertEqual(Path(successes[0]["attachment_path"]), self.pdf)
                        else:
                            self.assertEqual(successes, [])
                            self.assertEqual(reports[0]["status"], "no_pdf")
                            self.assertEqual(reports[0]["reason"], "no_valid_local_main_pdf")

    def test_si_in_a_scientific_title_does_not_mean_supporting_information(self):
        for title, filename in (
            ("Oxidation of Si powders", "2024-Smith-Si-powders.pdf"),
            ("Oxidation of Si", "2024-Smith-Oxidation-of-Si.pdf"),
        ):
            with self.subTest(title=title):
                self.data["/api/users/0/items/PAPER001/children"] = [
                    attachment(title=title, filename=filename),
                ]
                successes, _ = collector.lookup([row()], self.read)
                self.assertEqual(len(successes), 1)

    def test_collect_and_finalize_preserve_originals_failures_and_old_reports(self):
        supplement = self.root / "1-s2.0-S1359645425009097-mmc1.pdf"
        supplement.write_bytes(self.pdf.read_bytes().replace(b"test fixture", b"supplement!!"))
        supplement_hash = workflow._sha256(supplement)
        supplement_item = attachment("ATTACH02", "PDF", supplement.name)
        self.data["/api/users/0/items/PAPER001/children"].append(supplement_item)
        self.data["/api/users/0/items/ATTACH02/file/view/url"] = supplement.as_uri()
        # 第二篇只有补充材料：不能进入成功 CSV 或被 finalize 标为正文交付。
        self.data[self.calls_path].append(paper("PAPER002", "10.1000/missing"))
        self.data["/api/users/0/items/PAPER002/children"] = [
            attachment("ATTACH03", "PDF", supplement.name),
        ]
        self.data["/api/users/0/items/ATTACH03/file/view/url"] = supplement.as_uri()
        paths = fixture(self.root, [row(), row("paper-0002", "10.1000/missing")])
        before = paths.state.read_bytes()
        source_hash = workflow._sha256(self.pdf)
        with patch.object(collector, "official_reader", return_value=self.read):
            result = collector.collect(paths.root, self.root / "official.py")
        self.assertEqual(paths.state.read_bytes(), before)
        self.assertEqual(result["matched"], 1)
        csv_path = Path(result["results"])
        original_csv = csv_path.read_bytes()
        self.assertTrue(original_csv.startswith(b"\xef\xbb\xbf"))
        with csv_path.open(encoding="utf-8-sig", newline="") as handle:
            records = list(csv.reader(handle))
        self.assertEqual(records[0], workflow.ZOTERO_RESULT_FIELDS)
        self.assertEqual(len(records), 2)  # failure is audit-only
        with Path(result["report"]).open(encoding="utf-8-sig", newline="") as handle:
            reports = list(csv.DictReader(handle))
        self.assertEqual(reports[1]["status"], "no_pdf")
        self.assertEqual(reports[1]["prior_reason"], "original_institutional_reason")
        finalized = workflow.finalize_batch(paths.root, csv_path)
        self.assertEqual(finalized.success_count, 1)
        state = workflow.load_batch_state(paths.root)
        self.assertEqual(state["rows"][1]["reason"], "original_institutional_reason")
        self.assertEqual(state["rows"][1]["status"], "unsupported_publisher")
        delivered = list(workflow.user_pdf_dir(paths).glob("*.pdf"))
        self.assertEqual(len(delivered), 1)
        self.assertTrue(delivered[0].name.startswith("2024-Smith-Densification-study"))
        self.assertEqual(workflow._sha256(delivered[0]), source_hash)
        self.assertEqual(workflow._sha256(self.pdf), source_hash)
        self.assertEqual(workflow._sha256(supplement), supplement_hash)
        workflow.finalize_batch(paths.root, csv_path)
        with patch.object(collector, "official_reader", return_value=self.read):
            repeated = collector.collect(paths.root, self.root / "official.py")
        self.assertFalse(repeated["ready_to_finalize"])
        self.assertEqual(csv_path.read_bytes(), original_csv)
        self.assertNotEqual(repeated["results"], result["results"])
        self.assertEqual(len(list(workflow.user_pdf_dir(paths).glob("*.pdf"))), 1)

    def test_unavailable_helper_or_api_reports_without_batch_mutation(self):
        paths = fixture(self.root, [row()])
        before = paths.state.read_bytes()
        result = collector.collect(paths.root, self.root / "absent.py")
        self.assertFalse(result["ready_to_finalize"])
        self.assertIn("official_helper_missing", Path(result["report"]).read_text(encoding="utf-8-sig"))
        with patch.object(collector, "official_reader", side_effect=RuntimeError("zotero_api_http_403")):
            result = collector.collect(paths.root, self.root / "official.py")
        self.assertIn("zotero_api_http_403", Path(result["report"]).read_text(encoding="utf-8-sig"))
        self.assertEqual(paths.state.read_bytes(), before)

    def test_existing_queue_and_stale_fallback_are_rejected_before_lookup(self):
        paths = fixture(self.root, [row()])
        with patch.object(collector, "official_reader") as reader:
            paths.zotero_fallback.write_text(paths.zotero_fallback.read_text(encoding="utf-8-sig").replace("Densification", "Changed"), encoding="utf-8-sig")
            with self.assertRaisesRegex(ValueError, "fallback_state_mismatch"):
                collector.collect(paths.root, self.root / "official.py")
            (paths.working / "zotero_bridge_jobs.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "existing_bridge_batch"):
                collector.collect(paths.root, self.root / "official.py")
            reader.assert_not_called()
        self.assertEqual(list(paths.working.glob("zotero_results_existing_*.csv")), [])

    def test_official_helper_is_loaded_and_only_get_is_used(self):
        helper = self.root / "official.py"
        helper.write_text('''from types import SimpleNamespace
def request(path, *, method, timeout):
    assert method == "GET"
    return SimpleNamespace(status=200, payload=[{"route": path}])
def parse_body(response):
    return response.payload
def status_payload():
    raise AssertionError("must not inspect profiles or restart Zotero")
''', encoding="utf-8")
        self.assertEqual(collector.official_reader(helper)("/api/"), [{"route": "/api/"}])


class OptionalBridgeCLITests(unittest.TestCase):
    def test_three_commands_only_queue_with_explicit_opt_in(self):
        import paper_batch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = workflow.BatchRunResult(workflow.paths_from_run_dir(root), 1, 0, 1, 0, 1)
            for command in ("start", "retry-failed", "recover-oa"):
                for flags in ([], ["--no-auto-zotero"], ["--auto-zotero"]):
                    with self.subTest(command=command, flags=flags), ExitStack() as stack:
                        stack.enter_context(redirect_stdout(io.StringIO()))
                        stack.enter_context(patch("paper_batch.start_batch", return_value=result))
                        stack.enter_context(patch("paper_batch.retry_failed_batch", return_value=result))
                        stack.enter_context(patch("paper_batch.load_batch_state", return_value={"options": {}}))
                        stack.enter_context(patch("paper_batch.result_from_state", return_value=result))
                        stack.enter_context(patch("paper_automation.oa_recovery.run_limited_oa_recovery_on_batch", return_value=[]))
                        stack.enter_context(patch("paper_batch._handle_bridge_run", return_value=(None, 3)))
                        bridge = stack.enter_context(patch("paper_batch.run_zotero_bridge"))
                        args = ([command, "--text", "10.1000/example", "--out", str(root)]
                                if command == "start" else [command, "--run-dir", str(root)])
                        code = paper_batch.main(args + flags)
                        self.assertEqual(bridge.call_count, int(flags == ["--auto-zotero"]))
                        self.assertEqual(code, 3 if flags == ["--auto-zotero"] else 0)

    def test_enable_disable_flags_are_mutually_exclusive(self):
        import paper_batch
        for command in ("start", "retry-failed", "recover-oa"):
            args = [command, "--text", "10.1000/example"] if command == "start" else [command, "--run-dir", "fixture"]
            with self.subTest(command=command), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    paper_batch.build_parser().parse_args(args + ["--auto-zotero", "--no-auto-zotero"])

    def test_gui_passes_bridge_parameters_only_for_manual_zotero(self):
        from paper_scraper_ui import PaperScraperUI
        app = PaperScraperUI.__new__(PaperScraperUI)  # no window or settings writes
        for name, value in {
            "batch_action_var": "start", "batch_input_file_var": "papers.csv",
            "output_var": "results", "batch_run_name_var": "test",
            "batch_login_wait_var": "0", "batch_library_id_var": "7",
            "batch_wait_seconds_var": "30", "batch_run_dir_var": "existing",
        }.items():
            setattr(app, name, SimpleNamespace(get=lambda value=value: value))
        command = app._build_paper_batch_command()
        for flag in ("--auto-zotero", "--library-id", "--wait-seconds"):
            self.assertNotIn(flag, command)
        app.batch_action_var = SimpleNamespace(get=lambda: "zotero")
        command = app._build_paper_batch_command()
        self.assertEqual(command[command.index("--library-id") + 1], "7")
        self.assertEqual(command[command.index("--wait-seconds") + 1], "30")


if __name__ == "__main__":
    unittest.main()
