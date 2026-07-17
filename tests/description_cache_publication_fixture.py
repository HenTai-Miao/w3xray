"""Shared mechanics for owned description-cache publication tests."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
import os
from pathlib import Path
from typing import Final

from tests.description_cache_migration_fixture import (
    candidate,
    legacy_client_fill,
    write_legacy_inputs,
)
from w3xtool import atomic_rename
from w3xtool.atomic_rename import rename_noreplace
from w3xtool.description_cache_publication_models import RetainedCacheRecord
from w3xtool.description_cache_publication_descriptor_close import (
    DescriptorCloseLedger,
)
from w3xtool.description_cache_publication_errors import (
    DescriptionCachePublicationError,
)
from w3xtool.description_cache_publication_stage import BoundDescriptionCacheStage


_DIRECTORY_FLAGS: Final = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)


def _identity(path: Path) -> tuple[int, int]:
    details = path.stat(follow_symlinks=False)
    return details.st_dev, details.st_ino


@contextmanager
def bound_stage(stage: Path) -> Generator[BoundDescriptionCacheStage]:
    """Hold one real parent and stage descriptor for a focused race test."""
    parent_descriptor = os.open(stage.parent, _DIRECTORY_FLAGS)
    stage_descriptor = os.open(stage, _DIRECTORY_FLAGS)
    try:
        yield BoundDescriptionCacheStage(
            parent_descriptor,
            stage_descriptor,
            stage,
            _identity(stage.parent),
            _identity(stage),
            DescriptorCloseLedger(),
        )
    finally:
        os.close(stage_descriptor)
        os.close(parent_descriptor)


@contextmanager
def open_parent(parent: Path) -> Generator[int]:
    """Hold one no-follow publication-parent descriptor."""
    descriptor = os.open(parent, _DIRECTORY_FLAGS)
    try:
        yield descriptor
    finally:
        os.close(descriptor)


def assert_failure_order(
    error: DescriptionCachePublicationError,
    expected: tuple[Exception, ...],
) -> None:
    """Require an exact failure ledger by object identity and order."""
    assert len(error.failures) == len(expected)
    assert all(
        actual is wanted
        for actual, wanted in zip(error.failures, expected, strict=True)
    )


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


def exchange_in_parent(
    parent_descriptor: int,
    source_name: str,
    destination_name: str,
) -> None:
    """Apply the production exchange primitive within one held parent."""
    atomic_rename.rename_exchange(
        parent_descriptor,
        source_name,
        parent_descriptor,
        destination_name,
    )


def transient_publication_paths(output: Path) -> tuple[Path, ...]:
    """Return transaction-private stage and backup paths."""
    patterns = (
        ".w3xray-description-cache-stage-*",
        ".w3xray-description-cache-backup-*",
    )
    return tuple(path for pattern in patterns for path in output.parent.glob(pattern))


def retained_publication_paths(output: Path) -> tuple[Path, ...]:
    """Return retained-generation sibling paths adjacent to one output."""
    return tuple(output.parent.glob(".w3xray-description-cache-retained-*-*"))


def assert_live_retained_records(
    records: tuple[RetainedCacheRecord, ...],
) -> None:
    """Require every result record to name its exact current inode."""
    for record in records:
        details = record.path.stat(follow_symlinks=False)
        assert (details.st_dev, details.st_ino) == record.identity


__all__ = (
    "bound_stage",
    "open_parent",
    "assert_failure_order",
    "exchange_in_parent",
    "rename_in_parent",
    "retained_publication_paths",
    "replacement_inputs",
    "transient_publication_paths",
    "assert_live_retained_records",
)
