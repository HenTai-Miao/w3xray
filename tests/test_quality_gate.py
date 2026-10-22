"""Cross-platform changed-path quality command contracts."""

from __future__ import annotations

import subprocess
from pathlib import Path
import tomllib

import pytest

from tests.quality_audit_gap_paths import AUDIT_GAP_REQUIRED_PATHS
from gametool import quality_gate


_ROOT = Path(__file__).resolve().parents[1]


def test_quality_gate_builds_all_three_cross_platform_commands() -> None:
    # Given / When
    commands = quality_gate.build_quality_commands(python_executable="python")

    # Then
    assert [command.tool for command in commands] == [
        "ruff-check",
        "ruff-format",
        "basedpyright",
        "syntax-warnings",
    ]
    assert all("gametool/batch_manifest_io.py" in command.argv for command in commands)
    assert all("gametool/quality_gate.py" in command.argv for command in commands)
    assert all("gametool/quality_test_paths.py" in command.argv for command in commands)
    assert all("gametool/quality_tool_paths.py" in command.argv for command in commands)
    assert all("tests/test_batch_soak.py" in command.argv for command in commands)
    assert all(
        "tests/test_batch_execution_windows_pipe.py" in command.argv
        for command in commands
    )
    assert all(
        command.argv[:3] == ("python", "-m", command.module) for command in commands
    )
    assert all("shell=True" not in command.argv for command in commands)


def test_quality_gate_disables_broken_github_annotations_for_basedpyright(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: GitHub Actions enables basedpyright's incompatible annotation reporter.
    captured: list[tuple[str | None, str | None]] = []

    def run(
        argv: tuple[str, ...],
        *,
        check: bool,
        shell: bool,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        assert not check
        assert not shell
        captured.append(
            (
                None if env is None else env.get("GITHUB_ACTIONS"),
                None
                if env is None
                else env.get("PYRIGHT_DISABLE_GITHUB_ACTIONS_OUTPUT"),
            )
        )
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(quality_gate.subprocess, "run", run)
    basedpyright = quality_gate.build_quality_commands(python_executable="python")[-1]

    # When: the project runs its basedpyright command.
    code = quality_gate.run_quality_commands((basedpyright,))

    # Then: ordinary CI context is preserved while the broken reporter is disabled.
    assert code == 0
    assert captured == [("true", "1")]


def test_quality_gate_paths_are_one_unique_immutable_set() -> None:
    # Given / When
    paths = quality_gate.STRICT_PATHS

    # Then
    assert isinstance(paths, tuple)
    assert len(paths) == len(set(paths))
    assert paths == tuple(sorted(paths))
    assert "gametool/batch_description_cache.py" not in paths
    assert "gametool/description_cache_batch.py" not in paths


def test_quality_gate_covers_audit_gap_core_modules() -> None:
    # Given
    expected_paths = {
        *AUDIT_GAP_REQUIRED_PATHS,
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
        "tests/test_windows_acceptance_support.py",
        "tests/test_windows_real_install_workflow.py",
        "gametool/__init__.py",
        "gametool/gui_item_relation_layout.py",
        "gametool/gui_item_relations.py",
        "gametool/item_relation_builder.py",
        "gametool/item_relation_endpoints.py",
        "gametool/item_relation_fields.py",
        "gametool/item_relation_field_variants.py",
        "gametool/item_relation_models.py",
        "gametool/item_relation_presentation.py",
        "gametool/item_relation_scripts.py",
        "gametool/map_components.py",
        "gametool/map_data.py",
        "gametool/object_candidate_values.py",
        "gametool/object_candidates.py",
        "gametool/object_candidate_models.py",
        "gametool/object_candidate_text_tables.py",
        "gametool/object_field_selection.py",
        "gametool/object_materialization.py",
        "gametool/object_pipeline.py",
        "gametool/object_text_categories.py",
        "gametool/object_text_evidence.py",
        "gametool/object_text_index.py",
        "gametool/object_text_roles.py",
        "gametool/object_text_sources.py",
        "gametool/object_text_records.py",
        "gametool/batch_map_retirement.py",
        "gametool/batch_output_lock.py",
        "gametool/batch_retirement_quarantine.py",
        "gametool/campaign_child_loader.py",
        "gametool/map_loader.py",
    }

    # When
    commands = quality_gate.build_quality_commands(python_executable="python")

    # Then
    assert all(expected_paths.issubset(command.argv) for command in commands)


def test_both_quality_authorities_cover_safe_output_callers_and_races() -> None:
    required = {
        "tests/test_safe_output_races.py",
        "gametool/safe_output_anchored.py",
        "gametool/safe_output_staging.py",
    }

    assert required.issubset(AUDIT_GAP_REQUIRED_PATHS)
    assert required.issubset(quality_gate.STRICT_PATHS)


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
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        assert not check
        assert not shell
        assert env["PYRIGHT_DISABLE_GITHUB_ACTIONS_OUTPUT"] == "1"
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
    assert project["project"]["scripts"]["gamexray-quality"] == (
        "gametool.quality_gate:main"
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
        quality_at = text.index("uv run gamexray-quality")
        tests_at = text.index("uv run gamexray-test")
        assert sync_at < quality_at < tests_at, path
