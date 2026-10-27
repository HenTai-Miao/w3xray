"""Cross-platform changed-path quality command contracts."""

from __future__ import annotations

import subprocess
from importlib.machinery import ModuleSpec
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
    monkeypatch.setattr(quality_gate, "STRICT_PATHS", ("gametool/quality_gate.py",))
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
        "retired_contract_tests/posix/test_batch_map_retirement_safety.py",
        "tests/test_campaign_shared_object_identity.py",
        "tests/test_object_candidate_collection.py",
        "tests/test_object_candidate_merge.py",
        "tests/test_object_pipeline.py",
        "tests/test_object_pipeline_priority.py",
        "tests/test_object_text_pipeline.py",
        "tests/test_object_text_roles.py",
        "tests/test_object_text_sources.py",
        "tests/test_windows_only_distribution.py",
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
        "retired_contract_tests/posix/test_safe_output_races.py",
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
    monkeypatch.setattr(quality_gate, "STRICT_PATHS", ("gametool/quality_gate.py",))
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


def test_windows_quality_batches_keep_every_path_and_quoted_unicode() -> None:
    paths = tuple(f'目录 with spaces/😀{index:04d}\\".py' for index in range(1200))
    command = quality_gate.QualityCommand(
        "check", "ruff", ("python", "-m", "ruff", "check", *paths), path_start=4
    )
    batches = quality_gate._command_batches(command, windows_units=240)
    assert len(batches) > 1
    assert tuple(path for batch in batches for path in batch[4:]) == paths
    assert all(quality_gate._windows_units(batch) <= 240 for batch in batches)


def test_windows_quality_command_unit_boundary_includes_terminator() -> None:
    command = quality_gate.QualityCommand(
        "check",
        "ruff",
        ("python", "-m", "ruff", "check", "a.py", "😀.py"),
        path_start=4,
    )
    length = quality_gate._windows_units(command.argv)
    assert quality_gate._command_batches(command, windows_units=length) == (
        command.argv,
    )
    assert len(quality_gate._command_batches(command, windows_units=length - 1)) == 2


def test_windows_quality_single_oversized_path_fails_explicitly() -> None:
    command = quality_gate.QualityCommand(
        "check",
        "ruff",
        ("python", "-m", "ruff", "check", "a" * 500 + ".py"),
        path_start=4,
    )
    with pytest.raises(ValueError, match="单个检查路径"):
        quality_gate._command_batches(command, windows_units=240)


def test_windows_quality_budget_includes_forwarded_node_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    based = tmp_path / ("long-install-" * 20) / "basedpyright" / "__init__.py"
    node = tmp_path / ("long-node-" * 20) / "nodejs_wheel" / "executable.py"

    def spec(name: str) -> ModuleSpec:
        return ModuleSpec(
            name, loader=None, origin=str(based if name == "basedpyright" else node)
        )

    monkeypatch.setattr(quality_gate.importlib.util, "find_spec", spec)
    paths = tuple(f"tests/test_{index:06d}.py" for index in range(2000))
    command = quality_gate.QualityCommand(
        "type",
        "basedpyright",
        ("python", "-m", "basedpyright", "--level", "error", *paths),
        path_start=5,
    )
    batches = quality_gate._command_batches(
        command, windows_units=quality_gate._windows_limit(command)
    )
    assert len(batches) > 1
    for batch in batches:
        forwarded = (
            str(node.parent / "node.exe"),
            str(based.parent / "index.js"),
            *batch[3:],
        )
        assert quality_gate._windows_units(batch) <= 32767
        assert quality_gate._windows_units(forwarded) <= 32767
    assert tuple(path for batch in batches for path in batch[5:]) == paths


@pytest.mark.parametrize("failure", [0, 11])
def test_quality_runner_executes_all_batches_or_stops_at_failure(
    monkeypatch: pytest.MonkeyPatch,
    failure: int,
) -> None:
    paths = tuple(f"tests/{index:05d}_" + "x" * 60 + ".py" for index in range(1200))
    command = quality_gate.QualityCommand(
        "check", "ruff", ("python", "-m", "ruff", "check", *paths), path_start=4
    )
    expected = quality_gate._command_batches(command, windows_units=32767)
    calls: list[tuple[str, ...]] = []

    def run(
        argv: tuple[str, ...], *, check: bool, shell: bool, env: dict[str, str]
    ) -> subprocess.CompletedProcess[str]:
        assert not check and not shell
        assert env["PYRIGHT_DISABLE_GITHUB_ACTIONS_OUTPUT"] == "1"
        calls.append(argv)
        return subprocess.CompletedProcess(argv, failure if len(calls) == 2 else 0)

    original = quality_gate._command_batches
    monkeypatch.setattr(
        quality_gate,
        "_command_batches",
        lambda command, **kwargs: original(command, windows_units=32767),
    )
    monkeypatch.setattr(quality_gate.subprocess, "run", run)
    assert quality_gate.run_quality_commands((command,)) == failure
    assert calls == list(expected[:2] if failure else expected)
