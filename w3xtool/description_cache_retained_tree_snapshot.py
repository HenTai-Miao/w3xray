"""Descriptor-relative bounded metadata snapshots for retained trees."""

from __future__ import annotations

from dataclasses import dataclass
import os
import stat
from typing import Final, assert_never

from .description_cache_retained_integrity_models import (
    CacheArtifactKind,
    TreeEntryState,
    TreeProofStatus,
)
from .description_cache_retained_siblings import kind_from_mode


_DIRECTORY_FLAGS: Final = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)


@dataclass(frozen=True, slots=True)
class RetainedScanBounds:
    """Exact byte, count, and depth bounds supplied by the orchestrator."""

    file_bytes: int
    tree_bytes: int
    file_count: int
    entry_count: int
    depth: int


@dataclass(frozen=True, slots=True)
class TreeSnapshot:
    """One before/after metadata-only tree proof."""

    status: TreeProofStatus
    entries: tuple[TreeEntryState, ...]
    size: int | None
    file_count: int | None
    entry_count: int | None
    problem_path: str | None


class _Accumulator:
    """Mutable state whose sole purpose is one bounded depth-first traversal."""

    __slots__ = (
        "entries",
        "entry_count",
        "file_count",
        "problem_path",
        "size",
        "status",
    )

    entries: list[TreeEntryState]
    size: int
    file_count: int
    entry_count: int
    status: TreeProofStatus
    problem_path: str | None

    def __init__(self) -> None:
        self.entries = []
        self.size = 0
        self.file_count = 0
        self.entry_count = 0
        self.status = TreeProofStatus.COMPLETE
        self.problem_path = None


def snapshot_retained_tree(
    root_descriptor: int,
    bounds: RetainedScanBounds,
) -> TreeSnapshot:
    """Snapshot every no-follow entry, stopping exactly at the first bound."""
    try:
        root_before = os.fstat(root_descriptor)
    except OSError:
        return _failed_snapshot(TreeProofStatus.UNREADABLE, None)
    if not stat.S_ISDIR(root_before.st_mode):
        return _failed_snapshot(TreeProofStatus.UNSTABLE, None)
    accumulator = _Accumulator()
    _visit_directory(root_descriptor, "", 0, bounds, accumulator)
    try:
        root_after = os.fstat(root_descriptor)
    except OSError:
        return _failed_snapshot(TreeProofStatus.UNREADABLE, None)
    if _stable_stat(root_before) != _stable_stat(root_after):
        accumulator.status = TreeProofStatus.UNSTABLE
        accumulator.problem_path = None
    if accumulator.status is not TreeProofStatus.COMPLETE:
        return TreeSnapshot(
            accumulator.status,
            tuple(accumulator.entries),
            None,
            None,
            None,
            accumulator.problem_path,
        )
    return TreeSnapshot(
        TreeProofStatus.COMPLETE,
        tuple(accumulator.entries),
        accumulator.size,
        accumulator.file_count,
        accumulator.entry_count,
        None,
    )


