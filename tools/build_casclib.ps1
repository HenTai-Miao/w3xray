$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Commit = "4971d363e665551ac4142f541e5f2d71f1cda653"
$SourceUrl = "https://codeload.github.com/ladislav-zezula/CascLib/tar.gz/4971d363e665551ac4142f541e5f2d71f1cda653"
$SourceSha256 = "6b40739449d12f9c55b0acca7c40cba591ac0bdd10f485d58fafcb164021021e"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$OutputDir = Join-Path $RepoRoot "third_party/CascLib/bin/win-x64"
$TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("w3xray-casclib-" + [Guid]::NewGuid().ToString("N"))
$ArchivePath = Join-Path $TempRoot "CascLib.tar.gz"
$SourceDir = Join-Path $TempRoot "CascLib-$Commit"
$BuildDir = Join-Path $TempRoot "build-vs2022-x64"

try {
    New-Item -ItemType Directory -Path $TempRoot | Out-Null
    Invoke-WebRequest -Uri $SourceUrl -OutFile $ArchivePath -UseBasicParsing

    $ActualSourceHash = (Get-FileHash -Algorithm SHA256 -Path $ArchivePath).Hash.ToLowerInvariant()
    if ($ActualSourceHash -ne $SourceSha256) {
        throw "CascLib source SHA256 mismatch: expected $SourceSha256, got $ActualSourceHash"
    }

    & cmake -E chdir $TempRoot cmake -E tar xzf $ArchivePath
    if ($LASTEXITCODE -ne 0) { throw "Failed to extract CascLib source archive" }

    & cmake -S $SourceDir -B $BuildDir -G "Visual Studio 17 2022" -A "x64" `
        -DCMAKE_POLICY_VERSION_MINIMUM=3.5 `
        -DCASC_UNICODE=ON `
        -DCASC_BUILD_SHARED_LIB=ON `
        -DCASC_BUILD_STATIC_LIB=OFF `
        -DCASC_BUILD_TESTS=OFF
    if ($LASTEXITCODE -ne 0) { throw "CascLib CMake configure failed" }

    & cmake --build $BuildDir --config Release --target casc
    if ($LASTEXITCODE -ne 0) { throw "CascLib Release build failed" }

    $BuiltDll = Join-Path $BuildDir "Release/CascLib.dll"
    if (-not (Test-Path -LiteralPath $BuiltDll -PathType Leaf)) {
        throw "CascLib.dll was not produced at $BuiltDll"
    }

    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
    $OutputDll = Join-Path $OutputDir "CascLib.dll"
    Copy-Item -LiteralPath $BuiltDll -Destination $OutputDll -Force
    $DllHash = (Get-FileHash -Algorithm SHA256 -Path $OutputDll).Hash.ToLowerInvariant()
    Set-Content -LiteralPath (Join-Path $OutputDir "CascLib.dll.sha256") `
        -Value $DllHash -Encoding ascii -NoNewline
    Write-Host "Built $OutputDll"
    Write-Host "SHA256 $DllHash"
}
finally {
    if (Test-Path -LiteralPath $TempRoot) {
        Remove-Item -LiteralPath $TempRoot -Recurse -Force
    }
}
