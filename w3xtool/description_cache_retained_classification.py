"""Closed role-by-kind classification for one retained sibling artifact."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final, assert_never

from .description_cache_owned_schema import TRUSTED_DESCRIPTION_CACHE_OWNED_INVENTORY
from .description_cache_publication_models import RetainedCacheRole
from .description_cache_retained_binding import BoundActiveCache
from .description_cache_retained_file_proof import prove_retained_regular_file
from .description_cache_retained_integrity_models import (
    CacheArtifactKind,
    DescriptionCacheRetentionError,
    RetainedArtifactValidation,
    RetainedDescriptionCacheArtifact,
    RetainedTreeProof,
    SiblingState,
    TreeProofStatus,
)
from .description_cache_retained_previous import classify_retained_previous
from .description_cache_retained_siblings import stat_sibling
from .description_cache_retained_tree import prove_retained_directory
from .description_cache_retained_tree_snapshot import RetainedScanBounds


_DIRECTORY_FLAGS: Final = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)


def inspect_retained_artifact(
    bound: BoundActiveCache,
    state: SiblingState,
    transaction_id: str,
    role: RetainedCacheRole,
    bounds: RetainedScanBounds,
) -> RetainedDescriptionCacheArtifact:
    """Apply the exact closed role-by-no-follow-kind classification table."""
    path = bound.root.parent / state.name
    match state.kind:
        case CacheArtifactKind.UNKNOWN:
            return _row(
                path, transaction_id, role, state, RetainedArtifactValidation.UNREADABLE
            )
        case CacheArtifactKind.SYMLINK | CacheArtifactKind.SPECIAL:
            return _row(
                path,
                transaction_id,
                role,
                state,
                RetainedArtifactValidation.UNSAFE_OBJECT,
            )
        case CacheArtifactKind.REGULAR_FILE:
            if role is RetainedCacheRole.PREVIOUS:
                return _row(
                    path,
                    transaction_id,
                    role,
                    state,
                    RetainedArtifactValidation.UNSAFE_OBJECT,
                )
            proof = prove_retained_regular_file(
                bound.parent_descriptor,
                state.name,
                state,
                bounds,
            )
        case CacheArtifactKind.DIRECTORY:
            proof = _prove_directory(bound, state, role, bounds)
        case unreachable:
            assert_never(unreachable)
    _require_current(bound.parent_descriptor, state)
    return _classify_proof(path, transaction_id, role, state, proof)


def _prove_directory(
    bound: BoundActiveCache,
    state: SiblingState,
    role: RetainedCacheRole,
    bounds: RetainedScanBounds,
) -> RetainedTreeProof:
    _require_current(bound.parent_descriptor, state)
    try:
        descriptor = os.open(
            state.name,
            _DIRECTORY_FLAGS,
            dir_fd=bound.parent_descriptor,
        )
    except OSError:
        return RetainedTreeProof(
            TreeProofStatus.UNREADABLE, (), None, None, None, None, None
        )
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (state.device, state.inode):
            raise DescriptionCacheRetentionError("retained sibling identity changed")
        capture = (
            frozenset(TRUSTED_DESCRIPTION_CACHE_OWNED_INVENTORY)
            if role is RetainedCacheRole.PREVIOUS
            else frozenset()
        )
        return prove_retained_directory(descriptor, bounds, capture)
    finally:
        os.close(descriptor)


def _classify_proof(
    path: Path,
    transaction_id: str,
    role: RetainedCacheRole,
    state: SiblingState,
    proof: RetainedTreeProof,
) -> RetainedDescriptionCacheArtifact:
    match proof.status:
        case TreeProofStatus.COMPLETE:
            if role is RetainedCacheRole.PREVIOUS:
                validation, problem = classify_retained_previous(path, proof)
            else:
                validation = RetainedArtifactValidation.PARTIAL_EVIDENCE
                problem = None
            return RetainedDescriptionCacheArtifact(
                path,
                transaction_id,
                role,
                state.kind,
                state.device,
                state.inode,
                validation,
                proof.size,
                proof.file_count,
                proof.entry_count,
                proof.sha256,
                problem,
            )
        case TreeProofStatus.UNSAFE:
            validation = (
                RetainedArtifactValidation.INVALID_PREVIOUS
                if role is RetainedCacheRole.PREVIOUS
                else RetainedArtifactValidation.UNSAFE_OBJECT
            )
        case TreeProofStatus.OVERSIZED:
            validation = RetainedArtifactValidation.OVERSIZED
        case TreeProofStatus.UNSTABLE:
            validation = RetainedArtifactValidation.UNSTABLE
        case TreeProofStatus.UNREADABLE:
            validation = RetainedArtifactValidation.UNREADABLE
        case unreachable:
            assert_never(unreachable)
    return _row(
        path,
        transaction_id,
        role,
        state,
        validation,
        proof.problem_path,
    )


def _row(
    path: Path,
    transaction_id: str,
    role: RetainedCacheRole,
    state: SiblingState,
    validation: RetainedArtifactValidation,
    problem: str | None = None,
) -> RetainedDescriptionCacheArtifact:
    return RetainedDescriptionCacheArtifact(
        path,
        transaction_id,
        role,
        state.kind,
        state.device,
        state.inode,
        validation,
        problem_path=problem,
    )


def _require_current(parent_descriptor: int, expected: SiblingState) -> None:
    try:
        current = stat_sibling(parent_descriptor, expected.name)
    except OSError as exc:
        raise DescriptionCacheRetentionError(
            "retained sibling identity became unavailable"
        ) from exc
    current_state = (
        current.st_dev,
        current.st_ino,
        current.st_size,
        current.st_mtime_ns,
        current.st_ctime_ns,
        current.st_mode,
    )
    expected_state = (
        expected.device,
        expected.inode,
        expected.size,
        expected.mtime_ns,
        expected.ctime_ns,
        expected.mode,
    )
    if current_state != expected_state:
        raise DescriptionCacheRetentionError("retained sibling identity changed")


__all__ = ("inspect_retained_artifact",)
