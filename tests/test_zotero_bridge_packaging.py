from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILDER = PROJECT_ROOT / "build_zotero_bridge_xpi.ps1"
PLUGIN_ROOT = PROJECT_ROOT / "zotero_bridge_plugin"


class ZoteroBridgePackagingTests(unittest.TestCase):
    def builder_text(self) -> str:
        self.assertTrue(BUILDER.is_file(), "missing build_zotero_bridge_xpi.ps1")
        return BUILDER.read_text(encoding="utf-8")

    def test_builder_is_explicit_and_parameterized(self) -> None:
        text = self.builder_text()
        self.assertIn("[CmdletBinding()]", text)
        self.assertIn("[string]$OutputDirectory", text)
        self.assertIn("[switch]$Force", text)
        self.assertIn("ConvertFrom-Json", text)
        self.assertNotIn("make_windows_ui_package.bat", text)

    def test_builder_rejects_output_inside_plugin_source(self) -> None:
        text = self.builder_text()
        for required in (
            "Test-PathInside",
            "$pluginRootFull",
            "$outputDirectoryFull",
            "Refusing output directory inside plugin source",
        ):
            self.assertIn(required, text)

    def test_builder_uses_only_an_explicit_plugin_source_allowlist(self) -> None:
        text = self.builder_text()
        for required in (
            "$AllowedRootFiles",
            '"manifest.json"',
            '"bootstrap.js"',
            "$AllowedDirectories",
            '"content"',
            '"locale"',
        ):
            self.assertIn(required, text)
        for excluded in (
            '"tests"',
            '"package.json"',
            '".git"',
            '"*.log"',
            '"plugin-state.json"',
            '"*.progress.json"',
            '"cookies*.json"',
            '".env"',
        ):
            self.assertIn(excluded, text)

    def test_builder_validates_archive_root_entries_and_moves_atomically(self) -> None:
        text = self.builder_text()
        for required in (
            "Compress-Archive",
            "tar -tf",
            "$RequiredRootEntries",
            '"manifest.json"',
            '"bootstrap.js"',
            "$temporaryXpi",
            "$finalXpi",
            "Move-Item",
            "noOverwrite",
        ):
            self.assertIn(required, text)

    def test_builder_is_not_called_by_start_install_or_existing_packaging_scripts(self) -> None:
        for relative in (
            "start_paper_scraper_ui.bat",
            "install_codex_skills.ps1",
            "make_windows_ui_package.bat",
        ):
            with self.subTest(path=relative):
                text = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
                self.assertNotIn("build_zotero_bridge_xpi", text)

    def test_beginner_readme_marks_build_as_manual_and_approval_gated(self) -> None:
        path = PLUGIN_ROOT / "README.md"
        self.assertTrue(path.is_file(), "missing zotero_bridge_plugin/README.md")
        text = path.read_text(encoding="utf-8")
        for required in (
            "node --test .\\zotero_bridge_plugin\\tests\\*.test.cjs",
            "build_zotero_bridge_xpi.ps1 -OutputDirectory .\\dist",
            "需明确批准",
            "本次不会执行",
            "不会自动安装",
            "Zotero 9.0.x",
        ):
            self.assertIn(required, text)

    def test_repository_contains_no_built_xpi(self) -> None:
        self.assertEqual(list(PROJECT_ROOT.rglob("*.xpi")), [])


if __name__ == "__main__":
    unittest.main()
