"""Release metadata and user-facing package guidance stay synchronized."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Final

from w3xtool import __version__


_ROOT: Final = Path(__file__).resolve().parents[1]
_RELEASE_VERSION: Final = "0.1.1"


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


def test_readme_describes_both_release_packages_and_build_modes() -> None:
    # Given: the user and developer packaging documentation.
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")

    # When/Then: both release assets, their caveats, and both build modes are visible.
    assert "w3xray-v0.1.1-windows-x64.zip" in readme
    assert "w3xray-v0.1.1-windows-x64.exe" in readme
    assert "SmartScreen" in readme
    assert "\nuv run w3xray-dist\n" in readme
    assert "\nuv run w3xray-dist --onefile\n" in readme
