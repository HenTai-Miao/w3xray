"""Release build paths and console mode preserve an executable CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from gametool.dev_test import create_test_environment
from gametool.dist_build import (
    APP_NAME,
    DistArgumentError,
    DistFormat,
    parse_cli_options,
)

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "tools" / "build_windows_release.ps1"


def test_dist_options_select_external_build_and_artifact_roots(tmp_path: Path) -> None:
    dist = tmp_path / "release files"
    work = tmp_path / "build files"
    options = parse_cli_options(
        ("--distpath", str(dist), "--onefile", "--workpath", str(work), "--no-clean")
    )

    assert options.dist_path == dist
    assert options.work_path == work
    assert options.format is DistFormat.ONEFILE
    assert options.clean is False


@pytest.mark.parametrize("argument", ("--distpath", "--workpath"))
@pytest.mark.parametrize("tail", ((), ("",), ("--onefile",)))
def test_dist_path_options_reject_missing_values(
    argument: str, tail: tuple[str, ...]
) -> None:
    with pytest.raises(DistArgumentError, match="需要目录路径"):
        parse_cli_options((argument, *tail))


def test_windows_spec_keeps_cli_streams_and_hides_only_its_own_console() -> None:
    root = Path(__file__).resolve().parents[1]
    spec = (root / f"{APP_NAME}.spec").read_text(encoding="utf-8")

    assert "'console': True" in spec
    assert "'hide_console': 'hide-early' if sys.platform == 'win32' else None" in spec
    assert "'console': False" not in spec


@pytest.mark.skipif(os.name != "nt", reason="Windows release script")
def test_release_script_preserves_existing_output_assets(tmp_path: Path) -> None:
    output = tmp_path / "already populated"
    output.mkdir()
    asset = output / "user-asset.json"
    asset.write_bytes(b'{"keep": "exact original bytes"}\r\n')
    before = (asset.read_bytes(), asset.stat().st_mtime_ns)

    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(_SCRIPT),
            "-OutputRoot",
            str(output),
        ],
        cwd=_ROOT,
        env=create_test_environment(),
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert result.returncode != 0
    assert b"new or empty ordinary directory" in result.stderr
    assert list(output.iterdir()) == [asset]
    assert (asset.read_bytes(), asset.stat().st_mtime_ns) == before


@pytest.mark.skipif(os.name != "nt", reason="Windows release script")
def test_release_script_rejects_repository_as_output() -> None:
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(_SCRIPT),
            "-OutputRoot",
            str(_ROOT),
        ],
        cwd=_ROOT,
        env=create_test_environment(),
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert result.returncode != 0
    assert b"OutputRoot must be outside the repository" in result.stderr


@pytest.mark.skipif(os.name != "nt", reason="Windows process argument encoding")
def test_release_process_captures_status_and_streams_with_private_environment(
    tmp_path: Path,
) -> None:
    harness = tmp_path / "invoke-release-process.ps1"
    harness.write_text(
        r"""param($ScriptPath, $RepositoryPath, $EvidenceRoot, $PythonPath)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
