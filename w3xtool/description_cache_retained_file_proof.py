"""Single-open bounded regular-file proofs for retained artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from typing import Final

from .description_cache_retained_integrity_models import (
    RetainedTreeProof,
    SiblingState,
    TreeEntryState,
    TreeProofStatus,
)
from .description_cache_retained_tree_snapshot import (
    RetainedScanBounds,
    stable_entry_state,
)
from .descriptor_open_flags import directory_read_flags, file_read_flags


_READ_BYTES: Final = 1024 * 1024


@dataclass(frozen=True, slots=True)
class RetainedFileRead:
    """One exact descriptor payload digest and optional captured bytes."""

    size: int
    sha256: str
    payload: bytes | None


class RetainedFileOversized(OSError):
    """The descriptor crossed its exact content bound while reading."""


class RetainedFileUnstable(OSError):
    """A named file or ancestor changed around its descriptor read."""


def prove_retained_regular_file(
    parent_descriptor: int,
    name: str,
    expected: SiblingState,
    bounds: RetainedScanBounds,
) -> RetainedTreeProof:
    """Read one top-level regular artifact through its anchored sibling name."""
    if (
        expected.size is None
        or expected.size > bounds.file_bytes
        or expected.size > bounds.tree_bytes
        or bounds.file_count < 1
    ):
        return _failed_proof(TreeProofStatus.OVERSIZED)
    try:
        before = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        if stable_entry_state(before) != _state_from_sibling(expected):
            raise RetainedFileUnstable
        descriptor = os.open(name, file_read_flags(), dir_fd=parent_descriptor)
        try:
            opened = os.fstat(descriptor)
            if stable_entry_state(opened) != stable_entry_state(before):
                raise RetainedFileUnstable
            evidence = read_retained_file(descriptor, bounds.file_bytes, False)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        named = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        if stable_entry_state(after) != stable_entry_state(
            before
        ) or stable_entry_state(named) != stable_entry_state(before):
            raise RetainedFileUnstable
    except RetainedFileOversized:
        return _failed_proof(TreeProofStatus.OVERSIZED)
    except RetainedFileUnstable:
        return _failed_proof(TreeProofStatus.UNSTABLE)
    except OSError:
        return _failed_proof(TreeProofStatus.UNREADABLE)
    return RetainedTreeProof(
        TreeProofStatus.COMPLETE,
        (),
        evidence.size,
        1,
        0,
        evidence.sha256,
        None,
    )


def read_relative_retained_file(
    root_descriptor: int,
    expected: TreeEntryState,
    maximum: int,
    capture_payload: bool,
) -> RetainedFileRead:
    """Open one safe relative file exclusively through held directory fds."""
    parts = expected.relative_path.split("/")
    parent = os.dup(root_descriptor)
    try:
        for part in parts[:-1]:
            child = os.open(part, directory_read_flags(), dir_fd=parent)
            os.close(parent)
            parent = child
        name = parts[-1]
        before = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if stable_entry_state(before) != _state_from_entry(expected):
            raise RetainedFileUnstable
        descriptor = os.open(name, file_read_flags(), dir_fd=parent)
        try:
            opened = os.fstat(descriptor)
            if stable_entry_state(opened) != stable_entry_state(before):
                raise RetainedFileUnstable
            evidence = read_retained_file(descriptor, maximum, capture_payload)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        named = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if stable_entry_state(after) != stable_entry_state(
            before
        ) or stable_entry_state(named) != stable_entry_state(before):
            raise RetainedFileUnstable
        return evidence
    finally:
        os.close(parent)


def read_retained_file(
    descriptor: int,
    maximum: int,
    capture_payload: bool,
) -> RetainedFileRead:
    """Hash to EOF once, stopping without truncation at maximum plus one."""
    digest = hashlib.sha256()
    payload = bytearray() if capture_payload else None
    size = 0
    while True:
        chunk = os.read(descriptor, min(_READ_BYTES, maximum + 1 - size))
        if not chunk:
            break
        size += len(chunk)
        if size > maximum:
            raise RetainedFileOversized
        digest.update(chunk)
        if payload is not None:
            payload.extend(chunk)
    return RetainedFileRead(
        size,
        digest.hexdigest(),
        None if payload is None else bytes(payload),
    )


def _state_from_sibling(state: SiblingState) -> tuple[int | None, ...]:
    return (
        state.device,
        state.inode,
        state.size,
        state.mtime_ns,
        state.ctime_ns,
        state.mode,
    )


def _state_from_entry(state: TreeEntryState) -> tuple[int | None, ...]:
    return (
        state.device,
        state.inode,
        state.size,
        state.mtime_ns,
        state.ctime_ns,
        state.mode,
    )


def _failed_proof(status: TreeProofStatus) -> RetainedTreeProof:
    return RetainedTreeProof(status, (), None, None, None, None, None)


__all__ = (
    "RetainedFileOversized",
    "RetainedFileRead",
    "RetainedFileUnstable",
    "prove_retained_regular_file",
    "read_relative_retained_file",
    "read_retained_file",
)
