"""macOS and Linux release packaging remains reproducible and documented."""

from __future__ import annotations

from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW = _ROOT / ".github" / "workflows" / "posix-package.yml"


def test_posix_workflow_targets_release_tag_on_supported_runners() -> None:
    workflow = _WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "default: v0.7.0" in workflow
    assert "ref: ${{ inputs.source_ref }}" in workflow
    assert "persist-credentials: false" in workflow
    assert "SOURCE_REF_INPUT: ${{ inputs.source_ref }}" in workflow
    assert "'${{ inputs.source_ref }}'" not in workflow
    for target in (
        "runner: macos-15-intel\n            platform: macos\n            arch: x64\n            machine: x86_64",
        "runner: macos-15\n            platform: macos\n            arch: arm64\n            machine: arm64",
        "runner: ubuntu-24.04\n            platform: linux\n            arch: x64",
    ):
        assert target in workflow
    assert "EXPECTED_MACHINE: ${{ matrix.machine }}" in workflow
    assert 'test "$ActualMachine" = "$EXPECTED_MACHINE"' in workflow


def test_posix_workflow_tests_accepts_and_archives_onedir_package() -> None:
    workflow = _WORKFLOW.read_text(encoding="utf-8")

    for required in (
        "brew install python-tk@3.14",
        "sudo apt-get install --no-install-recommends -y xauth xvfb",
        "uv sync --dev",
        "import tkinter; print(tkinter.TkVersion)",
        "uv run gamexray-test",
        "xvfb-run -a uv run gamexray-test",
        "--basetemp /dev/shm/gamexray-pytest",
        'test -f "$PythonLibDir/libtcl9.0.so"',
        'test -f "$PythonLibDir/libtcl9tk9.0.so"',
        'export LD_LIBRARY_PATH="$PythonLibDir${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"',
        "hook-PIL.ImageTk.py",
        'hiddenimports = ["PIL._tkinter_finder"]',
        "uv run gamexray-dist",
        'Executable="dist/GameXRay 游戏档案透视器/GameXRay 游戏档案透视器"',
        "AcceptanceArgs=(acceptance",
        '"$Executable" "${AcceptanceArgs[@]}"',
        'xvfb-run -a "$Executable" "${AcceptanceArgs[@]}"',
        'overall_status == "pass"',
        "ditto -c -k --keepParent",
        "tar -C dist -czf",
        "unzip -t",
        "tar -tzf",
        'test -x "$ArchivedExecutable"',
        'file "$ArchivedExecutable"',
        'grep -Fq "$ExpectedArchitecture"',
        "gamexray-v$Version-macos-${{ matrix.arch }}.zip",
        "gamexray-v$Version-linux-${{ matrix.arch }}.tar.gz",
        "actions/upload-artifact@v4",
        "if-no-files-found: error",
    ):
        assert required in workflow
    assert "--no-gui" not in workflow


def test_posix_suites_run_once_without_exclusions_and_keep_failure_evidence() -> None:
    workflow = _WORKFLOW.read_text(encoding="utf-8")

    for platform in ("macOS", "Linux"):
        step = workflow.split(
            f"      - name: Run full test suite on {platform}\n",
            maxsplit=1,
        )[1].split("\n      - name: ", maxsplit=1)[0]
        assert step.count("uv run gamexray-test") == 1
        assert "set -euo pipefail" in step
        assert '--junitxml "$EvidenceDir/pytest.xml"' in step
        assert '2>&1 | tee "$EvidenceDir/pytest.log"' in step
        assert "trap " in step
        assert '"$?" > "$EvidenceDir/exit-code.txt"' in step
        for excluded in (
            "--deselect",
            "--ignore",
            "--last-failed",
            "--collect-only",
            "--lf",
            " -k ",
            " -m ",
            "tests/",
            "for Attempt",
            "retrying",
            "continue-on-error",
            "|| true",
        ):
            assert excluded not in step
        assert "uv run gamexray-test -q -ra" in step
        if platform == "Linux":
            assert "xvfb-run -a uv run gamexray-test" in step
            assert "--basetemp /dev/shm/gamexray-pytest" in step

    upload = workflow.split("      - name: Upload test evidence\n", maxsplit=1)[
        1
    ].split("\n      - name: ", maxsplit=1)[0]
    assert "if: always()" in upload
    assert "uses: actions/upload-artifact@v4" in upload
    assert "name: gamexray-${{ matrix.platform }}-${{ matrix.arch }}-tests" in upload
    assert "path: artifacts/${{ matrix.platform }}-${{ matrix.arch }}-tests/" in upload
    assert 'xvfb-run -a "$Executable"' in workflow


def test_readme_lists_macos_and_linux_release_assets() -> None:
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    release_section = readme.split("## 开发运行（uv）", maxsplit=1)[0]

    for asset in (
        "gamexray-v0.7.0-macos-arm64.zip",
        "gamexray-v0.7.0-macos-x64.zip",
        "gamexray-v0.7.0-linux-x64.tar.gz",
    ):
        assert asset in release_section
    assert "Apple Silicon" in release_section
    assert "Intel" in release_section
    assert "未签名" in release_section
