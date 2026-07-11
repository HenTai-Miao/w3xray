param(
    [Parameter(Mandatory = $true)]
    [string]$War3Dir,
    [string]$MapPath,
    [string]$CampaignPath,
    [string]$EvidenceDir
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
if (-not $MapPath) {
    $MapPath = Join-Path $RepoRoot "tests/fixtures/maps/war3net-map-script-builder.w3x"
}
if (-not $CampaignPath) {
    $CampaignPath = Join-Path $RepoRoot "tests/fixtures/reference/stormlib-campaign.w3n"
}
if (-not $EvidenceDir) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $EvidenceDir = Join-Path ([System.IO.Path]::GetTempPath()) "w3xray-acceptance-$stamp"
}

if (-not (Test-Path -LiteralPath (Join-Path $War3Dir ".build.info") -PathType Leaf)) {
    throw "Warcraft III .build.info not found: $War3Dir"
}
if (-not (Test-Path -LiteralPath $MapPath -PathType Leaf)) {
    throw "Map fixture not found: $MapPath"
}
if (-not (Test-Path -LiteralPath $CampaignPath -PathType Leaf)) {
    throw "Campaign fixture not found: $CampaignPath"
}

$env:W3XRAY_WAR3_DIR = (Resolve-Path -LiteralPath $War3Dir).Path

& powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "build_casclib.ps1")
if ($LASTEXITCODE -ne 0) { throw "build_casclib.ps1 failed" }

& uv sync --dev
if ($LASTEXITCODE -ne 0) { throw "uv sync failed" }

& uv run w3xray-test
if ($LASTEXITCODE -ne 0) { throw "uv run w3xray-test failed" }

& uv run w3xray-dist
if ($LASTEXITCODE -ne 0) { throw "uv run w3xray-dist failed" }

$DistDir = Join-Path $RepoRoot "dist"
$OnedirEvidenceDir = Join-Path $EvidenceDir "windows-onedir"
$OnedirExe = @(Get-ChildItem -LiteralPath $DistDir -Filter "*.exe" -File -Recurse)
if ($OnedirExe.Count -ne 1) {
    throw "Expected one onedir executable"
}

New-Item -ItemType Directory -Path $OnedirEvidenceDir -Force | Out-Null
$OnedirReport = Join-Path $OnedirEvidenceDir "acceptance.json"
$OnedirAcceptanceArgs = @(
    "acceptance",
    "--map", $MapPath,
    "--campaign", $CampaignPath,
    "--output", $OnedirEvidenceDir,
    "--report", $OnedirReport,
    "--repeat", "10",
    "--require-windows",
    "--war3-dir", $env:W3XRAY_WAR3_DIR
)
& $OnedirExe[0].FullName @OnedirAcceptanceArgs
if ($LASTEXITCODE -ne 0) { throw "Onedir EXE acceptance failed; report: $OnedirReport" }

& uv run w3xray-dist --onefile
if ($LASTEXITCODE -ne 0) { throw "uv run w3xray-dist --onefile failed" }

$OnefileEvidenceDir = Join-Path $EvidenceDir "windows-onefile"
$OnefileExe = @(Get-ChildItem -LiteralPath $DistDir -Filter "*.exe" -File)
if ($OnefileExe.Count -ne 1) {
    throw "Expected one direct executable"
}

New-Item -ItemType Directory -Path $OnefileEvidenceDir -Force | Out-Null
$OnefileReport = Join-Path $OnefileEvidenceDir "acceptance.json"
$OnefileAcceptanceArgs = @(
    "acceptance",
    "--map", $MapPath,
    "--campaign", $CampaignPath,
    "--output", $OnefileEvidenceDir,
    "--report", $OnefileReport,
    "--repeat", "10",
    "--require-windows",
    "--war3-dir", $env:W3XRAY_WAR3_DIR
)
& $OnefileExe[0].FullName @OnefileAcceptanceArgs
if ($LASTEXITCODE -ne 0) { throw "Onefile EXE acceptance failed; report: $OnefileReport" }

Write-Host "Windows acceptance passed"
Write-Host "Onedir evidence: $OnedirReport"
Write-Host "Onefile evidence: $OnefileReport"
