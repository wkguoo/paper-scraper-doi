[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

function Resolve-FullPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    $expanded = [Environment]::ExpandEnvironmentVariables($Path)
    if ([System.IO.Path]::IsPathRooted($expanded)) {
        return [System.IO.Path]::GetFullPath($expanded).TrimEnd('\', '/')
    }
    return [System.IO.Path]::GetFullPath(
        (Join-Path (Get-Location).Path $expanded)
    ).TrimEnd('\', '/')
}

function Test-PathInside {
    param(
        [Parameter(Mandatory = $true)][string]$Candidate,
        [Parameter(Mandatory = $true)][string]$Parent
    )

    $comparison = [StringComparison]::OrdinalIgnoreCase
    $separator = [System.IO.Path]::DirectorySeparatorChar
    return $Candidate.Equals($Parent, $comparison) -or
        $Candidate.StartsWith("$Parent$separator", $comparison)
}

if (-not $PSScriptRoot) {
    throw "This builder must be run from a saved build_zotero_bridge_xpi.ps1 file."
}

$pluginRootFull = Resolve-FullPath (Join-Path $PSScriptRoot "zotero_bridge_plugin")
$outputDirectoryFull = Resolve-FullPath $OutputDirectory
if (Test-PathInside -Candidate $outputDirectoryFull -Parent $pluginRootFull) {
    throw "Refusing output directory inside plugin source: $outputDirectoryFull"
}

$AllowedRootFiles = @(
    "manifest.json",
    "bootstrap.js"
)
$AllowedDirectories = @(
    "content",
    "locale"
)
$ForbiddenArchivePatterns = @(
    "tests",
    "package.json",
    ".git",
    "*.log",
    "plugin-state.json",
    "*.progress.json",
    "cookies*.json",
    ".env"
)
$RequiredRootEntries = @(
    "manifest.json",
    "bootstrap.js"
)

foreach ($name in $AllowedRootFiles) {
    $source = Join-Path $pluginRootFull $name
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Missing required plugin source file: $source"
    }
}
foreach ($name in $AllowedDirectories) {
    $source = Join-Path $pluginRootFull $name
    if (-not (Test-Path -LiteralPath $source -PathType Container)) {
        throw "Missing required plugin source directory: $source"
    }
}

$manifestPath = Join-Path $pluginRootFull "manifest.json"
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$version = [string]$manifest.version
if ($version -notmatch '^\d+\.\d+\.\d+$') {
    throw "manifest.json contains an invalid semantic version: $version"
}

New-Item -ItemType Directory -Path $outputDirectoryFull -Force | Out-Null
$archiveName = "zotero-paper-download-bridge-$version.xpi"
$finalXpi = Join-Path $outputDirectoryFull $archiveName
$noOverwrite = -not $Force
if ((Test-Path -LiteralPath $finalXpi) -and $noOverwrite) {
    throw "Output already exists; pass -Force only if replacement is intended: $finalXpi"
}

$token = [Guid]::NewGuid().ToString("N")
$stagingRoot = Join-Path ([System.IO.Path]::GetTempPath()) "zotero-bridge-build-$token"
$staging = Join-Path $stagingRoot "stage"
$temporaryZip = Join-Path $outputDirectoryFull ".$archiveName.$token.tmp.zip"
$temporaryXpi = Join-Path $outputDirectoryFull ".$archiveName.$token.tmp.xpi"

try {
    New-Item -ItemType Directory -Path $staging -Force | Out-Null
    foreach ($name in $AllowedRootFiles) {
        Copy-Item -LiteralPath (Join-Path $pluginRootFull $name) -Destination $staging
    }
    foreach ($name in $AllowedDirectories) {
        Copy-Item -LiteralPath (Join-Path $pluginRootFull $name) -Destination $staging -Recurse
    }

    $stagedFiles = Get-ChildItem -LiteralPath $staging -File -Recurse
    foreach ($file in $stagedFiles) {
        $relative = [System.IO.Path]::GetRelativePath($staging, $file.FullName).Replace('\', '/')
        $allowed = $AllowedRootFiles -contains $relative
        if (-not $allowed) {
            $allowed = $AllowedDirectories | Where-Object {
                $relative.StartsWith("$_/", [StringComparison]::Ordinal)
            }
        }
        if (-not $allowed) {
            throw "Staging contains a path outside the explicit allowlist: $relative"
        }
        foreach ($pattern in $ForbiddenArchivePatterns) {
            if ($relative -like $pattern -or $relative -like "*/$pattern") {
                throw "Staging contains a forbidden path: $relative"
            }
        }
    }

    Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $temporaryZip -CompressionLevel Optimal
    Move-Item -LiteralPath $temporaryZip -Destination $temporaryXpi

    $archiveEntries = @(& tar -tf $temporaryXpi)
    if ($LASTEXITCODE -ne 0) {
        throw "tar could not list the temporary XPI archive."
    }
    $archiveEntries = $archiveEntries | ForEach-Object { $_.Replace('\', '/').TrimStart('./') }
    foreach ($required in $RequiredRootEntries) {
        if ($archiveEntries -notcontains $required) {
            throw "Temporary XPI is missing required root entry: $required"
        }
    }
    foreach ($entry in $archiveEntries) {
        foreach ($pattern in $ForbiddenArchivePatterns) {
            if ($entry -like $pattern -or $entry -like "$pattern/*" -or $entry -like "*/$pattern") {
                throw "Temporary XPI contains a forbidden entry: $entry"
            }
        }
    }

    if (Test-Path -LiteralPath $finalXpi) {
        if ($noOverwrite) {
            throw "Output appeared during build and will not be overwritten: $finalXpi"
        }
        Remove-Item -LiteralPath $finalXpi -Force
    }
    # The final Move-Item is a same-directory rename of a validated temporary XPI.
    Move-Item -LiteralPath $temporaryXpi -Destination $finalXpi
    Write-Host "Validated Zotero XPI created: $finalXpi"
}
finally {
    $systemTempFull = Resolve-FullPath ([System.IO.Path]::GetTempPath())
    $stagingRootFull = Resolve-FullPath $stagingRoot
    if (
        (Test-PathInside -Candidate $stagingRootFull -Parent $systemTempFull) -and
        -not $stagingRootFull.Equals($systemTempFull, [StringComparison]::OrdinalIgnoreCase) -and
        (Test-Path -LiteralPath $stagingRootFull)
    ) {
        Remove-Item -LiteralPath $stagingRootFull -Recurse -Force
    }
    foreach ($temporaryFile in @($temporaryZip, $temporaryXpi)) {
        if (Test-Path -LiteralPath $temporaryFile) {
            Remove-Item -LiteralPath $temporaryFile -Force
        }
    }
}
