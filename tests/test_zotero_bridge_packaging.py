from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILDER = PROJECT_ROOT / "scripts" / "build" / "build_zotero_bridge_xpi.ps1"
PLUGIN_ROOT = PROJECT_ROOT / "zotero_bridge_plugin"


class ZoteroBridgePackagingTests(unittest.TestCase):
    def builder_text(self) -> str:
        self.assertTrue(BUILDER.is_file(), "missing scripts/build/build_zotero_bridge_xpi.ps1")
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

    def test_builder_rejects_reparse_points_before_creating_output(self) -> None:
        text = self.builder_text()

        for required in (
            "function Assert-NoReparsePointInPath",
            "[System.IO.FileAttributes]::ReparsePoint",
            "[System.IO.Directory]::GetParent",
            "Assert-NoReparsePointInPath -Path $pluginRootFull",
            "Assert-NoReparsePointInPath -Path $outputDirectoryFull",
            "Get-ChildItem -LiteralPath $pluginRootFull -Force -Recurse",
        ):
            self.assertIn(required, text)
        self.assertLess(
            text.index("Assert-NoReparsePointInPath -Path $outputDirectoryFull"),
            text.index("New-Item -ItemType Directory -Path $outputDirectoryFull"),
        )

    def test_reparse_guard_rejects_a_real_junction_without_building_xpi(self) -> None:
        if os.name != "nt":
            self.skipTest("Windows junction check")
        powershell = shutil.which("powershell.exe") or shutil.which("powershell")
        if not powershell:
            self.skipTest("PowerShell is required for the junction check")
        fixture_base = PROJECT_ROOT / ".codex-test-tmp"
        fixture_base.mkdir(exist_ok=True)
        root = Path(tempfile.mkdtemp(prefix="zotero-reparse-", dir=fixture_base))
        target = root / "target"
        link = root / "link"
        env = os.environ.copy()
        env["ZOTERO_BUILDER_TEST_SCRIPT"] = str(BUILDER)
        env["ZOTERO_BUILDER_TEST_ROOT"] = str(root)
        command = r'''
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $env:ZOTERO_BUILDER_TEST_SCRIPT,
    [ref]$tokens,
    [ref]$errors
)
if ($errors.Count -gt 0) { throw "builder_ast_invalid" }
$functionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Assert-NoReparsePointInPath"
}, $true)
if ($null -eq $functionAst) { throw "reparse_guard_missing" }
Invoke-Expression $functionAst.Extent.Text
$target = Join-Path $env:ZOTERO_BUILDER_TEST_ROOT "target"
$link = Join-Path $env:ZOTERO_BUILDER_TEST_ROOT "link"
try {
    New-Item -ItemType Directory -Path $target -Force | Out-Null
    try {
        New-Item -ItemType Junction -Path $link -Target $target | Out-Null
    } catch {
        Write-Output "JUNCTION_UNAVAILABLE"
        return
    }
    $rejected = $false
    try {
        Assert-NoReparsePointInPath -Path (Join-Path $link "child") -Label "Fixture path"
    } catch {
        if ($_.Exception.Message -like "Fixture path contains a junction or symbolic link:*") {
            $rejected = $true
        } else {
            throw
        }
    }
    if (-not $rejected) { throw "junction_was_not_rejected" }
    Write-Output "REPARSE_REJECT_OK"
} finally {
    if (Test-Path -LiteralPath $link) { Remove-Item -LiteralPath $link -Force }
    if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Force }
}
'''
        try:
            completed = subprocess.run(
                [powershell, "-NoProfile", "-Command", command],
                cwd=PROJECT_ROOT,
                env=env,
                capture_output=True,
                check=False,
                text=True,
                errors="replace",
            )
            output = f"{completed.stdout}\n{completed.stderr}"
            if "JUNCTION_UNAVAILABLE" in output:
                self.skipTest("This Windows environment cannot create a junction")
            self.assertEqual(completed.returncode, 0, output)
            self.assertIn("REPARSE_REJECT_OK", output)
            self.assertEqual(list(PROJECT_ROOT.rglob("*.xpi")), [])
        finally:
            if os.path.lexists(link):
                os.rmdir(link)
            if target.exists():
                os.rmdir(target)
            if root.exists():
                os.rmdir(root)

    def test_builder_refuses_source_output_before_creating_an_archive(self) -> None:
        powershell = shutil.which("powershell.exe") or shutil.which("powershell")
        if not powershell:
            self.skipTest("PowerShell is required for this Windows builder check")
        completed = subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(BUILDER),
                "-OutputDirectory",
                str(PLUGIN_ROOT),
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            check=False,
            text=True,
            errors="replace",
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "Refusing output directory inside plugin source",
            f"{completed.stdout}\n{completed.stderr}",
        )
        self.assertEqual(list(PROJECT_ROOT.rglob("*.xpi")), [])

    def test_builder_preserves_windows_volume_roots(self) -> None:
        text = self.builder_text()
        self.assertIn("[System.IO.Path]::GetPathRoot($fullPath)", text)
        self.assertIn("$fullPath.Equals($volumeRoot", text)
        self.assertNotIn("GetFullPath($expanded).TrimEnd", text)
        self.assertNotIn("[System.IO.Path]::GetRelativePath", text)

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
            '"*.collection.json"',
            '"*.cancelled.json"',
            '"*.result.json"',
            '"cookies*.json"',
            '".env"',
        ):
            self.assertIn(excluded, text)

    def test_builder_rejects_forbidden_names_at_every_nested_path_segment(self) -> None:
        text = self.builder_text()

        self.assertIn("function Test-ForbiddenArchivePath", text)
        self.assertIn("$segments", text)
        self.assertIn("if ($segment -like $pattern)", text)
        self.assertIn("Test-ForbiddenArchivePath -RelativePath $relative", text)
        self.assertIn("Test-ForbiddenArchivePath -RelativePath $entry", text)
        self.assertNotIn('$relative -like "*/$pattern"', text)
        self.assertNotIn('$entry -like "*/$pattern"', text)

    def test_builder_validates_archive_root_entries_and_moves_atomically(self) -> None:
        text = self.builder_text()
        for required in (
            "tar -a -c -f",
            "tar could not create the temporary XPI archive",
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
        self.assertNotIn("Compress-Archive", text)

    def test_force_replaces_an_existing_xpi_without_delete_then_move_gap(self) -> None:
        text = self.builder_text()
        self.assertIn("[System.IO.File]::Replace($temporaryXpi, $finalXpi, $null)", text)
        self.assertNotIn("Remove-Item -LiteralPath $finalXpi", text)

    def test_builder_is_not_called_by_start_install_or_existing_packaging_scripts(self) -> None:
        for relative in (
            "start_paper_scraper_ui.bat",
            "install_codex_skills.ps1",
            "scripts/build/make_windows_ui_package.bat",
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
            "scripts\\build\\build_zotero_bridge_xpi.ps1 -OutputDirectory .\\dist",
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