. (Join-Path $RepositoryPath 'tools/windows_process.ps1')
$Tokens = $null
$ParseErrors = $null
$Ast = [System.Management.Automation.Language.Parser]::ParseFile($ScriptPath, [ref]$Tokens, [ref]$ParseErrors)
if ($ParseErrors.Count) { throw ($ParseErrors | Out-String) }
$Functions = @($Ast.FindAll({ param($Node) $Node -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true))
foreach ($Function in $Functions) {
    if ($Function.Name -eq 'Invoke-ReleaseProcess') {
        Invoke-Expression $Function.Extent.Text
    }
}
$RepoRoot = $RepositoryPath
$LogsRoot = Join-Path $EvidenceRoot 'logs'
$PrivateCache = Join-Path $EvidenceRoot 'private-cache'
$War3Dir = ''
New-Item -ItemType Directory -Path $LogsRoot, $PrivateCache | Out-Null
$Before = $env:GAMEXRAY_CACHE_DIR
$Code = 'import json, os, sys; print(json.dumps({"argv": sys.argv[1:], "cache": os.environ["GAMEXRAY_CACHE_DIR"], "gui": os.environ["GAMEXRAY_GUI_CONFIG_PATH"], "war3": os.environ.get("GAMEXRAY_WAR3_DIR")})); print("captured stderr", file=sys.stderr); sys.exit(7)'
$Result = Invoke-ReleaseProcess -FilePath $PythonPath -Arguments @('-X', 'utf8', '-c', $Code, 'space value', 'quote"value', '', 'trailing\') -Name 'child'
[ordered]@{ exit_code = $Result.ExitCode; stdout = $Result.Stdout; stderr = $Result.Stderr; stdout_path = $Result.StdoutPath; stderr_path = $Result.StderrPath; cache_before = $Before; cache_after = $env:GAMEXRAY_CACHE_DIR } | ConvertTo-Json -Compress
""",
        encoding="ascii",
    )
    environment = create_test_environment()
    environment["GAMEXRAY_WAR3_DIR"] = str(tmp_path / "caller client")

    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(harness),
            str(_SCRIPT),
            str(_ROOT),
            str(tmp_path),
            sys.executable,
        ],
        cwd=tmp_path,
        env=environment,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.splitlines()[-1])
    assert payload["exit_code"] == 7
    stdout = json.loads(payload["stdout"])
    assert stdout["argv"] == ["space value", 'quote"value', "", "trailing\\"]
    assert stdout["cache"] == str(tmp_path / "private-cache")
    assert stdout["gui"] == str(tmp_path / "private-cache" / "gui-config.json")
    assert stdout["war3"] is None
    assert payload["stderr"].strip() == "captured stderr"
    assert (
        Path(payload["stdout_path"]).read_bytes().decode("utf-8") == payload["stdout"]
    )
    assert (
        Path(payload["stderr_path"]).read_bytes().decode("utf-8") == payload["stderr"]
    )
    assert (
        payload["cache_before"]
        == payload["cache_after"]
        == environment["GAMEXRAY_CACHE_DIR"]
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows .NET Framework ZIP names")
def test_release_zip_has_raw_forward_slash_names_and_complete_payloads(
    tmp_path: Path,
) -> None:
    source = tmp_path / APP_NAME
    payloads = {
        "app.bin": bytes(range(256)) * 8,
        "_internal/hidden.bin": b"hidden resource\x00\xff",
        "_internal/嵌套 with spaces/完整文本.txt": "\ufeff完整\t内容\r\n".encode(
            "utf-8"
        ),
        "empty.txt": b"",
    }
    for relative, payload in payloads.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    (source / "empty-directory").mkdir()
    before = {
        relative: (
            (source / relative).read_bytes(),
            (source / relative).stat().st_mtime_ns,
        )
        for relative in payloads
    }
    unrelated = tmp_path / "user-asset.json"
    unrelated.write_bytes(b"preserve this unrelated asset")
    archive_path = tmp_path / "release.zip"
    harness = tmp_path / "write-release-zip.ps1"
    harness.write_text(
        r"""param($ScriptPath, $SourceDirectory, $RootName, $ArchivePath)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$Tokens = $null
$ParseErrors = $null
$Ast = [System.Management.Automation.Language.Parser]::ParseFile($ScriptPath, [ref]$Tokens, [ref]$ParseErrors)
if ($ParseErrors.Count) { throw ($ParseErrors | Out-String) }
foreach ($Function in @($Ast.FindAll({ param($Node) $Node -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true))) {
    if ($Function.Name -eq 'Write-ReleaseZip') { Invoke-Expression $Function.Extent.Text }
}
$Hidden = Get-Item -LiteralPath (Join-Path $SourceDirectory '_internal/hidden.bin') -Force
$Hidden.Attributes = $Hidden.Attributes -bor [System.IO.FileAttributes]::Hidden
Write-ReleaseZip -SourceDirectory $SourceDirectory -RootName $RootName -ArchivePath $ArchivePath
""",
        encoding="ascii",
    )
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(harness),
        str(_SCRIPT),
        str(source),
        APP_NAME,
        str(archive_path),
    ]
    result = subprocess.run(
        command,
        cwd=tmp_path,
        env=create_test_environment(),
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    with zipfile.ZipFile(archive_path) as archive:
        for entry in archive.infolist():
            assert entry.orig_filename == entry.filename
            assert "\\" not in entry.orig_filename
            assert entry.orig_filename.startswith(APP_NAME + "/")
        packed = {
            entry.orig_filename.removeprefix(APP_NAME + "/"): archive.read(entry)
            for entry in archive.infolist()
            if not entry.is_dir()
        }
        assert packed == payloads
        assert archive.getinfo(APP_NAME + "/empty-directory/").is_dir()
    assert {
        relative: (
            (source / relative).read_bytes(),
            (source / relative).stat().st_mtime_ns,
        )
        for relative in payloads
    } == before
    assert unrelated.read_bytes() == b"preserve this unrelated asset"

    # A failed/reused destination must retain the exact earlier archive.
    archive_before = (archive_path.read_bytes(), archive_path.stat().st_mtime_ns)
    repeated = subprocess.run(
        command,
        cwd=tmp_path,
        env=create_test_environment(),
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert repeated.returncode != 0
    assert (
        archive_path.read_bytes(),
        archive_path.stat().st_mtime_ns,
    ) == archive_before
