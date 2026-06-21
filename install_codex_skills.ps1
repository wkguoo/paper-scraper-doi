[CmdletBinding()]
param(
    [string]$RepositoryRoot,
    [string]$SkillsRoot,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Resolve-RepositoryRoot {
    param([string]$Path)
    $resolved = (Resolve-Path -LiteralPath $Path).Path
    if (-not (Test-Path -LiteralPath (Join-Path $resolved "skills"))) {
        throw "Repository root does not contain a skills directory: $resolved"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $resolved "sd_institutional_skill.py"))) {
        throw "Repository root does not contain sd_institutional_skill.py: $resolved"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $resolved "paper_skill.py"))) {
        throw "Repository root does not contain paper_skill.py: $resolved"
    }
    return $resolved
}

function Resolve-CodexSkillsRoot {
    param([string]$ExplicitRoot)
    if ($ExplicitRoot) {
        return $ExplicitRoot
    }
    if ($env:CODEX_HOME) {
        return (Join-Path $env:CODEX_HOME "skills")
    }
    return (Join-Path $HOME ".codex\skills")
}

function Resolve-FullPath {
    param([string]$Path)
    $expanded = [Environment]::ExpandEnvironmentVariables($Path)
    if ([System.IO.Path]::IsPathRooted($expanded)) {
        return [System.IO.Path]::GetFullPath($expanded).TrimEnd('\', '/')
    }
    return [System.IO.Path]::GetFullPath((Join-Path (Get-Location).Path $expanded)).TrimEnd('\', '/')
}

function Test-PathOverlap {
    param(
        [string]$Left,
        [string]$Right
    )
    $comparison = [StringComparison]::OrdinalIgnoreCase
    return $Left.Equals($Right, $comparison) -or
        $Left.StartsWith("$Right\", $comparison) -or
        $Right.StartsWith("$Left\", $comparison)
}

if (-not $RepositoryRoot) {
    if ($PSScriptRoot) {
        $RepositoryRoot = $PSScriptRoot
    } elseif ($PSCommandPath) {
        $RepositoryRoot = Split-Path -Parent $PSCommandPath
    } else {
        $RepositoryRoot = (Get-Location).Path
    }
}

$repo = Resolve-RepositoryRoot -Path $RepositoryRoot
$targetRoot = Resolve-CodexSkillsRoot -ExplicitRoot $SkillsRoot
$sourceRoot = Join-Path $repo "skills"
$sourceRootFull = Resolve-FullPath $sourceRoot
$targetRootFull = Resolve-FullPath $targetRoot

if (Test-PathOverlap -Left $sourceRootFull -Right $targetRootFull) {
    throw "Refusing to install because target skills root overlaps repository skills source: source=$sourceRootFull target=$targetRootFull"
}

Write-Host "Repository: $repo"
Write-Host "Codex skills target: $targetRoot"

if (-not $DryRun) {
    New-Item -ItemType Directory -Force -Path $targetRoot | Out-Null
}

Get-ChildItem -LiteralPath $sourceRoot -Directory | ForEach-Object {
    $destination = Join-Path $targetRoot $_.Name
    Write-Host "Install skill: $($_.Name) -> $destination"
    if (-not $DryRun) {
        if (Test-Path -LiteralPath $destination) {
            Remove-Item -LiteralPath $destination -Recurse -Force
        }
        Copy-Item -LiteralPath $_.FullName -Destination $destination -Recurse -Force
    }
}

Write-Host "Set user environment variable PAPER_SCRAPER_DOI_ROOT=$repo"
if (-not $DryRun) {
    [Environment]::SetEnvironmentVariable("PAPER_SCRAPER_DOI_ROOT", $repo, "User")
}

if ($DryRun) {
    Write-Host "Dry run only; no files or environment variables were changed."
} else {
    Write-Host "Done. Restart Codex or the terminal if it does not see the updated user environment variable."
}
