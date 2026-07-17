"""Recovery-role moves and two-name postcondition proof."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .description_cache_publication_errors import (
    PublicationCommitContextError,
    merge_failures,
)
from .description_cache_publication_fs import DirectoryIdentity
from .description_cache_publication_models import (
    NamedLeafProof,
    PublicationTransientRecord,
    RetainedCacheRecord,
    RetainedCacheRole,
)
from .description_cache_publication_named_leaf import read_named_leaf
from .description_cache_publication_retention_names import RetainedCacheNames


type Rename = Callable[[int, str, str], None]


def move_object_to_recovery(
    parent_descriptor: int,
    parent_identity: DirectoryIdentity,
    source: Path,
    expected: DirectoryIdentity,
    names: RetainedCacheNames,
    rename_noreplace: Rename,
) -> RetainedCacheRecord:
    """Move one exact object to recovery and prove both namespace sides."""
    recovery = names.path(RetainedCacheRole.RECOVERY)
    if source == recovery:
        current = read_named_leaf(parent_descriptor, recovery.name)
        if current.readable and current.identity == expected:
            return RetainedCacheRecord(
                recovery,
                RetainedCacheRole.RECOVERY,
                *expected,
            )
        context_error = PublicationCommitContextError(
            "existing recovery object cannot be proved; NEEDS_CONTEXT",
            transient=_named_transient(parent_identity, recovery, current, None),
            failures=current.failures,
        )
        if current.failure is not None:
            raise context_error from current.failure
        raise context_error
    source_before = read_named_leaf(parent_descriptor, source.name)
    if source_before.identity != expected:
        proof = _reprove_recovery_move(
            parent_descriptor,
            parent_identity,
            source,
            recovery,
            expected,
        )
        context_error = PublicationCommitContextError(
            "unexpected retained object changed again; NEEDS_CONTEXT",
            proof.retained,
            proof.transient,
            merge_failures(source_before.failures, proof.failures),
        )
        if source_before.failure is not None:
            raise context_error from source_before.failure
        raise context_error
    move_error: Exception | None = None
    try:
        rename_noreplace(parent_descriptor, source.name, recovery.name)
    except Exception as exc:  # noqa: BROAD_EXCEPT_OK - recovery move reproof
        move_error = exc
    proof = _reprove_recovery_move(
        parent_descriptor,
        parent_identity,
        source,
        recovery,
        expected,
    )
    failures = merge_failures(
        () if move_error is None else (move_error,),
        proof.failures,
    )
    if move_error is None and proof.complete and proof.retained and not proof.transient:
        return proof.retained[0]
    detail = (
        "recovery move completed but its callable raised; NEEDS_CONTEXT"
        if move_error is not None and proof.complete
        else "unexpected retained object needs recovery context; NEEDS_CONTEXT"
    )
    context_error = PublicationCommitContextError(
        detail,
        proof.retained,
        proof.transient,
        failures,
    )
    if move_error is not None:
        raise context_error from move_error
    raise context_error


@dataclass(frozen=True, slots=True)
class _RecoveryMoveProof:
    complete: bool
    retained: tuple[RetainedCacheRecord, ...]
    transient: tuple[PublicationTransientRecord, ...]
    failures: tuple[Exception, ...]


def _reprove_recovery_move(
    parent_descriptor: int,
    parent_identity: DirectoryIdentity,
    source: Path,
    recovery: Path,
    expected: DirectoryIdentity,
) -> _RecoveryMoveProof:
    source_proof = read_named_leaf(parent_descriptor, source.name)
    recovery_proof = read_named_leaf(parent_descriptor, recovery.name)
    retained = (
        (RetainedCacheRecord(recovery, RetainedCacheRole.RECOVERY, *expected),)
        if recovery_proof.identity == expected
        else ()
    )
    transient = tuple(
        PublicationTransientRecord(
            source.parent,
            path.name,
            parent_identity,
            proof.identity,
        )
        for path, proof, allowed in (
            (source, source_proof, None),
            (recovery, recovery_proof, expected),
        )
        if not proof.readable
        or (proof.identity is not None and proof.identity != allowed)
    )
    return _RecoveryMoveProof(
        bool(retained and source_proof.readable and source_proof.identity is None),
        retained,
        transient,
        merge_failures(source_proof.failures, recovery_proof.failures),
    )


def _named_transient(
    parent_identity: DirectoryIdentity,
    path: Path,
    proof: NamedLeafProof,
    allowed: DirectoryIdentity | None,
) -> tuple[PublicationTransientRecord, ...]:
    if proof.readable and proof.identity == allowed:
        return ()
    return (
        PublicationTransientRecord(
            path.parent,
            path.name,
            parent_identity,
            proof.identity,
        ),
    )


__all__ = ("move_object_to_recovery",)
