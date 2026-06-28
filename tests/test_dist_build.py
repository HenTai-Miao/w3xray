"""dist 打包入口的命令构建与 dry-run 测试。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from w3xtool.dist_build import (
    APP_NAME,
    DistBuildConfig,
    build_pyinstaller_command,
    expected_artifact_path,
)


def test_build_pyinstaller_command_uses_project_paths(tmp_path: Path) -> None:
    # Given: a project-local dist build configuration.
    spec_path = tmp_path / f"{APP_NAME}.spec"
    config = DistBuildConfig(
        project_root=tmp_path,
        spec_path=spec_path,
        dist_path=tmp_path / "dist",
        work_path=tmp_path / "build" / "pyinstaller",
        clean=True,
    )

    # When: the PyInstaller command is generated.
    command = build_pyinstaller_command(config, python_executable="python")

    # Then: PyInstaller is invoked through the active interpreter with stable output paths.
    assert command == (
        "python",
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(tmp_path / "dist"),
        "--workpath",
        str(tmp_path / "build" / "pyinstaller"),
        str(spec_path),
    )


def test_expected_artifact_path_uses_windows_exe_suffix(tmp_path: Path) -> None:
    # Given: a Windows dist build configuration.
    config = DistBuildConfig(
        project_root=tmp_path,
        spec_path=tmp_path / f"{APP_NAME}.spec",
        dist_path=tmp_path / "dist",
        work_path=tmp_path / "build" / "pyinstaller",
        clean=True,
    )

    # When: the expected artifact path is rendered for Windows.
    artifact_path = expected_artifact_path(config, system="Windows")

    # Then: the distributable entrypoint is the exe inside the onedir folder.
    assert artifact_path == tmp_path / "dist" / APP_NAME / f"{APP_NAME}.exe"


def test_dist_build_module_dry_run_prints_pyinstaller_command() -> None:
    # Given: the project module is executed in dry-run mode.
    command = [sys.executable, "-m", "w3xtool.dist_build", "--dry-run"]

    # When: the command runs through the same Python used by pytest.
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )

    # Then: it prints the PyInstaller invocation without creating a build.
    assert "PyInstaller" in result.stdout
    assert "魔兽地图提取器.spec" in result.stdout
    assert "dry-run" in result.stdout
