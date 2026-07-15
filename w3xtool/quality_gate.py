"""Cross-platform static quality gate for the maintained changed-path set."""

from __future__ import annotations

from dataclasses import dataclass
import shlex
import subprocess
import sys
from typing import Final


STRICT_PATHS: Final = tuple(
    """main.py
tests/batch_publication_fixture.py
tests/gui_worker_fakes.py
tests/test_acceptance_runner.py
tests/test_batch_cli.py
tests/test_batch_dependencies.py
tests/test_batch_description_cache.py
tests/test_batch_execution.py
tests/test_batch_global_publication.py
tests/test_batch_manifest.py
tests/test_batch_map_processing.py
tests/test_batch_publication_recovery.py
tests/test_batch_resume.py
tests/test_batch_resume_loading.py
tests/test_batch_resume_runner.py
tests/test_batch_runner.py
tests/test_batch_runtime.py
tests/test_batch_runtime_runner.py
tests/test_batch_soak.py
tests/test_batch_state_reports.py
tests/test_description_cache.py
tests/test_description_cache_manifest_binding.py
tests/test_durable_io.py
tests/test_external_listfile_gui.py
tests/test_gui_casc_browser.py
tests/test_gui_casc_worker.py
tests/test_gui_current_map.py
tests/test_gui_current_map_lifecycle.py
tests/test_gui_description_cache.py
tests/test_gui_export_safety.py
tests/test_gui_export_worker.py
tests/test_gui_external_data_worker.py
tests/test_gui_loader_runner.py
tests/test_gui_object_filter_runner.py
tests/test_gui_source_browser_worker.py
tests/test_gui_worker_host.py
tests/test_gui_worker_registry.py
tests/test_map_relation_loading.py
tests/test_object_text_index.py
tests/test_quality_gate.py
tests/test_real_map_item_relation_acceptance.py
tests/test_reference_id_reports.py
w3xtool/acceptance_batch.py
w3xtool/acceptance_runner.py
w3xtool/batch_checkpoint_publication.py
w3xtool/batch_cli.py
w3xtool/batch_configuration.py
w3xtool/batch_dependencies.py
w3xtool/batch_description_cache.py
w3xtool/batch_execution.py
w3xtool/batch_execution_messages.py
w3xtool/batch_execution_models.py
w3xtool/batch_execution_request.py
w3xtool/batch_global_io.py
w3xtool/batch_global_models.py
w3xtool/batch_global_publication.py
w3xtool/batch_global_validation.py
w3xtool/batch_manifest_io.py
w3xtool/batch_manifest_models.py
w3xtool/batch_manifest_validation.py
w3xtool/batch_map_attempt.py
w3xtool/batch_map_manifest.py
w3xtool/batch_map_processing.py
w3xtool/batch_map_publication.py
w3xtool/batch_map_result.py
w3xtool/batch_models.py
w3xtool/batch_observability.py
w3xtool/batch_publication_models.py
w3xtool/batch_publication_record.py
w3xtool/batch_publication_recovery.py
w3xtool/batch_publication_resolution.py
w3xtool/batch_report_validation.py
w3xtool/batch_reports.py
w3xtool/batch_resume.py
w3xtool/batch_runner.py
w3xtool/batch_runtime.py
w3xtool/batch_state_io.py
w3xtool/batch_state_parser.py
w3xtool/description_cache.py
w3xtool/description_cache_batch.py
w3xtool/description_cache_models.py
w3xtool/description_cache_schema.py
w3xtool/durable_io.py
w3xtool/gui.py
w3xtool/gui_casc_browser.py
w3xtool/gui_current_map.py
w3xtool/gui_current_map_worker.py
w3xtool/gui_export_actions.py
w3xtool/gui_external_data.py
w3xtool/gui_lifecycle.py
w3xtool/gui_loader_host.py
w3xtool/gui_loader_runner.py
w3xtool/gui_object_filter_runner.py
w3xtool/gui_source_browser.py
w3xtool/gui_worker_host.py
w3xtool/gui_worker_registry.py
w3xtool/item_relation_exports.py
w3xtool/object_text_exports.py
w3xtool/quality_gate.py
w3xtool/safe_output.py
w3xtool/safe_output_chunk_writer.py
w3xtool/safe_output_path_publication.py
w3xtool/safe_output_publication.py""".splitlines()
)


@dataclass(frozen=True, slots=True)
class QualityCommand:
    """One labeled module command executed without a shell."""

    tool: str
    module: str
    argv: tuple[str, ...]


def build_quality_commands(
    *,
    python_executable: str = sys.executable,
) -> tuple[QualityCommand, ...]:
    """Build the three commands from one immutable path authority."""
    return (
        QualityCommand(
            "ruff-check",
            "ruff",
            (python_executable, "-m", "ruff", "check", *STRICT_PATHS),
        ),
        QualityCommand(
            "ruff-format",
            "ruff",
            (python_executable, "-m", "ruff", "format", "--check", *STRICT_PATHS),
        ),
        QualityCommand(
            "basedpyright",
            "basedpyright",
            (
                python_executable,
                "-m",
                "basedpyright",
                "--level",
                "error",
                *STRICT_PATHS,
            ),
        ),
    )


def run_quality_commands(commands: tuple[QualityCommand, ...]) -> int:
    """Echo and execute commands, stopping at the first failure."""
    for command in commands:
        print(f"[{command.tool}] {shlex.join(command.argv)}", flush=True)
        result = subprocess.run(command.argv, check=False, shell=False)
        if result.returncode:
            return result.returncode
    return 0


def main() -> int:
    """Run the maintained quality gate in the active Python environment."""
    return run_quality_commands(build_quality_commands())


if __name__ == "__main__":
    raise SystemExit(main())
