"""Stable no-follow integrity snapshots and deterministic comparison."""

from __future__ import annotations

import os
from pathlib import Path
import stat

from .bounded_file import BoundedFileError, sha256_regular_file
from .integrity_snapshot_io import (
    format_integrity_snapshot,
    parse_integrity_snapshot,
    tree_sha256,
)
from .integrity_snapshot_models import (
    INTEGRITY_SNAPSHOT_SCHEMA,
    IntegrityDifference,
    IntegrityDifferenceCode,
    IntegrityEntry,
    IntegrityRoot,
    IntegritySnapshot,
    IntegritySnapshotError,
    SnapshotRoot,
)


type StableFileIdentity = tuple[int, int, int, int]


def build_integrity_snapshot(
    roots: tuple[SnapshotRoot, ...],
) -> IntegritySnapshot:
    """Build a stable content-plus-metadata snapshot of explicit roots."""
    if not roots:
        raise IntegritySnapshotError("at least one root is required")
    labels: set[str] = set()
    root_paths: list[Path] = []
    normalized_roots: list[IntegrityRoot] = []
    for item in roots:
        if not item.label or item.label in labels:
            raise IntegritySnapshotError("root labels must be unique and nonempty")
        labels.add(item.label)
        try:
            root = item.path.expanduser().resolve(strict=True)
        except OSError as exc:
            raise IntegritySnapshotError(f"unreadable root: {item.path}") from exc
        if item.path.expanduser().is_symlink() or not root.is_dir():
            raise IntegritySnapshotError(f"unsafe root: {item.path}")
        if any(
            root == previous
            or root.is_relative_to(previous)
            or previous.is_relative_to(root)
            for previous in root_paths
        ):
            raise IntegritySnapshotError("snapshot roots overlap")
        root_paths.append(root)
        entries = _scan_integrity_root(root)
        normalized_roots.append(
            IntegrityRoot(
                item.label,
                str(root),
                entries,
                sum(entry.size for entry in entries),
                tree_sha256(entries),
            )
        )
    return IntegritySnapshot(
        INTEGRITY_SNAPSHOT_SCHEMA,
        tuple(sorted(normalized_roots, key=lambda value: value.label)),
    )


def compare_integrity_snapshot(
    expected: IntegritySnapshot,
    actual: IntegritySnapshot,
) -> tuple[IntegrityDifference, ...]:
    """Return canonical root and file differences between two snapshots."""
    expected_by_label = {root.label: root for root in expected.roots}
    actual_by_label = {root.label: root for root in actual.roots}
    differences: list[IntegrityDifference] = []
    for label in sorted(set(expected_by_label) | set(actual_by_label)):
        old = expected_by_label.get(label)
        new = actual_by_label.get(label)
        if old is None:
            differences.append(
                IntegrityDifference(IntegrityDifferenceCode.ROOT_ADDED, label, "")
            )
            continue
        if new is None:
            differences.append(
                IntegrityDifference(IntegrityDifferenceCode.ROOT_REMOVED, label, "")
            )
            continue
        if old.path != new.path:
            differences.append(
                IntegrityDifference(
                    IntegrityDifferenceCode.ROOT_PATH_CHANGED,
                    label,
                    "",
                )
            )
        differences.extend(_compare_entries(label, old.entries, new.entries))
    return tuple(differences)


def _compare_entries(
    label: str,
    expected: tuple[IntegrityEntry, ...],
    actual: tuple[IntegrityEntry, ...],
) -> tuple[IntegrityDifference, ...]:
    old_by_path = {entry.relative_path: entry for entry in expected}
    new_by_path = {entry.relative_path: entry for entry in actual}
    result: list[IntegrityDifference] = []
    for path in sorted(
        set(old_by_path) | set(new_by_path), key=lambda value: (value.casefold(), value)
    ):
        old = old_by_path.get(path)
        new = new_by_path.get(path)
        if old is None:
            code = IntegrityDifferenceCode.FILE_ADDED
        elif new is None:
            code = IntegrityDifferenceCode.FILE_REMOVED
        elif old != new:
            code = IntegrityDifferenceCode.FILE_CHANGED
        else:
            continue
        result.append(IntegrityDifference(code, label, path))
    return tuple(result)


def _scan_integrity_root(root: Path) -> tuple[IntegrityEntry, ...]:
    try:
        root_before = root.lstat()
        entries: list[IntegrityEntry] = []
        for directory, names, files in os.walk(root, followlinks=False):
            names.sort(key=lambda value: (value.casefold(), value))
            files.sort(key=lambda value: (value.casefold(), value))
            current = Path(directory)
            for name in names:
                path = current / name
                if not stat.S_ISDIR(path.lstat().st_mode):
                    raise IntegritySnapshotError(f"unsafe snapshot object: {path}")
            for name in files:
                path = current / name
                entries.append(_snapshot_file(root, path))
        root_after = root.lstat()
    except (OSError, BoundedFileError) as exc:
        raise IntegritySnapshotError(f"cannot snapshot root {root}: {exc}") from exc
    if _stable_file_identity(root_before) != _stable_file_identity(root_after):
        raise IntegritySnapshotError(f"snapshot root changed while reading: {root}")
    return tuple(
        sorted(
            entries,
            key=lambda entry: (entry.relative_path.casefold(), entry.relative_path),
        )
    )


def _snapshot_file(root: Path, path: Path) -> IntegrityEntry:
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise IntegritySnapshotError(f"unsafe snapshot object: {path}")
    digest, opened = sha256_regular_file(path)
    after = path.lstat()
    before_identity = _stable_file_identity(before)
    if before_identity != _stable_file_identity(after) or (
        opened.device,
        opened.inode,
        opened.size,
    ) != (before.st_dev, before.st_ino, before.st_size):
        raise IntegritySnapshotError(f"snapshot file changed while reading: {path}")
    return IntegrityEntry(
        path.relative_to(root).as_posix(),
        before.st_size,
        before.st_mtime_ns,
        digest,
    )


def _stable_file_identity(details: os.stat_result) -> StableFileIdentity:
    return details.st_dev, details.st_ino, details.st_size, details.st_mtime_ns


__all__ = (
    "INTEGRITY_SNAPSHOT_SCHEMA",
    "IntegrityDifference",
    "IntegrityDifferenceCode",
    "IntegrityEntry",
    "IntegrityRoot",
    "IntegritySnapshot",
    "IntegritySnapshotError",
    "SnapshotRoot",
    "build_integrity_snapshot",
    "compare_integrity_snapshot",
    "format_integrity_snapshot",
    "parse_integrity_snapshot",
)
