"""Identity-aware evidence preservation after partial rollback."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .description_cache_publication_errors import (
    DescriptionCachePublicationError,
    PublicationCommitContextError,
    merge_failures,
    merge_retained,
)
from .description_cache_publication_evidence import (
    finalize_error_evidence,
    require_live_retained_evidence,
)
from .description_cache_publication_fs import DirectoryIdentity
from .description_cache_publication_models import (
    PublicationTransientRecord,
    RetainedCacheRecord,
    RetainedCacheRole,
)
from .description_cache_publication_named_leaf import (
    read_named_leaf,
    reprove_retained,
    reprove_transient,
)
from .description_cache_publication_retention_names import RetainedCacheNames


type BoundRetain = Callable[
    [Path, DirectoryIdentity, RetainedCacheRole],
    RetainedCacheRecord,
]
type Sync = Callable[[int], None]


def normalize_recovery_failure(
    parent_descriptor: int,
    parent: Path,
    parent_identity: DirectoryIdentity,
    candidates: tuple[Path, ...],
    staged_identity: DirectoryIdentity,
    prior_records: tuple[RetainedCacheRecord, ...],
    prior_transient: tuple[PublicationTransientRecord, ...],
    prior_failures: tuple[Exception, ...],
    names: RetainedCacheNames,
    retain: BoundRetain,
    sync_parent: Sync,
) -> tuple[RetainedCacheRecord, ...]:
    """Preserve every exactly classified rollback leaf after a partial failure."""
    initial_proof = reprove_retained(
        parent_descriptor,
        parent,
        parent_identity,
        prior_records,
    )
    records = initial_proof.retained
    transient_proof = reprove_transient(
        parent_descriptor,
        parent,
        parent_identity,
        (*prior_transient, *initial_proof.transient),
    )
    transient = transient_proof.transient
    failures = merge_failures(
        prior_failures,
        (*initial_proof.failures, *transient_proof.failures),
    )
    for path in dict.fromkeys(candidates):
        if path.parent != parent:
            context_error = PublicationCommitContextError(
                "recovery candidate escaped the held parent; NEEDS_CONTEXT",
                records,
                transient,
                failures,
            )
            raise finalize_error_evidence(
                parent_descriptor,
                parent,
                parent_identity,
                context_error,
            )
        current_proof = read_named_leaf(parent_descriptor, path.name)
        failures = merge_failures(failures, current_proof.failures)
        if current_proof.readable and current_proof.identity is None:
            continue
        if current_proof.identity is None:
            transient = (
                *transient,
                PublicationTransientRecord(
                    parent,
                    path.name,
                    parent_identity,
                    None,
                ),
            )
            continue
        current = current_proof.identity
        role = (
            RetainedCacheRole.FAILED_STAGE
            if current == staged_identity
            else RetainedCacheRole.RECOVERY
        )
        existing = tuple(
            record
            for record in records
            if record.path == path
            and record.identity == current
            and (
                current != staged_identity
                or record.role is RetainedCacheRole.FAILED_STAGE
            )
        )
        if existing:
            continue
        target = names.path(role)
        try:
            retained = (
                RetainedCacheRecord(path, role, *current)
                if path == target
                else retain(path, current, role)
            )
        except DescriptionCachePublicationError as retention_error:
            raise finalize_error_evidence(
                parent_descriptor,
                parent,
                parent_identity,
                retention_error,
                earlier_retained=records,
                earlier_transient=transient,
                earlier_failures=failures,
            )
        retained_proof = reprove_retained(
            parent_descriptor,
            parent,
            parent_identity,
            merge_retained(records, (retained,)),
        )
        records = retained_proof.retained
        failures = merge_failures(failures, retained_proof.failures)
        transient = tuple(dict.fromkeys((*transient, *retained_proof.transient)))
    try:
        sync_parent(parent_descriptor)
    except Exception as sync_error:  # noqa: BROAD_EXCEPT_OK - rollback durability
        sync_proof = reprove_retained(
            parent_descriptor,
            parent,
            parent_identity,
            records,
        )
        context_error = PublicationCommitContextError(
            "partial rollback could not be durably synchronized; NEEDS_CONTEXT",
            sync_proof.retained,
            (*transient, *sync_proof.transient),
            failures=merge_failures(
                failures,
                (sync_error, *sync_proof.failures),
            ),
        )
        finalized = finalize_error_evidence(
            parent_descriptor,
            parent,
            parent_identity,
            context_error,
        )
        raise finalized
    try:
        live = require_live_retained_evidence(
            parent_descriptor,
            parent,
            parent_identity,
            records,
        )
    except DescriptionCachePublicationError as evidence_error:
        raise finalize_error_evidence(
            parent_descriptor,
            parent,
            parent_identity,
            evidence_error,
            earlier_transient=transient,
            earlier_failures=failures,
        )
    if transient:
        context_error = PublicationCommitContextError(
            "partial rollback needs exact operator context; NEEDS_CONTEXT",
            live,
            transient,
            failures,
        )
        raise finalize_error_evidence(
            parent_descriptor,
            parent,
            parent_identity,
            context_error,
        )
    return live


__all__ = ("normalize_recovery_failure",)
