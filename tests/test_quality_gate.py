"""Cross-platform changed-path quality command contracts."""

from __future__ import annotations

import subprocess
from pathlib import Path
import tomllib

import pytest

from w3xtool import quality_gate


_ROOT = Path(__file__).resolve().parents[1]


def test_quality_gate_builds_all_three_cross_platform_commands() -> None:
    # Given / When
    commands = quality_gate.build_quality_commands(python_executable="python")

    # Then
    assert [command.tool for command in commands] == [
        "ruff-check",
        "ruff-format",
        "basedpyright",
    ]
    assert all("w3xtool/batch_manifest_io.py" in command.argv for command in commands)
    assert all("w3xtool/quality_gate.py" in command.argv for command in commands)
    assert all("tests/test_batch_soak.py" in command.argv for command in commands)
    assert all(
        command.argv[:3] == ("python", "-m", command.module) for command in commands
    )
    assert all("shell=True" not in command.argv for command in commands)


def test_quality_gate_paths_are_one_unique_immutable_set() -> None:
    # Given / When
    paths = quality_gate.STRICT_PATHS

    # Then
    assert isinstance(paths, tuple)
    assert len(paths) == len(set(paths))
    assert paths == tuple(sorted(paths))


def test_quality_gate_stops_on_first_nonzero_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    calls: list[tuple[str, ...]] = []

    def run(
        argv: tuple[str, ...],
        *,
        check: bool,
        shell: bool,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        assert not check
        assert not shell
        return subprocess.CompletedProcess(argv, 0 if len(calls) == 1 else 9)

    monkeypatch.setattr(quality_gate.subprocess, "run", run)
    commands = quality_gate.build_quality_commands(python_executable="python")

    # When
    code = quality_gate.run_quality_commands(commands)

    # Then
    assert code == 9
    assert calls == [commands[0].argv, commands[1].argv]


def test_project_registers_quality_script_and_development_tools() -> None:
    # Given / When
    with (_ROOT / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)

    # Then
    assert project["project"]["scripts"]["w3xray-quality"] == (
        "w3xtool.quality_gate:main"
    )
    dev = tuple(project["dependency-groups"]["dev"])
    assert any(item.startswith("ruff>=") for item in dev)
    assert any(item.startswith("basedpyright>=") for item in dev)


def test_all_packaging_lanes_run_quality_after_sync_and_before_tests() -> None:
    # Given
    paths = (
        _ROOT / ".github" / "workflows" / "posix-package.yml",
        _ROOT / ".github" / "workflows" / "windows-package.yml",
        _ROOT / "tools" / "run_windows_acceptance.ps1",
    )

    # When / Then
    for path in paths:
        text = path.read_text(encoding="utf-8")
        sync_at = text.index("uv sync --dev")
        quality_at = text.index("uv run w3xray-quality")
        tests_at = text.index("uv run w3xray-test")
        assert sync_at < quality_at < tests_at, path
