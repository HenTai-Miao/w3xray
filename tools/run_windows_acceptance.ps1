param(
    [Parameter(Mandatory = $true)]
    [string]$War3Dir,
    [string]$MapPath,
    [string]$CampaignPath,
    [string]$EvidenceDir
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
. (Join-Path $PSScriptRoot "windows_process.ps1")
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

$MapPath = (Resolve-Path -LiteralPath $MapPath).Path
$CampaignPath = (Resolve-Path -LiteralPath $CampaignPath).Path
$EvidenceDir = [System.IO.Path]::GetFullPath($EvidenceDir)
$env:W3XRAY_WAR3_DIR = (Resolve-Path -LiteralPath $War3Dir).Path

& powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "build_casclib.ps1")
if ($LASTEXITCODE -ne 0) { throw "build_casclib.ps1 failed" }

& uv sync --dev
if ($LASTEXITCODE -ne 0) { throw "uv sync failed" }

& uv run w3xray-quality
if ($LASTEXITCODE -ne 0) { throw "uv run w3xray-quality failed" }

& uv run w3xray-test
if ($LASTEXITCODE -ne 0) { throw "uv run w3xray-test failed" }

& uv run w3xray-dist
if ($LASTEXITCODE -ne 0) { throw "uv run w3xray-dist failed" }

$DistDir = Join-Path $RepoRoot "dist"
$OnedirEvidenceDir = Join-Path $EvidenceDir "windows-onedir"
$OnedirWorkingDirectory = $RepoRoot
$Onedir = @(Get-ChildItem -LiteralPath $DistDir -Directory)
if ($Onedir.Count -ne 1) {
    throw "Expected one onedir directory"
}
$OnedirExe = @(Get-ChildItem -LiteralPath $Onedir[0].FullName -Filter "*.exe" -File -Recurse)
if ($OnedirExe.Count -ne 1) {
    throw "Expected one onedir executable"
}
$OnedirExePath = (Resolve-Path -LiteralPath $OnedirExe[0].FullName).Path

if (Test-Path -LiteralPath $OnedirEvidenceDir) {
    Remove-Item -LiteralPath $OnedirEvidenceDir -Recurse -Force
}
New-Item -ItemType Directory -Path $OnedirEvidenceDir -Force | Out-Null
$OnedirReport = Join-Path $OnedirEvidenceDir "acceptance.json"
$OnedirAcceptanceArgs = @(
    "acceptance",
    "--map", $MapPath,
    "--campaign", $CampaignPath,
    "--output", $OnedirEvidenceDir,
    "--report", $OnedirReport,
    "--repeat", "5",
    "--require-windows",
    "--war3-dir", $env:W3XRAY_WAR3_DIR
)
$OnedirCommandLine = ConvertTo-WindowsCommandLine $OnedirAcceptanceArgs
$OnedirProcess = Start-Process `
    -FilePath $OnedirExePath `
    -ArgumentList $OnedirCommandLine `
    -WorkingDirectory $OnedirWorkingDirectory `
    -Wait `
    -PassThru
if ($OnedirProcess.ExitCode -ne 0) {
    throw "Onedir EXE acceptance failed with exit code $($OnedirProcess.ExitCode); report: $OnedirReport"
}
if (-not (Test-Path -LiteralPath $OnedirReport -PathType Leaf)) {
    throw "Onedir EXE acceptance did not write report: $OnedirReport"
}
$OnedirResult = Get-Content -LiteralPath $OnedirReport -Raw -Encoding UTF8 | ConvertFrom-Json
if ($OnedirResult.overall_status -ne "pass") {
    throw "Onedir EXE acceptance report did not pass: $OnedirReport"
}
$ReportedExecutable = [System.IO.Path]::GetFullPath([string]$OnedirResult.executable)
if (-not [StringComparer]::OrdinalIgnoreCase.Equals($ReportedExecutable, $OnedirExePath)) {
    throw "Onedir EXE acceptance report identifies a different executable: $ReportedExecutable"
}

& uv run w3xray-dist --onefile
if ($LASTEXITCODE -ne 0) { throw "uv run w3xray-dist --onefile failed" }

$OnefileEvidenceDir = Join-Path $EvidenceDir "windows-onefile"
$OnefileWorkingDirectory = $RepoRoot
$OnefileExe = @(Get-ChildItem -LiteralPath $DistDir -Filter "*.exe" -File)
if ($OnefileExe.Count -ne 1) {
    throw "Expected one direct executable"
}
$OnefileExePath = (Resolve-Path -LiteralPath $OnefileExe[0].FullName).Path

if (Test-Path -LiteralPath $OnefileEvidenceDir) {
    Remove-Item -LiteralPath $OnefileEvidenceDir -Recurse -Force
}
New-Item -ItemType Directory -Path $OnefileEvidenceDir -Force | Out-Null
$OnefileReport = Join-Path $OnefileEvidenceDir "acceptance.json"
$OnefileAcceptanceArgs = @(
    "acceptance",
    "--map", $MapPath,
    "--campaign", $CampaignPath,
    "--output", $OnefileEvidenceDir,
    "--report", $OnefileReport,
    "--repeat", "5",
    "--require-windows",
    "--war3-dir", $env:W3XRAY_WAR3_DIR
)
$OnefileCommandLine = ConvertTo-WindowsCommandLine $OnefileAcceptanceArgs
$OnefileProcess = Start-Process `
    -FilePath $OnefileExePath `
    -ArgumentList $OnefileCommandLine `
    -WorkingDirectory $OnefileWorkingDirectory `
    -Wait `
    -PassThru
if ($OnefileProcess.ExitCode -ne 0) {
    throw "Onefile EXE acceptance failed with exit code $($OnefileProcess.ExitCode); report: $OnefileReport"
}
if (-not (Test-Path -LiteralPath $OnefileReport -PathType Leaf)) {
    throw "Onefile EXE acceptance did not write report: $OnefileReport"
}
$OnefileResult = Get-Content -LiteralPath $OnefileReport -Raw -Encoding UTF8 | ConvertFrom-Json
if ($OnefileResult.overall_status -ne "pass") {
    throw "Onefile EXE acceptance report did not pass: $OnefileReport"
}
$ReportedExecutable = [System.IO.Path]::GetFullPath([string]$OnefileResult.executable)
if (-not [StringComparer]::OrdinalIgnoreCase.Equals($ReportedExecutable, $OnefileExePath)) {
    throw "Onefile EXE acceptance report identifies a different executable: $ReportedExecutable"
}

Write-Host "Windows acceptance passed"
Write-Host "Onedir evidence: $OnedirReport"
Write-Host "Onefile evidence: $OnefileReport"
