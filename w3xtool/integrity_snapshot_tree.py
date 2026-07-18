"""Descriptor-relative no-follow traversal for one integrity root."""

from __future__ import annotations

import os
from pathlib import Path
import stat

from .descriptor_open_flags import directory_read_flags
from .integrity_path_binding import (
    IntegrityPathBindingError,
    bind_directory_path,
    stable_stat,
)
from .integrity_snapshot_file import IntegritySnapshotFileError, snapshot_regular_file
from .integrity_snapshot_models import IntegrityEntry, IntegritySnapshotError


def scan_integrity_root(root: Path) -> tuple[Path, tuple[IntegrityEntry, ...]]:
    """Bind and scan one explicit root solely through held descriptors."""
    try:
        with bind_directory_path(root) as bound:
            before = os.fstat(bound.descriptor)
            entries: list[IntegrityEntry] = []
            _visit_directory(bound.descriptor, bound.path, "", entries)
            after = os.fstat(bound.descriptor)
            bound.require_current()
            if stable_stat(before) != stable_stat(after):
                raise IntegritySnapshotError(
                    f"snapshot root changed while reading: {bound.path}"
                )
            return bound.path, tuple(
                sorted(
                    entries,
                    key=lambda entry: (
                        entry.relative_path.casefold(),
                        entry.relative_path,
                    ),
                )
            )
    except IntegritySnapshotError:
        raise
    except (
        IntegrityPathBindingError,
        IntegritySnapshotFileError,
        OSError,
        NotImplementedError,
    ) as exc:
        raise IntegritySnapshotError(f"cannot snapshot root {root}: {exc}") from exc


def _visit_directory(
    descriptor: int,
    root: Path,
    prefix: str,
    entries: list[IntegrityEntry],
) -> None:
    before = os.fstat(descriptor)
    if not stat.S_ISDIR(before.st_mode):
        raise IntegritySnapshotError(f"unsafe snapshot object: {root / prefix}")
    try:
        raw_names = os.listdir(descriptor)
        for name in raw_names:
            _ = name.encode("utf-8", errors="strict")
        names = tuple(
            sorted(
                raw_names,
                key=lambda value: (value.casefold(), value),
            )
        )
    except UnicodeError as exc:
        raise IntegritySnapshotError("snapshot path is not UTF-8") from exc
    for name in names:
        relative = name if not prefix else f"{prefix}/{name}"
        display = root / relative
        details = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        if stat.S_ISREG(details.st_mode):
            entries.append(
                snapshot_regular_file(descriptor, name, relative, display, details)
            )
        elif stat.S_ISDIR(details.st_mode):
            _visit_child_directory(
                descriptor,
                name,
                display,
                relative,
                details,
                root,
                entries,
            )
        else:
            raise IntegritySnapshotError(f"unsafe snapshot object: {display}")
    after = os.fstat(descriptor)
    if stable_stat(before) != stable_stat(after):
        raise IntegritySnapshotError(
            f"snapshot directory changed while reading: {root / prefix}"
        )


def _visit_child_directory(
    parent_descriptor: int,
    name: str,
    display: Path,
    relative: str,
    expected: os.stat_result,
    root: Path,
    entries: list[IntegrityEntry],
) -> None:
    descriptor = os.open(name, directory_read_flags(), dir_fd=parent_descriptor)
    try:
        opened = os.fstat(descriptor)
        expected_state = stable_stat(expected)
        if stable_stat(opened) != expected_state:
            raise IntegritySnapshotError(
                f"snapshot directory changed before reading: {display}"
            )
        _visit_directory(descriptor, root, relative, entries)
        after = os.fstat(descriptor)
        named = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        if stable_stat(after) != expected_state or stable_stat(named) != expected_state:
            raise IntegritySnapshotError(
                f"snapshot directory changed while reading: {display}"
            )
    finally:
        os.close(descriptor)


__all__ = ("scan_integrity_root",)
