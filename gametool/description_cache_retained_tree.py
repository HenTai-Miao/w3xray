"""Canonical before/read/after proofs for retained directory trees."""

from __future__ import annotations

import hashlib
import json
from typing import assert_never

from .description_cache_retained_file_proof import (
    RetainedFileOversized,
    RetainedFileUnstable,
    read_relative_retained_file,
)
from .description_cache_retained_integrity_models import (
    CacheArtifactKind,
    RetainedTreeProof,
    TreeEntryState,
    TreeProofStatus,
)
from .description_cache_retained_tree_snapshot import (
    RetainedScanBounds,
    TreeSnapshot,
    snapshot_retained_tree,
)


def prove_retained_directory(
    descriptor: int,
    bounds: RetainedScanBounds,
    capture_payload_names: frozenset[str] = frozenset(),
) -> RetainedTreeProof:
    """Take before/read/after proofs for one already-held directory."""
    before = snapshot_retained_tree(descriptor, bounds)
    incomplete = _incomplete_proof(before)
    if incomplete is not None:
        return incomplete
    digests: dict[str, str] = {}
    payloads: list[tuple[str, bytes]] = []
    for entry in before.entries:
        if entry.kind is not CacheArtifactKind.REGULAR_FILE:
            continue
        capture = (
            "/" not in entry.relative_path
            and entry.relative_path in capture_payload_names
        )
        try:
            evidence = read_relative_retained_file(
                descriptor,
                entry,
                bounds.file_bytes,
                capture,
            )
        except RetainedFileOversized:
            return _failed_proof(TreeProofStatus.OVERSIZED, entry.relative_path)
        except RetainedFileUnstable:
            return _failed_proof(TreeProofStatus.UNSTABLE, entry.relative_path)
        except OSError:
            return _failed_proof(TreeProofStatus.UNREADABLE, entry.relative_path)
        digests[entry.relative_path] = evidence.sha256
        if evidence.payload is not None:
            payloads.append((entry.relative_path, evidence.payload))
    after = snapshot_retained_tree(descriptor, bounds)
    if before != after:
        return _failed_proof(
            TreeProofStatus.UNSTABLE,
            _first_tree_difference(before.entries, after.entries),
        )
    hashed_entries = tuple(
        TreeEntryState(
            entry.relative_path,
            entry.kind,
            entry.device,
            entry.inode,
            entry.size,
            entry.mtime_ns,
            entry.ctime_ns,
            entry.mode,
            digests.get(entry.relative_path),
        )
        for entry in before.entries
    )
    if before.size is None or before.file_count is None or before.entry_count is None:
        return _failed_proof(TreeProofStatus.UNSTABLE, None)
    return RetainedTreeProof(
        TreeProofStatus.COMPLETE,
        hashed_entries,
        before.size,
        before.file_count,
        before.entry_count,
        retained_tree_sha256(hashed_entries),
        None,
        tuple(payloads),
    )


def retained_tree_sha256(entries: tuple[TreeEntryState, ...]) -> str:
    """Hash canonical JSON arrays for every proven entry."""
    digest = hashlib.sha256()
    for entry in entries:
        row = (
            entry.relative_path,
            entry.kind.value,
            entry.device,
            entry.inode,
            entry.size,
            entry.mtime_ns,
            entry.ctime_ns,
            entry.mode,
            entry.file_sha256,
        )
        digest.update(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def _incomplete_proof(snapshot: TreeSnapshot) -> RetainedTreeProof | None:
    match snapshot.status:
        case TreeProofStatus.COMPLETE:
            return None
        case TreeProofStatus.UNSAFE:
            return _failed_proof(TreeProofStatus.UNSAFE, snapshot.problem_path)
        case TreeProofStatus.OVERSIZED:
            return _failed_proof(TreeProofStatus.OVERSIZED, snapshot.problem_path)
        case TreeProofStatus.UNSTABLE:
            return _failed_proof(TreeProofStatus.UNSTABLE, snapshot.problem_path)
        case TreeProofStatus.UNREADABLE:
            return _failed_proof(TreeProofStatus.UNREADABLE, snapshot.problem_path)
        case unreachable:
            assert_never(unreachable)


def _failed_proof(status: TreeProofStatus, problem: str | None) -> RetainedTreeProof:
    return RetainedTreeProof(status, (), None, None, None, None, problem)


def _first_tree_difference(
    before: tuple[TreeEntryState, ...], after: tuple[TreeEntryState, ...]
) -> str | None:
    for old, new in zip(before, after, strict=False):
        if old != new:
            return old.relative_path
    if len(before) != len(after):
        remaining = before[len(after) :] or after[len(before) :]
        return remaining[0].relative_path
    return None


__all__ = ("prove_retained_directory", "retained_tree_sha256")
