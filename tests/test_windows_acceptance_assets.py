"""Windows acceptance scripts and CI wiring stay executable and complete."""

from __future__ import annotations

from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]


def test_windows_acceptance_script_builds_tests_packages_and_runs_exe() -> None:
    # Given: the repository's one-command real-machine acceptance script.
    script = (_ROOT / "tools" / "run_windows_acceptance.ps1").read_text(encoding="utf-8")

    # When/Then: every required gate executes in order through the packaged EXE.
    required = (
        "$env:W3XRAY_WAR3_DIR",
        "build_casclib.ps1",
        "uv run w3xray-test",
        "uv run w3xray-dist",
        "魔兽地图提取器.exe",
        '"acceptance"',
        '"--require-windows"',
        '"--war3-dir"',
    )
    positions = [script.index(value) for value in required]
    assert positions == sorted(positions)


def test_hosted_windows_workflow_packages_and_executes_artifact() -> None:
    # Given: the hosted Windows build workflow.
    workflow = (_ROOT / ".github" / "workflows" / "windows-package.yml").read_text(encoding="utf-8")

    # When/Then: it builds the pinned DLL, runs tests, packages, runs GUI acceptance, and uploads evidence.
    for required in (
        "windows-2022",
        "tools/build_casclib.ps1",
        "uv run w3xray-test",
        "uv run w3xray-dist",
        "魔兽地图提取器.exe",
        "acceptance",
        "--require-windows",
        "actions/upload-artifact@",
    ):
        assert required in workflow


def test_casclib_build_preserves_dotted_cmake_policy_version() -> None:
    # Given: Windows PowerShell forwards native CMake arguments itself.
    script = (_ROOT / "tools" / "build_casclib.ps1").read_text(encoding="utf-8")

    # When/Then: the dotted policy value is one quoted native argument.
    assert '"-DCMAKE_POLICY_VERSION_MINIMUM=3.5"' in script


def test_real_install_workflow_requires_dedicated_self_hosted_machine() -> None:
    # Given: a manually triggered workflow that can access a real installed client.
    workflow = (_ROOT / ".github" / "workflows" / "windows-real-war3.yml").read_text(encoding="utf-8")

    # When/Then: it cannot accidentally claim hosted synthetic coverage as real-install evidence.
    assert "workflow_dispatch" in workflow
    assert "self-hosted" in workflow
    assert "w3xray-war3" in workflow
    assert "run_windows_acceptance.ps1" in workflow
    assert "war3_dir" in workflow


def test_real_install_input_reaches_powershell_through_environment() -> None:
    # Given: a manually supplied path that may contain PowerShell metacharacters.
    workflow = (_ROOT / ".github" / "workflows" / "windows-real-war3.yml").read_text(encoding="utf-8")

    # When/Then: the expression is data in env, never source text in the run block.
    assert "W3XRAY_ACCEPTANCE_WAR3_DIR: ${{ inputs.war3_dir }}" in workflow
    assert "-War3Dir $env:W3XRAY_ACCEPTANCE_WAR3_DIR" in workflow
    assert "-War3Dir '${{ inputs.war3_dir }}'" not in workflow


def test_real_install_runner_executes_only_protected_local_ref() -> None:
    # Given: a persistent runner with access to a real Warcraft installation.
    workflow = (_ROOT / ".github" / "workflows" / "windows-real-war3.yml").read_text(encoding="utf-8")

    # When/Then: arbitrary dispatch refs cannot supply code or persisted credentials.
    assert "permissions:\n  contents: read" in workflow
    assert "if: github.ref == 'refs/heads/local'" in workflow
    assert "environment: w3xray-real-war3" in workflow
    assert "ref: local" in workflow
    assert "persist-credentials: false" in workflow
