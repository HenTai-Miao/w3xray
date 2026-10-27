param(
    [Parameter(Mandatory = $true)]
    [string]$OutputRoot,
    [string]$NativeBuildEvidence,
    [string]$War3Dir,
    [ValidateRange(1, 2147483647)]
    [int]$Repeat = 5,
    [switch]$Onefile
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw "This release script requires Windows."
}
if (-not [System.IO.Path]::IsPathRooted($OutputRoot)) {
    throw "OutputRoot must be an explicit absolute path outside the repository."
}
$RepoRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
$Python = Join-Path $RepoRoot ".venv/Scripts/python.exe"
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "The project Python environment is missing. Run uv sync --locked --dev first."
}
. (Join-Path $PSScriptRoot "windows_process.ps1")

# Resolve physical aliases before allowing any output writes. JSON stays ASCII
# so Windows PowerShell 5.1 does not depend on its legacy console encoding.
$IdentityCode = "import json, pathlib, sys; from gametool import __version__; from gametool.dist_build import APP_NAME; print(json.dumps({'repo': str(pathlib.Path(sys.argv[1]).resolve()), 'output': str(pathlib.Path(sys.argv[2]).resolve()), 'version': __version__, 'app_name': APP_NAME, 'python': sys.version.split()[0]}))"
$IdentityText = & $Python -X utf8 -c $IdentityCode $RepoRoot $OutputRoot
if ($LASTEXITCODE -ne 0) { throw "Unable to resolve release paths and metadata." }
$Identity = $IdentityText | ConvertFrom-Json
$RepoRoot = [string]$Identity.repo
$OutputRoot = [string]$Identity.output
$RepoPrefix = $RepoRoot.TrimEnd('\') + '\'
if ([StringComparer]::OrdinalIgnoreCase.Equals($OutputRoot, $RepoRoot) -or
    $OutputRoot.StartsWith($RepoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputRoot must be outside the repository."
}
if (Test-Path -LiteralPath $OutputRoot) {
    $ExistingRoot = Get-Item -LiteralPath $OutputRoot -Force
    if (-not $ExistingRoot.PSIsContainer -or
        ($ExistingRoot.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -or
        @(Get-ChildItem -LiteralPath $OutputRoot -Force).Count -ne 0) {
        throw "OutputRoot must be a new or empty ordinary directory; existing files are preserved."
    }
}
else {
    New-Item -ItemType Directory -Path $OutputRoot | Out-Null
}

$LogsRoot = Join-Path $OutputRoot "logs"
$PrivateCache = Join-Path $OutputRoot "runtime-cache"
New-Item -ItemType Directory -Path $LogsRoot, $PrivateCache | Out-Null

function Invoke-ReleaseProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][AllowEmptyString()][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Name,
        [string]$WorkingDirectory = $RepoRoot
    )
    $StdoutPath = Join-Path $LogsRoot ($Name + ".stdout.txt")
    $StderrPath = Join-Path $LogsRoot ($Name + ".stderr.txt")
    $StartInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $StartInfo.FileName = $FilePath
    $StartInfo.Arguments = ConvertTo-WindowsCommandLine -ArgumentList $Arguments
    $StartInfo.WorkingDirectory = $WorkingDirectory
    $StartInfo.UseShellExecute = $false
    $StartInfo.CreateNoWindow = $true
    $StartInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    $StartInfo.RedirectStandardOutput = $true
    $StartInfo.RedirectStandardError = $true
    $StartInfo.StandardOutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $StartInfo.StandardErrorEncoding = [System.Text.UTF8Encoding]::new($false)
    $StartInfo.EnvironmentVariables["GAMEXRAY_CACHE_DIR"] = $PrivateCache
    $StartInfo.EnvironmentVariables["GAMEXRAY_GUI_CONFIG_PATH"] = Join-Path $PrivateCache "gui-config.json"
    $StartInfo.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8"
    $StartInfo.EnvironmentVariables["PYTHONUTF8"] = "1"
    if ($War3Dir) {
        $StartInfo.EnvironmentVariables["GAMEXRAY_WAR3_DIR"] = (Resolve-Path -LiteralPath $War3Dir).Path
    }
    else { $StartInfo.EnvironmentVariables.Remove("GAMEXRAY_WAR3_DIR") }
    $Process = [System.Diagnostics.Process]::new()
    $Process.StartInfo = $StartInfo
    $Started = $false
    Write-Host "Running $Name; logs: $LogsRoot"
    try {
        if (-not $Process.Start()) { throw "Unable to start $Name" }
        $Started = $true
        # Drain both streams concurrently so verbose compiler/GUI diagnostics
        # cannot deadlock the process on a full pipe.
        $StdoutTask = $Process.StandardOutput.ReadToEndAsync()
        $StderrTask = $Process.StandardError.ReadToEndAsync()
        $Process.WaitForExit()
        $Stdout = $StdoutTask.GetAwaiter().GetResult()
        $Stderr = $StderrTask.GetAwaiter().GetResult()
        $ExitCode = $Process.ExitCode
    }
    finally {
        if ($Started -and -not $Process.HasExited) {
            # Reap only this held child and its descendants when interrupted.
            $StopInfo = [System.Diagnostics.ProcessStartInfo]::new()
            $StopInfo.FileName = "taskkill.exe"
            $StopInfo.Arguments = "/PID $($Process.Id) /T /F"
            $StopInfo.UseShellExecute = $false
            $StopInfo.CreateNoWindow = $true
            $StopInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
            $StopProcess = [System.Diagnostics.Process]::Start($StopInfo)
            $StopProcess.WaitForExit()
            $StopProcess.Dispose()
        }
        $Process.Dispose()
    }
    [System.IO.File]::WriteAllText($StdoutPath, $Stdout, [System.Text.UTF8Encoding]::new($false))
    [System.IO.File]::WriteAllText($StderrPath, $Stderr, [System.Text.UTF8Encoding]::new($false))
    return [pscustomobject]@{
        ExitCode = $ExitCode
        Stdout = $Stdout
        Stderr = $Stderr
        StdoutPath = $StdoutPath
        StderrPath = $StderrPath
    }
}

function Require-ReleaseSuccess {
    param($Result, [string]$Name)
    if ($Result.ExitCode -ne 0) {
        throw "$Name failed with exit code $($Result.ExitCode). See $($Result.StdoutPath) and $($Result.StderrPath)"
    }
}

function Get-ReleaseSourceSnapshot {
    param([string]$Name)
    $Listing = Invoke-ReleaseProcess -FilePath "git.exe" -Arguments @("-C", $RepoRoot, "ls-files", "--cached", "--others", "--exclude-standard", "-z") -Name $Name
    Require-ReleaseSuccess $Listing "Source inventory"
    [string[]]$Paths = $Listing.Stdout.Split([char[]]@([char]0), [StringSplitOptions]::RemoveEmptyEntries)
    [Array]::Sort($Paths, [StringComparer]::Ordinal)
    $Entries = [System.Collections.Generic.List[object]]::new()
    $Canonical = [System.Text.StringBuilder]::new()
    foreach ($Relative in $Paths) {
        $Path = Join-Path $RepoRoot $Relative
        $Item = Get-Item -LiteralPath $Path -Force
        if ($Item.PSIsContainer -or ($Item.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
            throw "Source snapshot requires ordinary files: $Relative"
        }
        $Hash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
        $Entries.Add([ordered]@{ path = $Relative; bytes = $Item.Length; sha256 = $Hash })
        [void]$Canonical.Append($Relative).Append([char]0).Append($Hash).Append([char]0).Append($Item.Length).Append("`n")
    }
    $Hasher = [System.Security.Cryptography.SHA256]::Create()
    try {
        $Digest = $Hasher.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($Canonical.ToString()))
        $TreeHash = ([BitConverter]::ToString($Digest)).Replace("-", "").ToLowerInvariant()
    }
    finally { $Hasher.Dispose() }
    return [pscustomobject]@{ sha256 = $TreeHash; files = $Entries.ToArray() }
}

function Write-ReleaseJson {
    param([string]$Path, $Value)
    [System.IO.File]::WriteAllText($Path, ($Value | ConvertTo-Json -Depth 12), [System.Text.UTF8Encoding]::new($false))
}

function Write-ReleaseZip {
    param(
        [Parameter(Mandatory = $true)][string]$SourceDirectory,
        [Parameter(Mandatory = $true)][string]$RootName,
        [Parameter(Mandatory = $true)][string]$ArchivePath
    )
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $SourcePrefix = [System.IO.Path]::GetFullPath($SourceDirectory).TrimEnd('\') + '\'
    $SourceFiles = @(Get-ChildItem -LiteralPath $SourceDirectory -Recurse -File -Force)
    # .NET Framework's CreateFromDirectory writes Windows backslashes into ZIP
    # names. Create every entry explicitly with the ZIP-standard '/' separator.
    $ArchiveStream = [System.IO.File]::Open($ArchivePath, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
    try {
        $Archive = [System.IO.Compression.ZipArchive]::new($ArchiveStream, [System.IO.Compression.ZipArchiveMode]::Create, $false, [System.Text.Encoding]::UTF8)
        try {
            foreach ($SourceFile in $SourceFiles) {
                $Relative = $SourceFile.FullName.Substring($SourcePrefix.Length).Replace('\', '/')
                $Entry = $Archive.CreateEntry($RootName + '/' + $Relative, [System.IO.Compression.CompressionLevel]::Optimal)
                if ($SourceFile.LastWriteTime.Year -ge 1980 -and $SourceFile.LastWriteTime.Year -le 2107) {
                    $Entry.LastWriteTime = [DateTimeOffset]$SourceFile.LastWriteTime
                }
                $InputStream = [System.IO.File]::OpenRead($SourceFile.FullName)
                try {
                    $EntryStream = $Entry.Open()
                    try { $InputStream.CopyTo($EntryStream) }
                    finally { $EntryStream.Dispose() }
                }
                finally { $InputStream.Dispose() }
            }
            foreach ($Directory in @(Get-ChildItem -LiteralPath $SourceDirectory -Recurse -Directory -Force)) {
                if (@(Get-ChildItem -LiteralPath $Directory.FullName -Force).Count -eq 0) {
                    $Relative = $Directory.FullName.Substring($SourcePrefix.Length).Replace('\', '/')
                    [void]$Archive.CreateEntry($RootName + '/' + $Relative + '/')
                }
            }
        }
        finally { $Archive.Dispose() }
    }
    finally { $ArchiveStream.Dispose() }
    # Verify every archive file, including hidden assets; no file-count cap and
    # no extraction into a directory that could already contain user files.
    $Archive = [System.IO.Compression.ZipFile]::OpenRead($ArchivePath)
    try {
        $ArchiveFiles = @($Archive.Entries | Where-Object { -not $_.FullName.EndsWith('/') })
        if ($SourceFiles.Count -ne $ArchiveFiles.Count) { throw "ZIP file coverage differs from the built application." }
        $ArchiveNames = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
        foreach ($Entry in $ArchiveFiles) {
            if (-not $ArchiveNames.Add($Entry.FullName)) { throw "ZIP contains a duplicate file entry." }
            $Prefix = $RootName + '/'
            if (-not $Entry.FullName.StartsWith($Prefix, [StringComparison]::Ordinal) -or $Entry.FullName.Contains('\')) { throw "ZIP entry has an unexpected root or separator." }
            $Relative = $Entry.FullName.Substring($Prefix.Length)
            $SourcePath = Join-Path $SourceDirectory $Relative
            $Stream = $Entry.Open()
            $SourceStream = [System.IO.File]::OpenRead($SourcePath)
            $Hasher = [System.Security.Cryptography.SHA256]::Create()
            try {
                $EntryHash = ([BitConverter]::ToString($Hasher.ComputeHash($Stream))).Replace("-", "").ToLowerInvariant()
                $SourceHash = ([BitConverter]::ToString($Hasher.ComputeHash($SourceStream))).Replace("-", "").ToLowerInvariant()
            }
            finally { $Stream.Dispose(); $SourceStream.Dispose(); $Hasher.Dispose() }
            if ($EntryHash -ne $SourceHash) { throw "ZIP payload differs from the built file: $Relative" }
        }
    }
    finally { $Archive.Dispose() }
}

$CommitRun = Invoke-ReleaseProcess -FilePath "git.exe" -Arguments @("-C", $RepoRoot, "rev-parse", "HEAD") -Name "source-commit"
Require-ReleaseSuccess $CommitRun "Source commit"
$SourceCommit = $CommitRun.Stdout.Trim()
$DirtyRun = Invoke-ReleaseProcess -FilePath "git.exe" -Arguments @("-C", $RepoRoot, "status", "--porcelain=v1", "-z") -Name "source-status"
Require-ReleaseSuccess $DirtyRun "Source status"
$WorkingTreeDirty = $DirtyRun.Stdout.Length -gt 0
$SourceBefore = Get-ReleaseSourceSnapshot "source-before-files"
Write-ReleaseJson (Join-Path $OutputRoot "source-tree.json") ([ordered]@{
    schema_version = 1
    source_commit = $SourceCommit
    working_tree_dirty = $WorkingTreeDirty
    source_sha256 = $SourceBefore.sha256
    hash_format = "UTF-8: ordinal path + NUL + lowercase sha256 + NUL + decimal bytes + LF"
    files = $SourceBefore.files
})

$NativeEvidencePath = Join-Path $OutputRoot "native-build.json"
if ($NativeBuildEvidence) {
    Copy-Item -LiteralPath (Resolve-Path -LiteralPath $NativeBuildEvidence).Path -Destination $NativeEvidencePath
}
else {
    $NativeBuild = Invoke-ReleaseProcess -FilePath "powershell.exe" -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $PSScriptRoot "build_casclib.ps1"), "-EvidencePath", $NativeEvidencePath) -Name "native-build"
    Require-ReleaseSuccess $NativeBuild "Pinned CascLib build"
}
$Native = Get-Content -LiteralPath $NativeEvidencePath -Raw -Encoding UTF8 | ConvertFrom-Json
$Pinned = Get-Content -LiteralPath (Join-Path $RepoRoot "third_party/CascLib/SOURCE_PROVENANCE.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$DllPath = Join-Path $RepoRoot "third_party/CascLib/bin/win-x64/CascLib.dll"
$DllHash = (Get-FileHash -LiteralPath $DllPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($Native.schema_version -ne 1 -or $Native.source_commit -ne $Pinned.commit -or
    $Native.source_sha256 -ne $Pinned.source_sha256 -or $Native.architecture -ne "x64" -or
    $Native.source_url -ne $Pinned.url -or $Native.configuration -ne "Release" -or
    $Native.dll_sha256 -ne $DllHash -or $Native.dll_size -ne (Get-Item -LiteralPath $DllPath).Length) {
    throw "Native build evidence does not bind the current pinned CascLib DLL. Rebuild it from source."
}
$NativeGate = Invoke-ReleaseProcess -FilePath $Python -Arguments @("-X", "utf8", "-c", "from pathlib import Path; from gametool.casclib_dist import validate_casclib_dist_assets; validate_casclib_dist_assets(Path.cwd(), system='Windows')") -Name "native-asset-gate"
Require-ReleaseSuccess $NativeGate "Native hash and x64 PE gate"

$DistRoot = Join-Path $OutputRoot "dist"
$WorkRoot = Join-Path $OutputRoot "build"
$BuildArgs = @("-X", "utf8", "-m", "gametool.dist_build", "--distpath", $DistRoot, "--workpath", $WorkRoot)
if ($Onefile) { $BuildArgs += "--onefile" }
$BuildRun = Invoke-ReleaseProcess -FilePath $Python -Arguments $BuildArgs -Name "pyinstaller-build"
Require-ReleaseSuccess $BuildRun "PyInstaller build"
$AppName = [string]$Identity.app_name
$AppDirectory = Join-Path $DistRoot $AppName
$Executable = if ($Onefile) { Join-Path $DistRoot ($AppName + ".exe") } else { Join-Path $AppDirectory ($AppName + ".exe") }
if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) { throw "New executable was not produced: $Executable" }
$VersionRun = Invoke-ReleaseProcess -FilePath $Executable -Arguments @("--version") -Name "executable-version" -WorkingDirectory $OutputRoot
Require-ReleaseSuccess $VersionRun "Executable version"
if ($VersionRun.Stdout.Trim() -ne ("GameXRay " + $Identity.version)) {
    throw "The new executable does not expose the expected version on stdout."
}
$HelpRun = Invoke-ReleaseProcess -FilePath $Executable -Arguments @("--help") -Name "executable-help" -WorkingDirectory $OutputRoot
Require-ReleaseSuccess $HelpRun "Executable help"
foreach ($Command in @("cli", "pack-query", "guide", "live", "live-report", "reference", "current", "batch", "casc", "save", "savecodes", "wgc", "gameconfig", "acceptance")) {
    if (-not $HelpRun.Stdout.Contains($Command)) { throw "Executable help is incomplete: $Command" }
}
$UnknownRun = Invoke-ReleaseProcess -FilePath $Executable -Arguments @("--hlep") -Name "executable-unknown-option" -WorkingDirectory $OutputRoot
if ($UnknownRun.ExitCode -ne 2 -or -not $UnknownRun.Stderr.Contains("--help")) { throw "Unknown executable options must fail visibly with code 2." }

$AcceptanceRoot = Join-Path $OutputRoot "acceptance"
$ReportPath = Join-Path $AcceptanceRoot "acceptance.json"
$AcceptanceArgs = @("acceptance", "--map", (Join-Path $RepoRoot "tests/fixtures/maps/war3net-map-script-builder.w3x"), "--campaign", (Join-Path $RepoRoot "tests/fixtures/reference/stormlib-campaign.w3n"), "--output", $AcceptanceRoot, "--report", $ReportPath, "--repeat", [string]$Repeat, "--require-windows")
if ($War3Dir) { $AcceptanceArgs += @("--war3-dir", (Resolve-Path -LiteralPath $War3Dir).Path) }
$AcceptanceRun = Invoke-ReleaseProcess -FilePath $Executable -Arguments $AcceptanceArgs -Name "executable-acceptance" -WorkingDirectory $OutputRoot
Require-ReleaseSuccess $AcceptanceRun "Packaged acceptance"
$Report = Get-Content -LiteralPath $ReportPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($Report.overall_status -ne "pass" -or -not [StringComparer]::OrdinalIgnoreCase.Equals([System.IO.Path]::GetFullPath([string]$Report.executable), $Executable)) {
    throw "Acceptance report does not identify this successful new executable."
}
$RequiredChecks = @("windows_runtime", "bundled_casclib", "map_load", "campaign_switch", "knowledge_pack_export", "pack_query_workflow", "batch_publication", "repeat_load", "gui_tabs")
if ($War3Dir) { $RequiredChecks += "real_windows_casc" }
if ($Report.coverage_scope -ne "requested" -or -not $Report.requested_coverage_complete -or @($Report.skipped_checks).Count -ne 0) {
    throw "Packaged acceptance did not complete every requested check without skips."
}
if (@($Report.requested_checks).Count -ne $RequiredChecks.Count -or
    @(Compare-Object -ReferenceObject $RequiredChecks -DifferenceObject @($Report.requested_checks)).Count -ne 0) {
    throw "Packaged acceptance requested a different check scope."
}
foreach ($Name in $RequiredChecks) {
    $Checks = @($Report.checks | Where-Object { $_.name -eq $Name })
    if ($Checks.Count -ne 1 -or $Checks[0].status -ne "pass") { throw "Required packaged acceptance did not pass: $Name" }
}
if (-not $Onefile) {
    $BundledDlls = @(Get-ChildItem -LiteralPath $AppDirectory -Filter "CascLib.dll" -Recurse -File -Force)
    if ($BundledDlls.Count -ne 1 -or (Get-FileHash -LiteralPath $BundledDlls[0].FullName -Algorithm SHA256).Hash.ToLowerInvariant() -ne $DllHash) {
        throw "The onedir package does not contain the proved new CascLib DLL."
    }
}
$GuideLeaf = '"\u4f7f\u7528\u8bf4\u660e.md"' | ConvertFrom-Json
$GuideSource = Join-Path $RepoRoot ("docs/usable-release-" + $Identity.version + ".md")
Copy-Item -LiteralPath $GuideSource -Destination (Join-Path $OutputRoot $GuideLeaf)
if (-not $Onefile) { Copy-Item -LiteralPath $GuideSource -Destination (Join-Path $AppDirectory $GuideLeaf) }
$SourceAfter = Get-ReleaseSourceSnapshot "source-after-files"
if ($SourceBefore.sha256 -ne $SourceAfter.sha256) { throw "Source files changed during the release build; no release asset was published." }

$AssetStem = "gamexray-v$($Identity.version)-windows-x64"
if ($Onefile) {
    $AssetPath = Join-Path $OutputRoot ($AssetStem + ".exe")
    Copy-Item -LiteralPath $Executable -Destination $AssetPath
}
else {
    $AssetPath = Join-Path $OutputRoot ($AssetStem + ".zip")
    Write-ReleaseZip -SourceDirectory $AppDirectory -RootName $AppName -ArchivePath $AssetPath
}
$AssetHash = (Get-FileHash -LiteralPath $AssetPath -Algorithm SHA256).Hash.ToLowerInvariant()
$Manifest = [ordered]@{
    schema_version = 1
    product = "GameXRay"
    version = $Identity.version
    platform = "windows-x64"
    package_format = $(if ($Onefile) { "onefile" } else { "onedir" })
    built_at_utc = [DateTime]::UtcNow.ToString("o")
    python = $Identity.python
    source_commit = $SourceCommit
    working_tree_dirty = $WorkingTreeDirty
    source_sha256 = $SourceBefore.sha256
    source_inventory = "source-tree.json"
    native_build_evidence = "native-build.json"
    native_source_commit = $Native.source_commit
    native_source_sha256 = $Native.source_sha256
    native_dll_sha256 = $DllHash
    acceptance_report = "acceptance/acceptance.json"
    acceptance_status = $Report.overall_status
    acceptance_coverage_complete = $Report.coverage_complete
    acceptance_coverage_scope = $Report.coverage_scope
    acceptance_requested_coverage_complete = $Report.requested_coverage_complete
    acceptance_requested_checks = @($Report.requested_checks)
    acceptance_executed_checks = @($Report.executed_checks)
    acceptance_not_requested = @($Report.not_requested)
    real_casc_verified = $Report.real_casc_verified
    acceptance_skipped_checks = @($Report.skipped_checks)
    required_checks = $RequiredChecks
    usage = $GuideLeaf
    artifact = [ordered]@{ name = (Split-Path -Leaf $AssetPath); bytes = (Get-Item -LiteralPath $AssetPath).Length; sha256 = $AssetHash }
}
Write-ReleaseJson (Join-Path $OutputRoot "release-manifest.json") $Manifest
$ChecksumNames = @((Split-Path -Leaf $AssetPath), "release-manifest.json", "native-build.json", "source-tree.json", "acceptance/acceptance.json", $GuideLeaf)
$ChecksumLines = foreach ($Name in $ChecksumNames) { ((Get-FileHash -LiteralPath (Join-Path $OutputRoot $Name) -Algorithm SHA256).Hash.ToLowerInvariant()) + "  " + $Name }
[System.IO.File]::WriteAllText((Join-Path $OutputRoot "SHA256SUMS"), (($ChecksumLines -join "`n") + "`n"), [System.Text.UTF8Encoding]::new($false))
Write-Host "Release accepted: $AssetPath"
Write-Host "Manifest: $(Join-Path $OutputRoot 'release-manifest.json')"
Write-Host "Checksums: $(Join-Path $OutputRoot 'SHA256SUMS')"
