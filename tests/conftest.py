"""Platform capability markers shared by the repository test suite."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


_POSIX_PROVENANCE_PREFIXES = (
    "test_batch_map_retirement",
    "test_description_cache_cli_retention",
    "test_description_cache_migration",
    "test_description_cache_publication",
    "test_description_cache_retained",
    "test_integrity_",
    "test_safe_output_cleanup_recovery",
    "test_safe_output_publication_atomicity",
    "test_safe_output_publication_cleanup_races",
)


# Only these exact original functions have independent Windows execution proof.
# New functions retain their module capability boundary until verified.
_WINDOWS_PORTABLE_PROVENANCE_TESTS: dict[str, frozenset[str]] = {
    "test_batch_map_retirement": frozenset(
        ("test_retirement_authority_rejects_legacy_partial_failed_publication",)
    ),
    "test_description_cache_migration": frozenset(
        (
            "test_legacy_headers_are_exact_when_parsing_historical_evidence",
            "test_migration_boundary_exists_when_task5_is_enabled",
            "test_migration_boundary_exposes_typed_contracts",
            "test_migration_error_propagates_through_context_manager",
        )
    ),
    "test_description_cache_publication_descriptor_close": frozenset(
        (
            "test_close_boundary_is_silent_when_every_descriptor_closes",
            "test_in_flight_typed_error_keeps_subtype_cause_and_evidence",
            "test_installed_target_subtype_is_not_collapsed_by_close_faults",
            "test_nominal_success_attempts_both_closes_and_reports_both_faults",
        )
    ),
    "test_description_cache_publication_imports": frozenset(
        ("test_publication_modules_import_in_clean_interpreter",)
    ),
    "test_description_cache_publication_low_level_faults": frozenset(
        (
            "test_initial_publication_parent_open_wrapper_ledgers_exact_fault",
            "test_stage_writer_leaf_open_wrapper_ledgers_exact_fault",
        )
    ),
    "test_description_cache_publication_named_leaf_retention": frozenset(
        ("test_read_named_leaf_classifies_exact_exception",)
    ),
    "test_description_cache_publication_parent_bound_contract": frozenset(
        ("test_parent_bound_validation_and_parent_proof_keep_both_faults",)
    ),
    "test_description_cache_publication_retention": frozenset(
        (
            "test_merge_failures_deduplicates_only_by_identity",
            "test_merge_retained_preserves_first_occurrence_order",
        )
    ),
    "test_description_cache_publication_stage_io": frozenset(
        ("test_stage_io_support_preflight_rejects_incomplete_host_without_transaction",)
    ),
    "test_description_cache_retained_integrity_bounds": frozenset(
        ("test_retained_scanner_publishes_exact_fixed_bounds",)
    ),
    "test_integrity_cli": frozenset(
        (
            "test_integrity_cli_returns_two_for_inexact_requests",
            "test_integrity_cli_returns_two_for_invalid_snapshot_payload",
            "test_main_dispatches_integrity_without_starting_gui",
        )
    ),
    "test_integrity_platform_boundaries": frozenset(
        ("test_snapshot_fails_closed_when_path_binding_capabilities_are_unavailable",)
    ),
    "test_integrity_report_history": frozenset(
        ("test_generic_safe_writer_keeps_plain_atomic_overwrite_responsibility",)
    ),
    "test_integrity_utf8_boundaries": frozenset(
        (
            "test_integrity_options_reject_surrogate_external_values",
            "test_snapshot_maps_a_surrogate_label_to_code_two",
        )
    ),
}


def requires_posix_provenance(path: Path, test_name: str | None = None) -> bool:
    """Preserve the module boundary except for exactly verified functions."""
    if not path.stem.startswith(_POSIX_PROVENANCE_PREFIXES):
        return False
    return test_name not in _WINDOWS_PORTABLE_PROVENANCE_TESTS.get(
        path.stem, frozenset()
    )


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip only deliberately unsupported provenance suites on Windows."""
    if os.name != "nt":
        return
    unavailable = pytest.mark.skip(
        reason="requires POSIX dir-fd/no-follow traversal and atomic exchange"
    )
    for item in items:
        original_name = item.originalname if isinstance(item, pytest.Function) else None
        if requires_posix_provenance(Path(str(item.path)), original_name):
            item.add_marker(unavailable)
