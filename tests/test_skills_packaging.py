from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class SkillPackagingTests(unittest.TestCase):
    def test_default_discovery_has_tests_package(self) -> None:
        self.assertTrue((PROJECT_ROOT / "tests" / "__init__.py").exists())

    def test_skill_frontmatter_names_and_descriptions_are_explicit(self) -> None:
        expected = {
            "paper-download": [
                "ScienceDirect",
                "open-access",
                "institutional",
            ],
            "sciencedirect-doi-download": [
                "ScienceDirect",
                "institutional",
                "DOI",
            ],
            "legal-oa-paper-download": [
                "open-access",
                "download assistance",
                "without institutional cookies",
                "third-party",
            ],
        }

        for skill_name, required_terms in expected.items():
            with self.subTest(skill=skill_name):
                path = PROJECT_ROOT / "skills" / skill_name / "SKILL.md"
                text = path.read_text(encoding="utf-8")
                frontmatter = self._frontmatter(text)
                self.assertEqual(frontmatter.get("name"), skill_name)
                description = frontmatter.get("description", "")
                self.assertGreater(len(description), 80)
                for term in required_terms:
                    self.assertIn(term, description)

    def test_paper_download_skill_documents_batch_zotero_fallback_contract(self) -> None:
        text = (PROJECT_ROOT / "skills" / "paper-download" / "SKILL.md").read_text(
            encoding="utf-8"
        )

        for required in (
            "paper_batch.py start",
            "paper_batch.py resume",
            "paper_batch.py finalize",
            "manual_retry.csv",
            "zotero_fallback.csv",
            "zotero_results.csv",
            'library_search(entity:"libraries", mode:"list")',
            "library_import",
            "library_update",
            "Codex下载回退_YYYYMMDD_HHMMSS",
            "Zotero.Attachments.addAvailablePDF",
            "env.addUndoStep",
            "metadata_uncertain",
            "zotero_unavailable",
            "zotero_api_unavailable",
            "existing_pdf",
            "downloaded",
            "no_pdf",
            "codex-download-success",
            "codex-download-failed",
            "task_id,zotero_item_id,attachment_path,status,reason",
            "run exactly one retry",
            "absolute Windows path",
            "reparse point",
            "must not overwrite",
        ):
            with self.subTest(required=required):
                self.assertIn(required, text)

        self.assertRegex(
            text,
            r"(?s)paper_batch\.py start.*paper_batch\.py resume.*paper_batch\.py finalize",
        )
        for forbidden in ("Sci-Hub", "Anna's Archive", "LibGen"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, text)

    def test_paper_download_skill_stops_for_unavailable_zotero_write_confirmation(self) -> None:
        text = (PROJECT_ROOT / "skills" / "paper-download" / "SKILL.md").read_text(
            encoding="utf-8"
        )

        required = (
            "Zotero-readable does not imply Zotero writes can show a confirmation UI.",
            "collection_update(action:\"create\", name:\"Codex下载回退_YYYYMMDD_HHMMSS\", libraryID:<libraryID>)",
            "Zotero MCP confirmation UI is unavailable for this Codex turn.",
            "Start a new Codex turn from Zotero and try again.",
            "stop all remaining Zotero writes",
            "Do not use `zotero_script` to bypass normal collection, import, or tag confirmation.",
            "start one new turn from the Zotero Codex panel and say “继续该批次”",
            "Preserve the run directory, `zotero_fallback.csv`, and every result already written.",
            "restart at the library check and collection creation",
            "Do not rerun project downloads or execute a second `resume`.",
            "`zotero_script(mode:\"write\")` remains limited to the single batch `Zotero.Attachments.addAvailablePDF` action with `env.addUndoStep`.",
            "write `zotero_unavailable` rows and keep the batch recoverable",
        )
        normalized_text = re.sub(r"\s+", " ", text)
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(re.sub(r"\s+", " ", phrase), normalized_text)

    def test_paper_download_skill_has_unambiguous_zotero_forward_protocol(self) -> None:
        skill_text = (
            PROJECT_ROOT / "skills" / "paper-download" / "SKILL.md"
        ).read_text(encoding="utf-8")
        cli_text = (PROJECT_ROOT / "paper_batch.py").read_text(encoding="utf-8")

        required_skill_text = (
            'collection_update(action:"create", name:"Codex下载回退_YYYYMMDD_HHMMSS", '
            'libraryID:<libraryID>)',
            'library_update(kind:"collections", action:"add", assignments:'
            '[{itemId:<id>, targetCollectionId:<collectionId>}, ...], libraryID:<libraryID>)',
            'library_import(kind:"identifiers", identifiers:[...], '
            'targetCollectionId:<collectionId>, libraryID:<libraryID>)',
            'library_search(entity:"items", mode:"search", text:"<normalized DOI>", '
            'include:["metadata","attachments"], libraryID:<libraryID>)',
            'library_update(kind:"tags", action:"add", assignments:'
            '[{itemId:<id>, tags:["codex-download-success"]}, ...], libraryID:<libraryID>)',
            'library_update(kind:"tags", action:"add", assignments:'
            '[{itemId:<id>, tags:["codex-download-failed"]}, ...], libraryID:<libraryID>)',
            "Python `csv` semantics",
            "UTF-8-SIG",
            "at least one field is non-empty",
            "exact header",
            "current task IDs",
            "active personal library",
            "group library",
            "Unicode NFKC",
            "casefold",
            "Unicode whitespace, punctuation, or symbol",
            "zotero_results_retry_YYYYMMDD_HHMMSS.csv",
            "exclusive creation",
            "not_found",
            "no_attachment",
            "download_failed",
            "This protocol generates only",
            "批次未完成且可恢复",
        )
        for required in required_skill_text:
            with self.subTest(required=required):
                self.assertIn(required, skill_text)

        self.assertIn("批次未完成且可恢复", cli_text)

    def test_paper_download_skill_distinguishes_pending_and_result_csv_boundaries(self) -> None:
        skill_text = (
            PROJECT_ROOT / "skills" / "paper-download" / "SKILL.md"
        ).read_text(encoding="utf-8")

        for required in (
            "Pending CSV files may ignore completely blank records",
            "Zotero result files reject every physical blank record",
            "all-whitespace result data row",
            "Do not assume a fixed Zotero MCP return schema",
            "numeric `libraryID`",
            "numeric `collectionId`",
            "numeric `itemId`",
            "array position",
            "fail closed",
            "library failure becomes `zotero_unavailable`",
            "collection or item ID failure becomes `no_pdf` or `metadata_uncertain`",
            "Python standard-library `csv.writer`",
            "open mode `x`",
            '`newline=""`',
            '`encoding="utf-8-sig"`',
            "fully construct and validate all current task IDs before opening the file",
            "finalize revalidates PDF content and reparse-point safety",
        ):
            with self.subTest(required=required):
                self.assertIn(required, skill_text)

    def test_install_script_supports_dry_run_and_repo_root_env(self) -> None:
        text = (PROJECT_ROOT / "install_codex_skills.ps1").read_text(encoding="utf-8")

        self.assertIn("[switch]$DryRun", text)
        self.assertIn("PAPER_SCRAPER_DOI_ROOT", text)
        self.assertIn("CODEX_HOME", text)
        self.assertIn("PSCommandPath", text)
        self.assertIn("Copy-Item", text)
        self.assertIn("Dry run only", text)
        self.assertIn("Resolve-FullPath", text)
        self.assertIn("Test-PathOverlap", text)
        self.assertIn("Refusing to install because target skills root overlaps", text)

    def test_notice_and_license_document_public_origin(self) -> None:
        notice = (PROJECT_ROOT / "NOTICE").read_text(encoding="utf-8")
        license_text = (PROJECT_ROOT / "LICENSE").read_text(encoding="utf-8")
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("GAO-pooh/paper-scraper", notice)
        self.assertIn("based on and extends", notice)
        self.assertIn("Copyright (c) 2026 wkguoo (modifications)", notice)
        self.assertIn("Copyright (c) 2026 wkguoo (modifications)", license_text)
        self.assertIn("基于开源项目", readme)
        self.assertIn("修改并扩展", readme)
        self.assertIn("NOTICE", readme)
        self.assertIn("不提供任何数据库、学校或出版社访问权限", readme)

    def test_github_actions_windows_tests_workflow_exists(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "tests.yml"
        text = workflow.read_text(encoding="utf-8")

        self.assertIn("windows-latest", text)
        self.assertIn('python-version: "3.11"', text)
        self.assertIn("python -m pip install -r requirements.txt", text)
        self.assertIn("python -m compileall", text)
        self.assertIn("python -m unittest discover -s tests -v", text)

    def test_public_copy_avoids_high_risk_access_wording(self) -> None:
        scanned_paths = [
            PROJECT_ROOT / "README.md",
            PROJECT_ROOT / "WINDOWS_UI_README.md",
            PROJECT_ROOT / "MANUAL_QA.md",
            PROJECT_ROOT / "sd_scraper.py",
            PROJECT_ROOT / "sd_scraper_en.py",
            PROJECT_ROOT / "skills" / "paper-download" / "SKILL.md",
            PROJECT_ROOT / "skills" / "sciencedirect-doi-download" / "SKILL.md",
            PROJECT_ROOT / "skills" / "legal-oa-paper-download" / "SKILL.md",
            PROJECT_ROOT / "docs" / "sciencedirect_skill_beginner_guide.md",
        ]
        disallowed = [
            "bypass " + "Cloudflare",
            "绕过" + "反爬",
            "ste" + "alth",
            "_STE" + "ALTH",
            "不触发" + "机器人验证",
            "破解 " + "CAPTCHA",
            "Cloudflare " + "不拦截",
        ]

        for path in scanned_paths:
            text = path.read_text(encoding="utf-8")
            for phrase in disallowed:
                with self.subTest(path=path.relative_to(PROJECT_ROOT), phrase=phrase):
                    self.assertNotIn(phrase, text)

    def test_public_copy_uses_cautious_oa_wording(self) -> None:
        scanned_paths = [
            PROJECT_ROOT / "README.md",
            PROJECT_ROOT / "README_zh.md",
            PROJECT_ROOT / "WINDOWS_UI_README.md",
            PROJECT_ROOT / "NOTICE",
            PROJECT_ROOT / "paper_scraper_ui.py",
            PROJECT_ROOT / "paper_skill.py",
            PROJECT_ROOT / "skills" / "paper-download" / "SKILL.md",
            PROJECT_ROOT / "skills" / "legal-oa-paper-download" / "SKILL.md",
            PROJECT_ROOT / "docs" / "superpowers" / "plans" / "2026-06-17-paper-skill.md",
        ]
        disallowed = [
            "合法 " + "OA " + "下载",
            "公开" + "合法 " + "OA",
            "公开" + "合法" + "开放获取",
            "合法" + "开放获取",
            "only legal " + "open-access PDFs",
            "legal open-access " + "workflow",
            "legal " + "OA " + "PDF",
            "legal open-access " + "PDF",
            "legal open-access " + "downloads",
        ]

        for path in scanned_paths:
            text = path.read_text(encoding="utf-8")
            for phrase in disallowed:
                with self.subTest(path=path.relative_to(PROJECT_ROOT), phrase=phrase):
                    self.assertNotIn(phrase, text)

    def test_sciencedirect_skills_document_supplement_outputs(self) -> None:
        for skill_name in ("paper-download", "sciencedirect-doi-download"):
            with self.subTest(skill=skill_name):
                text = (PROJECT_ROOT / "skills" / skill_name / "SKILL.md").read_text(encoding="utf-8")
                self.assertIn("supplement_download_report.csv", text)
                self.assertIn("supplements\\", text)
                self.assertIn("--no-download-supplements", text)

    def test_sciencedirect_reference_files_exist_and_are_linked(self) -> None:
        references_dir = PROJECT_ROOT / "skills" / "sciencedirect-doi-download" / "references"
        expected_reference_files = {
            "beginner-workflow.md",
            "failure-reasons.md",
        }

        self.assertTrue(references_dir.is_dir())
        actual_reference_files = {path.name for path in references_dir.glob("*.md")}
        self.assertTrue(expected_reference_files.issubset(actual_reference_files))

        skill_text = (
            PROJECT_ROOT / "skills" / "sciencedirect-doi-download" / "SKILL.md"
        ).read_text(encoding="utf-8")
        for filename in expected_reference_files:
            with self.subTest(reference=filename):
                self.assertIn(f"references/{filename}", skill_text)

    def test_beginner_docs_preflight_before_download_not_dry_run(self) -> None:
        beginner_docs = [
            PROJECT_ROOT / "README.md",
            PROJECT_ROOT / "README_zh.md",
            PROJECT_ROOT / "docs" / "sciencedirect_skill_beginner_guide.md",
            PROJECT_ROOT / "skills" / "paper-download" / "SKILL.md",
            PROJECT_ROOT / "skills" / "sciencedirect-doi-download" / "SKILL.md",
            PROJECT_ROOT
            / "skills"
            / "sciencedirect-doi-download"
            / "references"
            / "beginner-workflow.md",
        ]
        blocked_first_pass_phrases = [
            "Use $sciencedirect-doi-download to dry-run this paper list",
            "Use $sciencedirect-doi-download to dry-run these paper recommendations",
            "第一次拿到 AI 推荐列表，先跑 `--dry-run`",
            "beginner_dry_run",
        ]

        for path in beginner_docs:
            with self.subTest(path=path.relative_to(PROJECT_ROOT)):
                text = path.read_text(encoding="utf-8")
                self.assertIn("--beginner --preflight", text)
                for phrase in blocked_first_pass_phrases:
                    self.assertNotIn(phrase, text)

    def test_windows_ui_package_script_rebuilds_clean_package_dir(self) -> None:
        text = self._package_script_text()

        self.assertIn('set "PACKAGE_DIR=dist\\paper-scraper-ui-windows"', text)
        self.assertIn('if exist "%PACKAGE_DIR%" (', text)
        self.assertIn('rmdir /S /Q "%PACKAGE_DIR%"', text)
        self.assertIn('mkdir "%PACKAGE_DIR%"', text)
        self.assertLess(
            text.index('rmdir /S /Q "%PACKAGE_DIR%"'),
            text.index('mkdir "%PACKAGE_DIR%"'),
        )

    def test_windows_ui_package_script_includes_expected_assets(self) -> None:
        text = self._package_script_text()

        expected_snippets = [
            'call :copy_required "sd_scraper_en.py" "%PACKAGE_DIR%\\"',
            'call :copy_required "sd_supplements.py" "%PACKAGE_DIR%\\"',
            'call :copy_required "student_handoff.py" "%PACKAGE_DIR%\\"',
            'call :copy_required "LICENSE" "%PACKAGE_DIR%\\"',
            'call :copy_required "NOTICE" "%PACKAGE_DIR%\\"',
            'call :copy_optional "如何导出机构Cookie.md" "%PACKAGE_DIR%\\"',
            'call :copy_required "README.md" "%PACKAGE_DIR%\\"',
            'call :copy_required "README_zh.md" "%PACKAGE_DIR%\\"',
            'call :copy_required "MANUAL_QA.md" "%PACKAGE_DIR%\\"',
            'call :copy_required "install_codex_skills.ps1" "%PACKAGE_DIR%\\"',
            'call :copy_required "docs\\sciencedirect_skill_beginner_guide.md" "%PACKAGE_DIR%\\docs\\"',
            'call :robocopy_required "paper_automation" "%PACKAGE_DIR%\\paper_automation"',
            'call :robocopy_required "skills" "%PACKAGE_DIR%\\skills"',
            'call :verify_required "%PACKAGE_DIR%\\skills\\sciencedirect-doi-download\\references"',
            (
                'call :verify_required "%PACKAGE_DIR%\\skills\\sciencedirect-doi-download'
                '\\references\\beginner-workflow.md"'
            ),
            (
                'call :verify_required "%PACKAGE_DIR%\\skills\\sciencedirect-doi-download'
                '\\references\\failure-reasons.md"'
            ),
        ]

        for snippet in expected_snippets:
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, text)
        self.assertIn("如何导出机构Cookie.md", text)
        self.assertNotIn("濡備綍瀵煎嚭鏈烘瀯Cookie.md", text)

    def test_windows_ui_package_script_excludes_internal_and_cache_artifacts(self) -> None:
        text = self._package_script_text()

        self.assertIn('/XD "__pycache__"', text)
        self.assertIn('/XF "*.pyc"', text)
        self.assertNotIn('xcopy /E /I /Y "docs"', text)
        self.assertNotIn('robocopy "docs"', text)
        self.assertNotIn("docs\\superpowers", text)

    def test_windows_ui_package_script_fails_on_incomplete_package(self) -> None:
        text = self._package_script_text()

        self.assertIn(":copy_required", text)
        self.assertIn(":copy_optional", text)
        self.assertIn(":robocopy_required", text)
        self.assertIn(":verify_required", text)
        self.assertIn('rmdir /S /Q "%PACKAGE_DIR%"', text)
        self.assertIn('if exist "%PACKAGE_DIR%" (', text)
        self.assertIn("|| exit /b 1", text)
        self.assertIn("if errorlevel 1", text)
        self.assertIn('set "ROBOCOPY_EXIT=%ERRORLEVEL%"', text)
        self.assertIn("if %ROBOCOPY_EXIT% GEQ 8", text)

    @staticmethod
    def _package_script_text() -> str:
        return (PROJECT_ROOT / "make_windows_ui_package.bat").read_text(encoding="utf-8")

    @staticmethod
    def _frontmatter(text: str) -> dict[str, str]:
        match = re.match(r"---\n(.*?)\n---", text, flags=re.S)
        if not match:
            return {}
        result: dict[str, str] = {}
        for line in match.group(1).splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            result[key.strip()] = value.strip()
        return result


