"""Shared mechanics for owned description-cache publication tests."""

from __future__ import annotations

from pathlib import Path

from tests.description_cache_migration_fixture import (
    candidate,
    legacy_client_fill,
    write_legacy_inputs,
)
from w3xtool.atomic_rename import rename_noreplace


def replacement_inputs(root: Path, raw: str) -> tuple[Path, Path]:
    """Build independently proven replacement evidence."""
    return write_legacy_inputs(
        root / "replacement",
        cache_rows=(candidate(raw=raw),),
        report_rows=(
            legacy_client_fill(
                raw_description=raw,
                readable_description=raw,
            ),
        ),
    )


def rename_in_parent(
    parent_descriptor: int,
    source_name: str,
    destination_name: str,
) -> None:
    """Apply the production no-replace primitive within one held parent."""
    rename_noreplace(
        parent_descriptor,
        source_name,
        parent_descriptor,
        destination_name,
    )


def private_publication_paths(output: Path) -> tuple[Path, ...]:
    """Return stage and backup paths still adjacent to one output."""
    patterns = (
        ".w3xray-description-cache-stage-*",
        ".w3xray-description-cache-backup-*",
    )
    return tuple(path for pattern in patterns for path in output.parent.glob(pattern))


__all__ = ("private_publication_paths", "rename_in_parent", "replacement_inputs")
