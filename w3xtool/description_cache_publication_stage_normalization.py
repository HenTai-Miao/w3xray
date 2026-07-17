"""Evidence normalization after a private stage creation failure."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Never

from .description_cache_publication_errors import (
    DescriptionCachePublicationError,
    PublicationCommitContextError,
    merge_failures,
)
from .description_cache_publication_evidence import finalize_error_evidence
from .description_cache_publication_fs import DirectoryIdentity
from .description_cache_publication_models import (
    PublicationTransientRecord,
    RetainedCacheRole,
    RetainedEvidenceReproof,
)
from .description_cache_publication_named_leaf import (
    capture_named_transient,
    read_named_leaf,
)
from .description_cache_publication_parent_identity import require_parent_identity
from .description_cache_publication_retention_durability import retain_durably
from .description_cache_publication_retention_names import RetainedCacheNames


type Rename = Callable[[int, str, str], None]
type Sync = Callable[[int], None]


def raise_normalized_stage_creation_failure(
    parent_descriptor: int,
    stage: Path,
    output: Path,
    parent_identity: DirectoryIdentity,
    directory_expected: DirectoryIdentity | None,
    held_identity: DirectoryIdentity | None,
    names: RetainedCacheNames,
    rename_noreplace: Rename,
    sync_parent: Sync,
    cause: Exception,
) -> Never:
    """Normalize a created stage before surfacing its initiating failure."""
    initiating_failures = (cause,)
    try:
        require_parent_identity(parent_descriptor, stage.parent, parent_identity)
    except PublicationCommitContextError as parent_error:
        stage_evidence = capture_transient_record(
            parent_descriptor,
            stage,
            parent_identity,
            held_identity,
        )
        context_error = PublicationCommitContextError(
            "stage parent lost its captured binding; NEEDS_CONTEXT",
            transient=stage_evidence.transient,
            failures=merge_failures(
                merge_failures(
                    initiating_failures,
                    (*parent_error.failures, parent_error),
                ),
                stage_evidence.failures,
            ),
        )
        finalized = finalize_error_evidence(
            parent_descriptor,
            stage.parent,
            parent_identity,
            context_error,
            parent_loss_evidence=capture_named_transient(
                parent_descriptor,
                stage.parent,
                parent_identity,
                output,
            ),
        )
        raise finalized
    current_proof = read_named_leaf(parent_descriptor, stage.name)
    if current_proof.identity is None:
        stage_evidence = capture_transient_record(
            parent_descriptor,
            stage,
            parent_identity,
            held_identity,
        )
        context_error = PublicationCommitContextError(
            "created stage identity is unavailable; NEEDS_CONTEXT",
            transient=stage_evidence.transient,
            failures=merge_failures(
                merge_failures(initiating_failures, current_proof.failures),
                stage_evidence.failures,
            ),
        )
        finalized = finalize_error_evidence(
            parent_descriptor,
            stage.parent,
            parent_identity,
            context_error,
            parent_loss_evidence=capture_named_transient(
                parent_descriptor,
                stage.parent,
                parent_identity,
                output,
            ),
        )
        raise finalized
    current = current_proof.identity
    role = (
        RetainedCacheRole.FAILED_STAGE
        if directory_expected == current
        else RetainedCacheRole.RECOVERY
    )
    held_transient = (
        ()
        if held_identity is None or held_identity == current
        else (
            PublicationTransientRecord(
                stage.parent,
                stage.name,
                parent_identity,
                None,
                held_identity,
            ),
        )
    )
    try:
        retained = retain_durably(
            parent_descriptor,
            stage.parent,
            parent_identity,
            stage,
            current,
            names,
            role,
            rename_noreplace,
            sync_parent,
        )
    except DescriptionCachePublicationError as retention_error:
        retention_error.replace_failures(
            merge_failures(initiating_failures, retention_error.failures)
        )
        finalized = finalize_error_evidence(
            parent_descriptor,
            stage.parent,
            parent_identity,
            retention_error,
            later_transient=held_transient,
            parent_loss_evidence=capture_named_transient(
                parent_descriptor,
                stage.parent,
                parent_identity,
                output,
            ),
        )
        raise finalized
    context_error = PublicationCommitContextError(
        "stage creation failed after evidence normalization; NEEDS_CONTEXT",
        (retained,),
        held_transient,
        initiating_failures,
    )
    finalized = finalize_error_evidence(
        parent_descriptor,
        stage.parent,
        parent_identity,
        context_error,
        parent_loss_evidence=capture_named_transient(
            parent_descriptor,
            stage.parent,
            parent_identity,
            output,
        ),
    )
    raise finalized


def capture_transient_record(
    parent_descriptor: int,
    stage: Path,
    parent_identity: DirectoryIdentity,
    held_identity: DirectoryIdentity | None,
) -> RetainedEvidenceReproof:
    """Capture the current stage leaf and a separately held identity."""
    proof = read_named_leaf(parent_descriptor, stage.name)
    if proof.readable and proof.identity is None and held_identity is None:
        return RetainedEvidenceReproof()
    return RetainedEvidenceReproof(
        transient=(
            PublicationTransientRecord(
                stage.parent,
                stage.name,
                parent_identity,
                proof.identity,
                held_identity,
            ),
        ),
        failures=proof.failures,
    )


__all__ = (
    "capture_transient_record",
    "raise_normalized_stage_creation_failure",
)
