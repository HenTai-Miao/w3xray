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
    assert "w3xtool/batch_description_cache.py" not in paths
    assert "w3xtool/description_cache_batch.py" not in paths


def test_quality_gate_covers_audit_gap_core_modules() -> None:
    # Given
    expected_paths = {
        "tests/test_gui_item_relations.py",
        "tests/test_item_relation_resilience.py",
        "tests/test_item_relation_models.py",
        "tests/test_batch_map_retirement.py",
        "tests/test_batch_map_retirement_safety.py",
        "tests/test_campaign_shared_object_identity.py",
        "tests/test_object_candidate_collection.py",
        "tests/test_object_candidate_merge.py",
        "tests/test_object_pipeline.py",
        "tests/test_object_pipeline_priority.py",
        "tests/test_object_text_pipeline.py",
        "tests/test_object_text_roles.py",
        "tests/test_object_text_sources.py",
        "tests/test_posix_package_assets.py",
        "tests/test_release_metadata.py",
        "tests/test_windows_acceptance_assets.py",
        "tests/test_windows_real_install_workflow.py",
        "w3xtool/__init__.py",
        "w3xtool/gui_item_relation_layout.py",
        "w3xtool/gui_item_relations.py",
        "w3xtool/item_relation_builder.py",
        "w3xtool/item_relation_endpoints.py",
        "w3xtool/item_relation_fields.py",
        "w3xtool/item_relation_field_variants.py",
        "w3xtool/item_relation_models.py",
        "w3xtool/item_relation_presentation.py",
        "w3xtool/item_relation_scripts.py",
        "w3xtool/map_components.py",
        "w3xtool/map_data.py",
        "w3xtool/object_candidate_values.py",
        "w3xtool/object_candidates.py",
        "w3xtool/object_candidate_models.py",
        "w3xtool/object_candidate_text_tables.py",
        "w3xtool/object_field_selection.py",
        "w3xtool/object_materialization.py",
        "w3xtool/object_pipeline.py",
        "w3xtool/object_text_categories.py",
        "w3xtool/object_text_evidence.py",
        "w3xtool/object_text_index.py",
        "w3xtool/object_text_roles.py",
        "w3xtool/object_text_sources.py",
        "w3xtool/object_text_records.py",
        "w3xtool/batch_map_retirement.py",
        "w3xtool/batch_output_lock.py",
        "w3xtool/batch_retirement_quarantine.py",
        "w3xtool/campaign_child_loader.py",
        "w3xtool/map_loader.py",
    }

    # When
    commands = quality_gate.build_quality_commands(python_executable="python")

    # Then
    assert all(expected_paths.issubset(command.argv) for command in commands)


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
