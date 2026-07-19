"""Stable no-follow integrity snapshots and deterministic comparison."""

from __future__ import annotations

from .integrity_snapshot_io import (
    format_integrity_snapshot,
    parse_integrity_snapshot,
    tree_sha256,
)
from .integrity_snapshot_binding import (
    BoundSnapshotRoot,
    bind_snapshot_roots,
    require_snapshot_roots,
)
from .integrity_snapshot_tree import scan_bound_integrity_root
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


def build_integrity_snapshot(
    roots: tuple[SnapshotRoot, ...],
) -> IntegritySnapshot:
    """Build a stable content-plus-metadata snapshot of explicit roots."""
    with bind_snapshot_roots(roots) as bound:
        return build_bound_integrity_snapshot(bound)


def build_bound_integrity_snapshot(
    roots: tuple[BoundSnapshotRoot, ...],
) -> IntegritySnapshot:
    """Build one snapshot while the complete physical root set remains held."""
    normalized_roots: list[IntegrityRoot] = []
    require_snapshot_roots(roots)
    for item in roots:
        root, entries = scan_bound_integrity_root(item.binding)
        normalized_roots.append(
            IntegrityRoot(
                item.requested.label,
                str(root),
                entries,
                sum(entry.size for entry in entries),
                tree_sha256(entries),
            )
        )
    require_snapshot_roots(roots)
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


__all__ = (
    "INTEGRITY_SNAPSHOT_SCHEMA",
    "IntegrityDifference",
    "IntegrityDifferenceCode",
    "IntegrityEntry",
    "IntegrityRoot",
    "IntegritySnapshot",
    "IntegritySnapshotError",
    "SnapshotRoot",
    "build_bound_integrity_snapshot",
    "build_integrity_snapshot",
    "compare_integrity_snapshot",
    "format_integrity_snapshot",
    "parse_integrity_snapshot",
)