class BrowserProfileSafetyTests(unittest.TestCase):
    def test_debug_profile_copy_allowlist_excludes_sensitive_browser_state(self) -> None:
        import sd_scraper

        copied_files = set(sd_scraper.BROWSER_PROFILE_COPY_FILES)
        copied_dirs = set(sd_scraper.BROWSER_PROFILE_COPY_DIRS)

        self.assertEqual(copied_files, {
            "Cookies",
            "Cookies-journal",
            "Preferences",
            "Secure Preferences",
        })
        self.assertEqual(copied_dirs, set())
        self.assertTrue(copied_files.isdisjoint({
            "History",
            "Visited Links",
            "Web Data",
            "Login Data",
        }))
        self.assertTrue(copied_dirs.isdisjoint({
            "Network",
            "Local Storage",
            "Session Storage",
            "IndexedDB",
            "SharedStorage",
            "WebStorage",
        }))

    def test_english_debug_profile_copy_allowlist_excludes_sensitive_browser_state(self) -> None:
        import sd_scraper_en

        copied_files = set(sd_scraper_en.BROWSER_PROFILE_COPY_FILES)
        copied_dirs = set(sd_scraper_en.BROWSER_PROFILE_COPY_DIRS)

        self.assertEqual(copied_files, {
            "Cookies",
            "Cookies-journal",
            "Preferences",
            "Secure Preferences",
        })
        self.assertEqual(copied_dirs, set())
        self.assertTrue(copied_files.isdisjoint({
            "History",
            "Visited Links",
            "Web Data",
            "Login Data",
        }))
        self.assertTrue(copied_dirs.isdisjoint({
            "Network",
            "Local Storage",
            "Session Storage",
            "IndexedDB",
            "SharedStorage",
            "WebStorage",
        }))

    def test_missing_curl_cffi_error_is_delayed_until_network_use(self) -> None:
        import sd_scraper
        import sd_scraper_en

        for module in (sd_scraper, sd_scraper_en):
            original = module.HAS_CURL_CFFI
            try:
                module.HAS_CURL_CFFI = False
                session = module._new_curl_session(impersonate="chrome124", allow_missing=True)
                with self.assertRaisesRegex(RuntimeError, "curl_cffi"):
                    session.get("https://example.com")
                with self.assertRaisesRegex(RuntimeError, "curl_cffi"):
                    module._new_curl_session(impersonate="chrome124")
            finally:
                module.HAS_CURL_CFFI = original


if __name__ == "__main__":
    unittest.main()
