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


def requires_posix_provenance(path: Path) -> bool:
    """Return whether a test module requires held dir-fd and atomic exchange."""
    return path.stem.startswith(_POSIX_PROVENANCE_PREFIXES)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip only deliberately unsupported provenance suites on Windows."""
    if os.name != "nt":
        return
    unavailable = pytest.mark.skip(
        reason="requires POSIX dir-fd/no-follow traversal and atomic exchange"
    )
    for item in items:
        if requires_posix_provenance(Path(str(item.path))):
            item.add_marker(unavailable)
