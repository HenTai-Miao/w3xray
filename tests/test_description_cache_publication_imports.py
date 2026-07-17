"""Clean-interpreter import-cycle proof for cache publication."""

from __future__ import annotations

import subprocess
import sys
from typing import Final

import pytest


_MODULES: Final[tuple[str, ...]] = (
    "w3xtool.atomic_rename",
    "w3xtool.description_cache_owned_schema",
    "w3xtool.trusted_description_cache_models",
    "w3xtool.trusted_description_cache_io",
    "w3xtool.trusted_description_cache_generation_io",
    "w3xtool.description_cache_publication_fs",
    "w3xtool.description_cache_publication_models",
    "w3xtool.description_cache_publication_errors",
    "w3xtool.description_cache_publication_retention_names",
    "w3xtool.description_cache_publication_retention_recovery",
    "w3xtool.description_cache_publication_retention_installed",
    "w3xtool.description_cache_publication_retention",
    "w3xtool.description_cache_publication_parent_identity",
    "w3xtool.description_cache_publication_named_leaf",
    "w3xtool.description_cache_publication_evidence",
    "w3xtool.description_cache_publication_retention_durability",
    "w3xtool.description_cache_publication_descriptor_close",
    "w3xtool.description_cache_publication_stage_identity",
    "w3xtool.description_cache_publication_stage_normalization",
    "w3xtool.description_cache_publication_stage",
    "w3xtool.description_cache_publication_private_attempt",
    "w3xtool.description_cache_publication_backup_finalization",
    "w3xtool.description_cache_publication_stage_location_scan",
    "w3xtool.description_cache_publication_stage_location",
    "w3xtool.description_cache_publication_stage_retention",
    "w3xtool.description_cache_publication_stage_finalization",
    "w3xtool.description_cache_publication_stage_io",
    "w3xtool.description_cache_publication_build",
    "w3xtool.description_cache_publication_rollback_selection",
    "w3xtool.description_cache_publication_recovery_state",
    "w3xtool.description_cache_publication_generation_evidence",
    "w3xtool.description_cache_publication_result_evidence",
    "w3xtool.description_cache_publication_parent",
    "w3xtool.description_cache_publication_recovery",
    "w3xtool.description_cache_publication_commit",
    "w3xtool.description_cache_publication_replacement_restore",
    "w3xtool.description_cache_publication_rollback_handoff",
    "w3xtool.description_cache_publication_replacement",
    "w3xtool.description_cache_publication_absent",
    "w3xtool.description_cache_publication_transaction",
    "w3xtool.description_cache_publication_failure",
    "w3xtool.description_cache_publication",
    "w3xtool.description_cache_migration_models",
    "w3xtool.description_cache_migration",
    "w3xtool.description_cache_cli",
    "w3xtool.trusted_description_cache",
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
