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
                "legal",
                "without institutional cookies",
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
            'call :copy_required "LICENSE" "%PACKAGE_DIR%\\"',
            'call :copy_optional "如何导出机构Cookie.md" "%PACKAGE_DIR%\\"',
            'call :copy_required "README.md" "%PACKAGE_DIR%\\"',
            'call :copy_required "README_zh.md" "%PACKAGE_DIR%\\"',
            'call :copy_required "MANUAL_QA.md" "%PACKAGE_DIR%\\"',
            'call :copy_required "install_codex_skills.ps1" "%PACKAGE_DIR%\\"',
            'call :copy_required "docs\\sciencedirect_skill_beginner_guide.md" "%PACKAGE_DIR%\\docs\\"',
            'call :robocopy_required "paper_automation" "%PACKAGE_DIR%\\paper_automation"',
            'call :robocopy_required "skills" "%PACKAGE_DIR%\\skills"',
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


if __name__ == "__main__":
    unittest.main()
