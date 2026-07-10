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

$Exe = Join-Path $RepoRoot "dist/魔兽地图提取器/魔兽地图提取器.exe"
if (-not (Test-Path -LiteralPath $Exe -PathType Leaf)) {
    throw "Packaged executable not found: $Exe"
}

New-Item -ItemType Directory -Path $EvidenceDir -Force | Out-Null
$Report = Join-Path $EvidenceDir "acceptance.json"
$AcceptanceArgs = @(
    "acceptance",
    "--map", $MapPath,
    "--campaign", $CampaignPath,
    "--output", $EvidenceDir,
    "--report", $Report,
    "--repeat", "10",
    "--require-windows",
    "--war3-dir", $env:W3XRAY_WAR3_DIR
)
& $Exe @AcceptanceArgs
if ($LASTEXITCODE -ne 0) { throw "Packaged EXE acceptance failed; report: $Report" }

Write-Host "Windows acceptance passed"
Write-Host "Evidence: $Report"
