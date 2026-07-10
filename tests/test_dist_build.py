"""dist 打包入口的命令构建与 dry-run 测试。"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from w3xtool.casclib_dist import CascLibDistError, validate_casclib_dist_assets
from w3xtool.dist_build import (
    APP_NAME,
    DistBuildConfig,
    build_pyinstaller_command,
    expected_artifact_path,
    run_dist_build,
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
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "cp1252"},
    )

    # Then: it prints the PyInstaller invocation without creating a build.
    assert "PyInstaller" in result.stdout
    assert "魔兽地图提取器.spec" in result.stdout
    assert "dry-run" in result.stdout


def _write_pe(path: Path, *, machine: int = 0x8664) -> bytes:
    data = bytearray(128)
    data[:2] = b"MZ"
    data[0x3C:0x40] = (64).to_bytes(4, "little")
    data[64:68] = b"PE\0\0"
    data[68:70] = machine.to_bytes(2, "little")
    payload = bytes(data)
    path.parent.mkdir(parents=True)
    path.write_bytes(payload)
    return payload


def _write_matching_hash(root: Path, payload: bytes) -> None:
    hash_path = root / "third_party" / "CascLib" / "bin" / "win-x64" / "CascLib.dll.sha256"
    hash_path.write_text(hashlib.sha256(payload).hexdigest() + "\n", encoding="ascii")


@pytest.mark.parametrize("missing_name", ["CascLib.dll", "CascLib.dll.sha256"])
def test_windows_dist_rejects_missing_casclib_artifact(tmp_path: Path, missing_name: str) -> None:
    # Given: only one of the required native build artifacts exists.
    dll = tmp_path / "third_party" / "CascLib" / "bin" / "win-x64" / "CascLib.dll"
    payload = _write_pe(dll)
    _write_matching_hash(tmp_path, payload)
    (dll.parent / missing_name).unlink()

    # When/Then: Windows validation fails with the missing artifact name.
    with pytest.raises(CascLibDistError) as caught:
        validate_casclib_dist_assets(tmp_path, system="Windows")
    assert missing_name in str(caught.value)


def test_windows_dist_rejects_hash_mismatch(tmp_path: Path) -> None:
    # Given: an x64 PE whose generated hash does not match.
    dll = tmp_path / "third_party" / "CascLib" / "bin" / "win-x64" / "CascLib.dll"
    _write_pe(dll)
    (dll.parent / "CascLib.dll.sha256").write_text("0" * 64 + "\n", encoding="ascii")

    # When/Then: the dist gate rejects the unverified binary.
    with pytest.raises(CascLibDistError, match="SHA256"):
        validate_casclib_dist_assets(tmp_path, system="Windows")


def test_windows_dist_rejects_non_x64_pe(tmp_path: Path) -> None:
    # Given: a valid PE header for x86 rather than AMD64.
    dll = tmp_path / "third_party" / "CascLib" / "bin" / "win-x64" / "CascLib.dll"
    payload = _write_pe(dll, machine=0x014C)
    _write_matching_hash(tmp_path, payload)

    # When/Then: the dist gate rejects the wrong machine architecture.
    with pytest.raises(CascLibDistError, match="x64 PE"):
        validate_casclib_dist_assets(tmp_path, system="Windows")


def test_dist_asset_validation_is_not_required_off_windows(tmp_path: Path) -> None:
    # Given: a non-Windows build without local native artifacts.
    # When/Then: the Windows-only gate is a no-op.
    validate_casclib_dist_assets(tmp_path, system="Darwin")


def test_windows_dist_accepts_matching_x64_pe(tmp_path: Path) -> None:
    # Given: a matching hash and an AMD64 PE CascLib DLL.
    dll = tmp_path / "third_party" / "CascLib" / "bin" / "win-x64" / "CascLib.dll"
    payload = _write_pe(dll)
    _write_matching_hash(tmp_path, payload)

    # When/Then: the native asset gate accepts the artifact pair.
    validate_casclib_dist_assets(tmp_path, system="Windows")


def test_windows_dry_run_executes_native_asset_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a Windows dist configuration with a spec but no CascLib artifacts.
    spec_path = tmp_path / f"{APP_NAME}.spec"
    spec_path.write_text("", encoding="utf-8")
    config = DistBuildConfig(
        project_root=tmp_path,
        spec_path=spec_path,
        dist_path=tmp_path / "dist",
        work_path=tmp_path / "build",
        clean=True,
    )
    monkeypatch.setattr("w3xtool.casclib_dist.platform.system", lambda: "Windows")

    # When/Then: even dry-run refuses an unverifiable Windows bundle.
    with pytest.raises(CascLibDistError, match="CascLib.dll"):
        run_dist_build(config, dry_run=True)


def test_casclib_provenance_and_build_script_are_pinned() -> None:
    # Given: the committed provenance and Windows build recipe.
    root = Path(__file__).resolve().parents[1]
    provenance = json.loads(
        (root / "third_party" / "CascLib" / "SOURCE_PROVENANCE.json").read_text(encoding="utf-8")
    )
    script = (root / "tools" / "build_casclib.ps1").read_text(encoding="utf-8")

    # When/Then: immutable source identity, hash, temp build, and CMake flags are exact.
    assert provenance == {
        "name": "CascLib",
        "tag": "3.0",
        "commit": "4971d363e665551ac4142f541e5f2d71f1cda653",
        "url": "https://codeload.github.com/ladislav-zezula/CascLib/tar.gz/4971d363e665551ac4142f541e5f2d71f1cda653",
        "source_sha256": "6b40739449d12f9c55b0acca7c40cba591ac0bdd10f485d58fafcb164021021e",
        "license": "MIT",
    }
    for required in (
        provenance["url"],
        provenance["source_sha256"],
        "[System.IO.Path]::GetTempPath()",
        '-A "x64"',
        "-DCASC_UNICODE=ON",
        "-DCASC_BUILD_SHARED_LIB=ON",
        "-DCASC_BUILD_STATIC_LIB=OFF",
        "-DCASC_BUILD_TESTS=OFF",
        "-DCMAKE_POLICY_VERSION_MINIMUM=3.5",
        "CascLib.dll.sha256",
    ):
        assert required in script


def test_spec_adds_casclib_only_on_windows() -> None:
    # Given: the repository PyInstaller spec.
    spec = (Path(__file__).resolve().parents[1] / f"{APP_NAME}.spec").read_text(encoding="utf-8")

    # When/Then: DLL and license additions are guarded by the Windows platform.
    assert "if sys.platform == 'win32':" in spec
    assert "validate_casclib_dist_assets(spec_root, system='Windows')" in spec
    assert "CascLib.dll" in spec
    assert "third_party/CascLib/LICENSE" in spec
