param(
    [string]$EvidencePath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Commit = "4971d363e665551ac4142f541e5f2d71f1cda653"
$SourceUrl = "https://codeload.github.com/ladislav-zezula/CascLib/tar.gz/4971d363e665551ac4142f541e5f2d71f1cda653"
$SourceSha256 = "6b40739449d12f9c55b0acca7c40cba591ac0bdd10f485d58fafcb164021021e"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$OutputDir = Join-Path $RepoRoot "third_party/CascLib/bin/win-x64"
$TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("gamexray-casclib-" + [Guid]::NewGuid().ToString("N"))
$ArchivePath = Join-Path $TempRoot "CascLib.tar.gz"
$SourceDir = Join-Path $TempRoot "CascLib-$Commit"
$BuildDir = Join-Path $TempRoot "build-vs2022-x64"
if (-not $EvidencePath) {
    $EvidencePath = Join-Path ([System.IO.Path]::GetTempPath()) ("gamexray-casclib-build-" + [Guid]::NewGuid().ToString("N") + ".json")
}
$EvidencePath = [System.IO.Path]::GetFullPath($EvidencePath)

# 优先用 PATH 上的 cmake；缺失时探测 Visual Studio 自带的 CMake
# （<版本>\<edition>\Common7\... 布局，VS2019/2022/18 通用），
# 使脚本无需 VS 开发者终端即可运行。
$CmakeLookup = Get-Command cmake -ErrorAction SilentlyContinue
$CmakeCommand = if ($null -ne $CmakeLookup) { $CmakeLookup.Source } else { $null }
if (-not $CmakeCommand) {
    $CmakeCandidates = @(
        Get-Item "C:\Program Files\Microsoft Visual Studio\*\*\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe" -ErrorAction SilentlyContinue
        Get-Item "C:\Program Files (x86)\Microsoft Visual Studio\*\*\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe" -ErrorAction SilentlyContinue
    )
    if ($CmakeCandidates.Count -gt 0) {
        $CmakeCommand = $CmakeCandidates[0].FullName
    }
}
if (-not $CmakeCommand) {
    throw "cmake not found: add CMake to PATH or install Visual Studio with the CMake component"
}

try {
    # Windows PowerShell 5.1 的 HttpWebRequest 默认不含 TLS 1.2，GitHub 会直接断连。
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    New-Item -ItemType Directory -Path $TempRoot | Out-Null
    # Windows PowerShell 的 WebRequest 在部分系统代理下会长时间卡住。
    # 优先使用系统 curl，并在未显式配置环境代理时继承 Windows 的代理选择。
    $CurlLookup = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($null -ne $CurlLookup) {
        $DownloadArgs = @("--silent", "--show-error", "--fail", "--location", "--connect-timeout", "30", "--max-time", "180")
        if (-not $env:HTTPS_PROXY -and -not $env:ALL_PROXY) {
            $DownloadUri = [System.Uri]$SourceUrl
            $SystemProxy = [System.Net.WebRequest]::DefaultWebProxy
            if ($null -ne $SystemProxy -and -not $SystemProxy.IsBypassed($DownloadUri)) {
                $ProxyUri = $SystemProxy.GetProxy($DownloadUri)
                $DownloadArgs += @("--proxy", $ProxyUri.AbsoluteUri)
            }
        }
        & $CurlLookup.Source @DownloadArgs --output $ArchivePath $SourceUrl
        if ($LASTEXITCODE -ne 0) { throw "Failed to download the pinned CascLib source archive" }
    }
    else {
        Invoke-WebRequest -Uri $SourceUrl -OutFile $ArchivePath -UseBasicParsing -TimeoutSec 180
    }

    $ActualSourceHash = (Get-FileHash -Algorithm SHA256 -Path $ArchivePath).Hash.ToLowerInvariant()
    if ($ActualSourceHash -ne $SourceSha256) {
        throw "CascLib source SHA256 mismatch: expected $SourceSha256, got $ActualSourceHash"
    }

    # 不用 "cmake -E chdir ... cmake ..." 嵌套形式：内层 cmake 在不依赖 PATH 时无法解析。
    Push-Location $TempRoot
    try {
        & $CmakeCommand -E tar xzf $ArchivePath
        if ($LASTEXITCODE -ne 0) { throw "Failed to extract CascLib source archive" }
    }
    finally {
        Pop-Location
    }

    # 不固定 -G：让 CMake 选本机最新的 Visual Studio 生成器（VS2022/VS18 均可），
    # -A x64 仍强制 64 位架构。
    & $CmakeCommand -S $SourceDir -B $BuildDir -A "x64" `
        "-DCMAKE_POLICY_VERSION_MINIMUM=3.5" `
        -DCASC_UNICODE=ON `
        -DCASC_BUILD_SHARED_LIB=ON `
        -DCASC_BUILD_STATIC_LIB=OFF `
        -DCASC_BUILD_TESTS=OFF
    if ($LASTEXITCODE -ne 0) { throw "CascLib CMake configure failed" }

    & $CmakeCommand --build $BuildDir --config Release --target casc
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

    # 保留本次本机构建的完整身份；不把临时源码目录的存在误称为出处证明。
    $CmakeVersion = (& $CmakeCommand --version | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { throw "Unable to record CMake version" }
    $CacheLines = Get-Content -LiteralPath (Join-Path $BuildDir "CMakeCache.txt")
    $Toolchain = [ordered]@{}
    foreach ($Line in $CacheLines) {
        if ($Line -match '^(CMAKE_(?:GENERATOR|GENERATOR_INSTANCE|GENERATOR_PLATFORM|GENERATOR_TOOLSET|C_COMPILER|CXX_COMPILER|VS_MSBUILD_COMMAND|VS_PLATFORM_TOOLSET|VS_WINDOWS_TARGET_PLATFORM_VERSION)):[^=]+=(.*)$') {
            $Toolchain[$Matches[1]] = $Matches[2]
        }
    }
    $Evidence = [ordered]@{
        schema_version = 1
        built_at_utc = [DateTime]::UtcNow.ToString("o")
        source_commit = $Commit
        source_url = $SourceUrl
        source_sha256 = $ActualSourceHash
        architecture = "x64"
        configuration = "Release"
        cmake_executable = $CmakeCommand
        cmake_version = $CmakeVersion
        toolchain = $Toolchain
        options = @("CASC_UNICODE=ON", "CASC_BUILD_SHARED_LIB=ON", "CASC_BUILD_STATIC_LIB=OFF", "CASC_BUILD_TESTS=OFF")
        dll_path = $OutputDll
        dll_size = (Get-Item -LiteralPath $OutputDll).Length
        dll_sha256 = $DllHash
    }
    $EvidenceParent = Split-Path -Parent $EvidencePath
    New-Item -ItemType Directory -Path $EvidenceParent -Force | Out-Null
    [System.IO.File]::WriteAllText($EvidencePath, ($Evidence | ConvertTo-Json -Depth 5), [System.Text.UTF8Encoding]::new($false))
    Write-Host "Built $OutputDll"
    Write-Host "SHA256 $DllHash"
    Write-Host "Build evidence $EvidencePath"
}
finally {
    if (Test-Path -LiteralPath $TempRoot) {
        $ResolvedTempRoot = (Resolve-Path -LiteralPath $TempRoot).Path
        $ResolvedTempParent = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd('\') + '\'
        if (-not $ResolvedTempRoot.StartsWith($ResolvedTempParent, [System.StringComparison]::OrdinalIgnoreCase) -or
            -not (Split-Path -Leaf $ResolvedTempRoot).StartsWith("gamexray-casclib-", [System.StringComparison]::Ordinal)) {
            throw "Refusing to remove an unexpected CascLib temporary root: $ResolvedTempRoot"
        }
        Remove-Item -LiteralPath $TempRoot -Recurse -Force
    }
}
