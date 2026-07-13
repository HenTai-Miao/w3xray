"""macOS and Linux release packaging remains reproducible and documented."""

from __future__ import annotations

from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW = _ROOT / ".github" / "workflows" / "posix-package.yml"


def test_posix_workflow_targets_release_tag_on_supported_runners() -> None:
    workflow = _WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "default: v0.1.2" in workflow
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
        "uv run w3xray-test",
        "xvfb-run -a uv run w3xray-test",
        "--basetemp /dev/shm/w3xray-pytest",
        "for Attempt in 1 2",
        "retrying the complete suite in a fresh process",
        "tests/test_gui_pane_state.py::TestPaneState::test_object_editor_pane_positions_restore_from_named_config",
        "tests/test_gui_pane_state.py::TestPaneState::test_object_editor_pane_positions_save_on_drag_release",
        "tests/test_gui_scroll.py::TestColumnAutosize::test_object_column_grows_for_long_name",
        'test -f "$PythonLibDir/libtcl9.0.so"',
        'test -f "$PythonLibDir/libtcl9tk9.0.so"',
        'export LD_LIBRARY_PATH="$PythonLibDir${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"',
        'hook-PIL.ImageTk.py',
        'hiddenimports = ["PIL._tkinter_finder"]',
        "uv run w3xray-dist",
        'Executable="dist/魔兽地图提取器/魔兽地图提取器"',
        "AcceptanceArgs=(acceptance",
        '"$Executable" "${AcceptanceArgs[@]}"',
        'xvfb-run -a "$Executable" "${AcceptanceArgs[@]}"',
        "overall_status == \"pass\"",
        "ditto -c -k --keepParent",
        "tar -C dist -czf",
        "unzip -t",
        "tar -tzf",
        'test -x "$ArchivedExecutable"',
        'file "$ArchivedExecutable"',
        'grep -Fq "$ExpectedArchitecture"',
        "w3xray-v$Version-macos-${{ matrix.arch }}.zip",
        "w3xray-v$Version-linux-${{ matrix.arch }}.tar.gz",
        "actions/upload-artifact@v4",
        "if-no-files-found: error",
    ):
        assert required in workflow
    assert "--no-gui" not in workflow


def test_readme_lists_macos_and_linux_release_assets() -> None:
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    release_section = readme.split("## 开发运行（uv）", maxsplit=1)[0]

    for asset in (
        "w3xray-v0.1.2-macos-arm64.zip",
        "w3xray-v0.1.2-macos-x64.zip",
        "w3xray-v0.1.2-linux-x64.tar.gz",
    ):
        assert asset in release_section
    assert "Apple Silicon" in release_section
    assert "Intel" in release_section
    assert "未签名" in release_section