def _visit_directory(
    descriptor: int,
    prefix: str,
    depth: int,
    bounds: RetainedScanBounds,
    accumulator: _Accumulator,
) -> None:
    if accumulator.status in {
        TreeProofStatus.OVERSIZED,
        TreeProofStatus.UNSTABLE,
        TreeProofStatus.UNREADABLE,
    }:
        return
    try:
        names = tuple(
            sorted(os.listdir(descriptor), key=lambda name: name.encode("utf-8"))
        )
    except UnicodeError:
        _fail(accumulator, TreeProofStatus.UNREADABLE, None)
        return
    except OSError:
        _fail(accumulator, TreeProofStatus.UNREADABLE, prefix or None)
        return
    for name in names:
        relative = name if not prefix else f"{prefix}/{name}"
        child_depth = depth + 1
        if child_depth > bounds.depth:
            _fail(accumulator, TreeProofStatus.OVERSIZED, relative)
            return
        accumulator.entry_count += 1
        if accumulator.entry_count > bounds.entry_count:
            _fail(accumulator, TreeProofStatus.OVERSIZED, relative)
            return
        try:
            details = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        except FileNotFoundError:
            continue
        except OSError:
            accumulator.entries.append(_unknown_entry(relative))
            _fail(accumulator, TreeProofStatus.UNREADABLE, relative)
            return
        kind = kind_from_mode(details.st_mode)
        accumulator.entries.append(_tree_entry(relative, kind, details))
        match kind:
            case CacheArtifactKind.REGULAR_FILE:
                accumulator.file_count += 1
                accumulator.size += details.st_size
                if (
                    details.st_size > bounds.file_bytes
                    or accumulator.size > bounds.tree_bytes
                    or accumulator.file_count > bounds.file_count
                ):
                    _fail(accumulator, TreeProofStatus.OVERSIZED, relative)
                    return
            case CacheArtifactKind.DIRECTORY:
                _visit_child_directory(
                    descriptor,
                    name,
                    relative,
                    child_depth,
                    details,
                    bounds,
                    accumulator,
                )
            case CacheArtifactKind.SYMLINK | CacheArtifactKind.SPECIAL:
                accumulator.status = TreeProofStatus.UNSAFE
                if accumulator.problem_path is None:
                    accumulator.problem_path = relative
            case CacheArtifactKind.UNKNOWN:
                _fail(accumulator, TreeProofStatus.UNREADABLE, relative)
            case unreachable:
                assert_never(unreachable)
        if accumulator.status in {
            TreeProofStatus.OVERSIZED,
            TreeProofStatus.UNSTABLE,
            TreeProofStatus.UNREADABLE,
        }:
            return


def _visit_child_directory(
    parent_descriptor: int,
    name: str,
    relative: str,
    depth: int,
    expected: os.stat_result,
    bounds: RetainedScanBounds,
    accumulator: _Accumulator,
) -> None:
    try:
        descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_descriptor)
    except OSError:
        _fail(accumulator, TreeProofStatus.UNREADABLE, relative)
        return
    try:
        opened = os.fstat(descriptor)
        if _stable_stat(opened) != _stable_stat(expected):
            _fail(accumulator, TreeProofStatus.UNSTABLE, relative)
            return
        _visit_directory(descriptor, relative, depth, bounds, accumulator)
        after = os.fstat(descriptor)
        named = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        if _stable_stat(after) != _stable_stat(expected) or _stable_stat(
            named
        ) != _stable_stat(expected):
            _fail(accumulator, TreeProofStatus.UNSTABLE, relative)
    except FileNotFoundError:
        _fail(accumulator, TreeProofStatus.UNSTABLE, relative)
    except OSError:
        _fail(accumulator, TreeProofStatus.UNREADABLE, relative)
    finally:
        os.close(descriptor)


def stable_entry_state(details: os.stat_result) -> tuple[int, int, int, int, int, int]:
    """Return the exact metadata tuple required around every payload read."""
    return _stable_stat(details)


def _stable_stat(details: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        details.st_dev,
        details.st_ino,
        details.st_size,
        details.st_mtime_ns,
        details.st_ctime_ns,
        details.st_mode,
    )


def _tree_entry(
    relative: str, kind: CacheArtifactKind, details: os.stat_result
) -> TreeEntryState:
    return TreeEntryState(
        relative,
        kind,
        details.st_dev,
        details.st_ino,
        details.st_size,
        details.st_mtime_ns,
        details.st_ctime_ns,
        details.st_mode,
    )


def _unknown_entry(relative: str) -> TreeEntryState:
    return TreeEntryState(
        relative, CacheArtifactKind.UNKNOWN, None, None, None, None, None, None
    )


def _fail(
    accumulator: _Accumulator, status: TreeProofStatus, problem_path: str | None
) -> None:
    accumulator.status = status
    accumulator.problem_path = problem_path


def _failed_snapshot(status: TreeProofStatus, problem_path: str | None) -> TreeSnapshot:
    return TreeSnapshot(status, (), None, None, None, problem_path)


__all__ = ("RetainedScanBounds", "TreeSnapshot", "snapshot_retained_tree")
