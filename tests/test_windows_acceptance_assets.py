"""Windows acceptance scripts and CI wiring stay executable and complete."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import requires_posix_provenance


_ROOT = Path(__file__).resolve().parents[1]


def test_windows_capability_filter_is_limited_to_posix_provenance_suites() -> None:
    # Given / When / Then: extraction and packaged acceptance remain mandatory.
    for path in (
        Path("tests/test_batch_e2e.py"),
        Path("tests/test_acceptance_runner.py"),
        Path("tests/test_gui_description_cache.py"),
        Path("tests/test_trusted_description_cache.py"),
    ):
        assert not requires_posix_provenance(path)
    for path in (
        Path("tests/test_batch_map_retirement.py"),
        Path("tests/test_description_cache_publication.py"),
        Path("tests/test_integrity_snapshot.py"),
        Path("tests/test_safe_output_publication_atomicity.py"),
    ):
        assert requires_posix_provenance(path)


def _onefile_acceptance_sources() -> tuple[tuple[str, str], ...]:
    script = (_ROOT / "tools" / "run_windows_acceptance.ps1").read_text(
        encoding="utf-8"
    )

    workflow = (_ROOT / ".github" / "workflows" / "windows-package.yml").read_text(
        encoding="utf-8",
    )
    hosted = workflow.split(
        "      - name: Execute packaged onefile acceptance\n",
        maxsplit=1,
    )[1].split("      - name: Prepare release assets\n", maxsplit=1)[0]
    return (("real-machine", script), ("hosted", hosted))


def test_windows_acceptance_script_builds_tests_packages_and_runs_exe() -> None:
    # Given: the repository's one-command real-machine acceptance script.
    script = (_ROOT / "tools" / "run_windows_acceptance.ps1").read_text(
        encoding="utf-8"
    )

    # When/Then: every required gate executes in order through the packaged EXE.
    required = (
        "$env:W3XRAY_WAR3_DIR",
        "build_casclib.ps1",
        "uv run w3xray-test",
        "\n& uv run w3xray-dist\n",
        "windows-onedir",
        "Get-ChildItem",
        '"*.exe"',
        "$OnedirExe.Count -ne 1",
        "\n& uv run w3xray-dist --onefile\n",
        "windows-onefile",
        "$OnefileExe.Count -ne 1",
    )
    positions = [script.index(value) for value in required]
    assert positions == sorted(positions)
    assert script.count("\n& uv run w3xray-dist\n") == 1
    assert script.count("\n& uv run w3xray-dist --onefile\n") == 1
    assert script.count('"--repeat", "5"') == 2
    for argument in ('"acceptance"', '"--require-windows"', '"--war3-dir"'):
        assert script.count(argument) == 2


def test_hosted_windows_workflow_packages_and_executes_artifact() -> None:
    # Given: the hosted Windows build workflow.
    workflow = (_ROOT / ".github" / "workflows" / "windows-package.yml").read_text(
        encoding="utf-8"
    )

    # When: the named steps are isolated so evidence cannot leak across step boundaries.
    onedir_acceptance = workflow.split(
        "      - name: Execute packaged onedir acceptance\n",
        maxsplit=1,
    )[1].split("      - name: Build onefile executable\n", maxsplit=1)[0]
    onefile_acceptance = workflow.split(
        "      - name: Execute packaged onefile acceptance\n",
        maxsplit=1,
    )[1].split("      - name: Prepare release assets\n", maxsplit=1)[0]
    release_preparation = workflow.split(
        "      - name: Prepare release assets\n",
        maxsplit=1,
    )[1].split("      - name: Upload release assets\n", maxsplit=1)[0]
    upload_step = workflow.split("      - name: Upload release assets\n", maxsplit=1)[1]

    # Then: triggers, exact builds, per-format acceptance, and release assets are complete.
    for trigger in ("branches: [main]", "  pull_request:\n", "  workflow_dispatch:\n"):
        assert trigger in workflow
    assert (
        workflow.count(
            "      - name: Build onedir executable\n        run: uv run w3xray-dist\n"
        )
        == 1
    )
    assert (
        workflow.count(
            "      - name: Build onefile executable\n"
            "        run: uv run w3xray-dist --onefile\n"
        )
        == 1
    )
    assert '--report ".\\artifacts/windows-onedir/acceptance.json"' in onedir_acceptance
    assert "--repeat 5 --require-windows" in onedir_acceptance
    assert '"--report", $OnefileReport' in onefile_acceptance
    assert '"--repeat", "5"' in onefile_acceptance
    assert '"--require-windows"' in onefile_acceptance
    assert (
        '$DirectExe = @(Get-ChildItem -LiteralPath ".\\dist" -Filter "*.exe" -File)'
        in release_preparation
    )
    assert "$DirectExe[0].FullName" in release_preparation
    assert "$OnefileExe" not in release_preparation
    for release_filename in (
        "w3xray-v$Version-windows-x64.zip",
        "w3xray-v$Version-windows-x64.exe",
        "windows-onedir-acceptance.json",
        "windows-onefile-acceptance.json",
    ):
        assert release_filename in release_preparation
    assert "actions/upload-artifact@v4" in upload_step
    assert "name: w3xray-windows-release-assets" in upload_step
    assert "if-no-files-found: error" in upload_step


def test_real_machine_onedir_discovery_ignores_stale_direct_exe() -> None:
    # Given: an onedir phase that can inherit a direct EXE from an earlier run.
    script = (_ROOT / "tools" / "run_windows_acceptance.ps1").read_text(
        encoding="utf-8"
    )
    onedir_phase = script.split("\n& uv run w3xray-dist\n", maxsplit=1)[1].split(
        "\n& uv run w3xray-dist --onefile\n",
        maxsplit=1,
    )[0]

    # When/Then: discovery enters the sole onedir directory before searching recursively.
    required = (
        "$Onedir = @(Get-ChildItem -LiteralPath $DistDir -Directory)",
        "$Onedir.Count -ne 1",
        '$OnedirExe = @(Get-ChildItem -LiteralPath $Onedir[0].FullName -Filter "*.exe" -File -Recurse)',
    )
    assert [onedir_phase.index(value) for value in required] == sorted(
        onedir_phase.index(value) for value in required
    )
    assert (
        'Get-ChildItem -LiteralPath $DistDir -Filter "*.exe" -File -Recurse'
        not in onedir_phase
    )


def test_hosted_onedir_discovery_ignores_stale_direct_exe() -> None:
    # Given: the hosted onedir acceptance block.
    workflow = (_ROOT / ".github" / "workflows" / "windows-package.yml").read_text(
        encoding="utf-8",
    )
    onedir_phase = workflow.split(
        "      - name: Execute packaged onedir acceptance\n",
        maxsplit=1,
    )[1].split("      - name: Build onefile executable\n", maxsplit=1)[0]

    # When/Then: discovery enters the sole onedir directory before searching recursively.
    required = (
        '$Onedir = @(Get-ChildItem -LiteralPath ".\\dist" -Directory)',
        "$Onedir.Count -ne 1",
        '$OnedirExe = @(Get-ChildItem -LiteralPath $Onedir[0].FullName -Filter "*.exe" -File -Recurse)',
    )
    assert [onedir_phase.index(value) for value in required] == sorted(
        onedir_phase.index(value) for value in required
    )
    assert (
        'Get-ChildItem -LiteralPath ".\\dist" -Filter "*.exe" -File -Recurse'
        not in onedir_phase
    )


@pytest.mark.parametrize(("surface", "source"), _onefile_acceptance_sources())
def test_onefile_acceptance_removes_stale_evidence_before_launch(
    surface: str,
    source: str,
) -> None:
    # Given: a onefile acceptance surface that can inherit evidence from an earlier run.
    removal = "Remove-Item -LiteralPath $OnefileEvidenceDir -Recurse -Force"

    # When/Then: stale evidence is deleted before the new acceptance arguments are built.
    assert removal in source, f"{surface} onefile acceptance retains stale evidence"
    assert source.index(removal) < source.index("$OnefileAcceptanceArgs")


@pytest.mark.parametrize(("surface", "source"), _onefile_acceptance_sources())
def test_onefile_acceptance_uses_absolute_paths_and_working_directory(
    surface: str,
    source: str,
) -> None:
    # Given: fixtures and evidence can live beneath paths containing spaces.
    required = (
        "$MapPath = (Resolve-Path",
        "$CampaignPath = (Resolve-Path",
        "$OnefileEvidenceDir =",
        "$OnefileReport =",
        "$OnefileWorkingDirectory =",
        "-WorkingDirectory $OnefileWorkingDirectory",
    )

    # When/Then: the direct process receives only absolute paths and an explicit working directory.
    missing = [value for value in required if value not in source]
    assert not missing, (
        f"{surface} onefile acceptance lacks absolute path setup: {missing}"
    )
    assert '".\\tests\\fixtures' not in source
    assert '".\\artifacts/windows-onefile' not in source


@pytest.mark.parametrize(("surface", "source"), _onefile_acceptance_sources())
def test_onefile_acceptance_waits_and_validates_fresh_report(
    surface: str,
    source: str,
) -> None:
    # Given: a windowed PyInstaller EXE can detach from a direct PowerShell invocation.
    required = (
        "$OnefileProcess = Start-Process",
        "-Wait",
        "-PassThru",
        "$OnefileProcess.ExitCode",
        "Test-Path -LiteralPath $OnefileReport",
        "Get-Content -LiteralPath $OnefileReport -Raw -Encoding UTF8 | ConvertFrom-Json",
        ".overall_status",
        ".executable",
    )

    # When/Then: launch, wait/exit, fresh-file, and JSON gates execute in that order.
    missing = [value for value in required if value not in source]
    assert not missing, (
        f"{surface} onefile acceptance lacks completion gates: {missing}"
    )
    positions = [source.index(value) for value in required]
    assert positions == sorted(positions)


@pytest.mark.parametrize(("surface", "source"), _onefile_acceptance_sources())
def test_onefile_acceptance_rejects_unsafe_direct_invocation(
    surface: str,
    source: str,
) -> None:
    # Given: `&` plus LASTEXITCODE did not wait for the windowed onefile process tree.
    # When/Then: both surfaces use the shared encoder and reject that launch pattern.
    assert "ConvertTo-WindowsCommandLine $OnefileAcceptanceArgs" in source, surface
    assert not any(
        line.lstrip().startswith("& $OnefileExe") for line in source.splitlines()
    ), surface


def test_windows_process_helper_quotes_powershell_51_argument_lists() -> None:
    # Given: Start-Process on Windows PowerShell 5.1 joins ArgumentList values itself.
    helper_path = _ROOT / "tools" / "windows_process.ps1"
    assert helper_path.is_file(), "shared Windows command-line encoder is missing"
    helper = helper_path.read_text(encoding="utf-8")

    # When/Then: quotes and trailing backslashes are escaped before one command line is joined.
    required = (
        "[AllowEmptyString()]",
        "$Argument -notmatch '[\\s\"]'",
        "[regex]::Replace($Argument, '(\\\\*)\"', '$1$1\\\"')",
        "[regex]::Replace($escaped, '(\\\\+)$', '$1$1')",
        "return '\"' + $escaped + '\"'",
        '$encodedArguments -join " "',
    )
    missing = [value for value in required if value not in helper]
    assert not missing, f"unsafe Windows argument encoder: {missing}"
    assert helper.isascii()


def test_real_machine_powershell_51_script_has_no_utf8_source_tokens() -> None:
    # Windows PowerShell 5.1 reads BOM-less scripts through the legacy code page.
    script = (_ROOT / "tools" / "run_windows_acceptance.ps1").read_text(
        encoding="utf-8"
    )

    assert script.isascii()


def test_hosted_powershell_51_acceptance_step_has_no_utf8_source_tokens() -> None:
    workflow = (_ROOT / ".github" / "workflows" / "windows-package.yml").read_text(
        encoding="utf-8",
    )
    acceptance_step = workflow.split(
        "- name: Execute packaged onedir acceptance", maxsplit=1
    )[1]
    acceptance_step = acceptance_step.split(
        "- name: Upload release assets", maxsplit=1
    )[0]

    assert acceptance_step.isascii()


def test_casclib_build_preserves_dotted_cmake_policy_version() -> None:
    # Given: Windows PowerShell forwards native CMake arguments itself.
    script = (_ROOT / "tools" / "build_casclib.ps1").read_text(encoding="utf-8")

    # When/Then: the dotted policy value is one quoted native argument.
    assert '"-DCMAKE_POLICY_VERSION_MINIMUM=3.5"' in script
