"""Clean-interpreter import-cycle proof for cache publication."""

from __future__ import annotations

import subprocess
import sys
from typing import Final

import pytest


_MODULES: Final[tuple[str, ...]] = (
    "gametool.atomic_rename",
    "gametool.description_cache_owned_schema",
    "gametool.trusted_description_cache_models",
    "gametool.trusted_description_cache_io",
    "gametool.trusted_description_cache_generation_io",
    "gametool.description_cache_publication_fs",
    "gametool.description_cache_publication_models",
    "gametool.description_cache_publication_errors",
    "gametool.description_cache_publication_retention_names",
    "gametool.description_cache_publication_retention_recovery",
    "gametool.description_cache_publication_retention_installed",
    "gametool.description_cache_publication_retention",
    "gametool.description_cache_publication_parent_identity",
    "gametool.description_cache_publication_named_leaf",
    "gametool.description_cache_publication_evidence",
    "gametool.description_cache_publication_retention_durability",
    "gametool.description_cache_publication_descriptor_close",
    "gametool.description_cache_publication_stage_identity",
    "gametool.description_cache_publication_stage_normalization",
    "gametool.description_cache_publication_stage",
    "gametool.description_cache_publication_private_attempt",
    "gametool.description_cache_publication_backup_finalization",
    "gametool.description_cache_publication_stage_location_scan",
    "gametool.description_cache_publication_stage_location",
    "gametool.description_cache_publication_stage_retention",
    "gametool.description_cache_publication_stage_finalization",
    "gametool.description_cache_publication_stage_io",
    "gametool.description_cache_publication_build",
    "gametool.description_cache_publication_rollback_selection",
    "gametool.description_cache_publication_recovery_state",
    "gametool.description_cache_publication_generation_evidence",
    "gametool.description_cache_publication_result_evidence",
    "gametool.description_cache_publication_parent",
    "gametool.description_cache_publication_recovery",
    "gametool.description_cache_publication_commit",
    "gametool.description_cache_publication_replacement_restore",
    "gametool.description_cache_publication_rollback_handoff",
    "gametool.description_cache_publication_replacement",
    "gametool.description_cache_publication_absent",
    "gametool.description_cache_publication_transaction",
    "gametool.description_cache_publication_failure",
    "gametool.description_cache_publication",
    "gametool.description_cache_migration_models",
    "gametool.description_cache_migration",
    "gametool.description_cache_cli",
    "gametool.trusted_description_cache",
)


@pytest.mark.parametrize(
    "modules",
    (_MODULES, tuple(reversed(_MODULES))),
)
def test_publication_modules_import_in_clean_interpreter(
    modules: tuple[str, ...],
) -> None:
    code = "\n".join(f"import {module}" for module in modules)

    completed = subprocess.run(
        (sys.executable, "-c", code),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
