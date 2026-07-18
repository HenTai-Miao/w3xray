"""Release metadata and user-facing package guidance stay synchronized."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Final

from w3xtool import __version__


_ROOT: Final = Path(__file__).resolve().parents[1]
_RELEASE_VERSION: Final = "0.1.4"


def test_release_version_matches_project_runtime_and_lockfile() -> None:
    # Given: the project manifest and generated lockfile for the intended release.
    project = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((_ROOT / "uv.lock").read_text(encoding="utf-8"))

    # When: the editable project package and public runtime version are inspected.
    locked_versions = [
        package["version"]
        for package in lock["package"]
        if package["name"] == "w3xray" and package["source"] == {"editable": "."}
    ]

    # Then: every authoritative version source identifies the same release.
    assert project["project"]["version"] == _RELEASE_VERSION
    assert __version__ == _RELEASE_VERSION
    assert locked_versions == [_RELEASE_VERSION]


def test_readme_describes_windows_package_tradeoffs() -> None:
    # Given: the user-facing Windows release documentation.
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    release_section = readme.split("## 开发运行（uv）", maxsplit=1)[0]

    # When/Then: both formats and their operational tradeoffs are explicit.
    assert "w3xray-v0.1.4-windows-x64.zip" in release_section
    assert "w3xray-v0.1.4-windows-x64.exe" in release_section
    assert "功能相同" in release_section
    assert "启动更快" in release_section
    assert "更容易诊断" in release_section
    assert "杀软误报" in release_section
    assert "启动问题" in release_section
    assert "优先使用 ZIP" in release_section
    assert "临时目录" in release_section
    assert "启动较慢" in release_section
    assert "未做代码签名" in release_section
    assert "SmartScreen" in release_section


def test_readme_documents_both_developer_build_modes() -> None:
    # Given: the developer packaging documentation.
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")

    # When/Then: the default onedir and explicit onefile commands are visible.
    assert "\nuv run w3xray-dist\n" in readme
    assert "\nuv run w3xray-dist --onefile\n" in readme


def test_readme_points_to_both_windows_acceptance_reports() -> None:
    # Given: the real-Windows acceptance documentation.
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")

    # When/Then: the timestamped evidence root and both relative reports are visible.
    assert "w3xray-acceptance-" in readme
    assert "windows-onedir/acceptance.json" in readme
    assert "windows-onefile/acceptance.json" in readme
