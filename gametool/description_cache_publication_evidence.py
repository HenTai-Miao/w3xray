"""Caller-visible evidence boundaries for trusted-cache publication."""

from __future__ import annotations

from pathlib import Path

from .description_cache_publication_errors import (
    DescriptionCachePublicationError,
    PublicationCommitContextError,
    merge_failures,
    merge_retained,
)
from .description_cache_publication_fs import DirectoryIdentity
from .description_cache_publication_models import (
    PublicationTransientRecord,
    RetainedCacheRecord,
    RetainedEvidenceReproof,
)
from .description_cache_publication_named_leaf import (
    reprove_retained,
    reprove_transient,
)
from .description_cache_publication_parent_identity import require_parent_identity


def retained_as_transient(
    parent: Path,
    parent_identity: DirectoryIdentity,
    records: tuple[RetainedCacheRecord, ...],
) -> tuple[PublicationTransientRecord, ...]:
    """Demote held leaves whose public parent pathname is no longer bound."""
    return tuple(
        PublicationTransientRecord(
            parent,
            record.path.name,
            parent_identity,
            record.identity,
        )
        for record in records
    )


def finalize_error_evidence(
    parent_descriptor: int,
    parent: Path,
    parent_identity: DirectoryIdentity,
    error: DescriptionCachePublicationError,
    *,
    earlier_retained: tuple[RetainedCacheRecord, ...] = (),
    later_retained: tuple[RetainedCacheRecord, ...] = (),
    earlier_transient: tuple[PublicationTransientRecord, ...] = (),
    later_transient: tuple[PublicationTransientRecord, ...] = (),
    earlier_failures: tuple[Exception, ...] = (),
    later_failures: tuple[Exception, ...] = (),
    earlier_evidence: RetainedEvidenceReproof = RetainedEvidenceReproof(),
    later_evidence: RetainedEvidenceReproof = RetainedEvidenceReproof(),
    parent_loss_evidence: RetainedEvidenceReproof = RetainedEvidenceReproof(),
) -> DescriptionCachePublicationError:
    """Return one error containing only currently caller-addressable evidence."""
    merged = merge_retained(
        merge_retained(earlier_retained, earlier_evidence.retained),
        merge_retained(
            error.retained,
            merge_retained(later_evidence.retained, later_retained),
        ),
    )
    proof = reprove_retained(parent_descriptor, parent, parent_identity, merged)
    transient_proof = reprove_transient(
        parent_descriptor,
        parent,
        parent_identity,
        (
            *earlier_transient,
            *earlier_evidence.transient,
            *error.transient,
            *later_evidence.transient,
            *later_transient,
            *proof.transient,
        ),
    )
    transient = transient_proof.transient
    failures = merge_failures(earlier_failures, earlier_evidence.failures)
    failures = merge_failures(failures, error.failures)
    failures = merge_failures(failures, later_evidence.failures)
    failures = merge_failures(failures, later_failures)
    failures = merge_failures(failures, (*proof.failures, *transient_proof.failures))
    try:
        require_parent_identity(parent_descriptor, parent, parent_identity)
    except PublicationCommitContextError as parent_error:
        parent_error.replace_failures(
            merge_failures(
                (*failures, error),
                (*parent_loss_evidence.failures, *parent_error.failures),
            )
        )
        parent_error.replace_retained(())
        parent_error.replace_transient(
            tuple(
                dict.fromkeys(
                    (
                        *transient,
                        *parent_error.transient,
                        *retained_as_transient(parent, parent_identity, proof.retained),
                        *parent_loss_evidence.transient,
                    )
                )
            )
        )
        return parent_error
    if proof.retained != merged or proof.transient:
        return PublicationCommitContextError(
            "publication error contains unprovable retained evidence; NEEDS_CONTEXT",
            proof.retained,
            transient,
            merge_failures(failures, (error,)),
        )
    error.replace_retained(proof.retained)
    error.replace_transient(transient)
    error.replace_failures(failures)
    return error


def require_live_retained_evidence(
    parent_descriptor: int,
    parent: Path,
    parent_identity: DirectoryIdentity,
    records: tuple[RetainedCacheRecord, ...],
    *,
    parent_loss_evidence: RetainedEvidenceReproof = RetainedEvidenceReproof(),
) -> tuple[RetainedCacheRecord, ...]:
    """Require every record to remain exact and publicly addressable."""
    proof = reprove_retained(parent_descriptor, parent, parent_identity, records)
    try:
        require_parent_identity(parent_descriptor, parent, parent_identity)
    except PublicationCommitContextError as parent_error:
        parent_error.replace_failures(
            merge_failures(
                (*proof.failures, *parent_loss_evidence.failures),
                parent_error.failures,
            )
        )
        parent_error.replace_retained(())
        parent_error.replace_transient(
            tuple(
                dict.fromkeys(
                    (
                        *proof.transient,
                        *retained_as_transient(parent, parent_identity, proof.retained),
                        *parent_loss_evidence.transient,
                    )
                )
            )
        )
        raise
    if proof.retained != records or proof.transient:
        raise PublicationCommitContextError(
            "retained evidence cannot be re-proved; NEEDS_CONTEXT",
            proof.retained,
            proof.transient,
            proof.failures,
        )
    return proof.retained


__all__ = (
    "finalize_error_evidence",
    "require_live_retained_evidence",
    "retained_as_transient",
)
