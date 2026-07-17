"""Atomic no-replace movement of one non-active cache object."""

from __future__ import annotations

from collections.abc import Callable
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
from .description_cache_publication_retention_installed import (
    finish_installed_target,
)
from .description_cache_publication_retention_names import RetainedCacheNames
from .description_cache_publication_retention_recovery import (
    move_object_to_recovery,
)


type Rename = Callable[[int, str, str], None]


def retain_object(
    parent_descriptor: int,
    parent_identity: DirectoryIdentity,
    source: Path,
    expected: DirectoryIdentity,
    names: RetainedCacheNames,
    role: RetainedCacheRole,
    rename_noreplace: Rename,
) -> RetainedCacheRecord:
    """Move one exact source to an intended no-replace retained role."""
    if source.parent != names.parent:
        raise PublicationCommitContextError(
            "retention escaped the publication parent; NEEDS_CONTEXT"
        )
    target = names.path(role)
    source_before = read_named_leaf(parent_descriptor, source.name)
    if not source_before.readable or source_before.identity is None:
        context_error = PublicationCommitContextError(
            "retention source cannot be proved; NEEDS_CONTEXT",
            transient=_proof_transient(
                parent_identity,
                source,
                source_before,
                None,
            ),
            failures=source_before.failures,
        )
        if source_before.failure is not None:
            raise context_error from source_before.failure
        raise context_error
    if source_before.identity != expected:
        recovery = move_object_to_recovery(
            parent_descriptor,
            parent_identity,
            source,
            source_before.identity,
            names,
            rename_noreplace,
        )
        raise PublicationCommitContextError(
            "retention source identity changed and was preserved as recovery; "
            "NEEDS_CONTEXT",
            (recovery,),
        )

    move_error: Exception | None = None
    try:
        rename_noreplace(parent_descriptor, source.name, target.name)
    except Exception as exc:  # noqa: BROAD_EXCEPT_OK - atomic move reproof
        move_error = exc

    source_after = read_named_leaf(parent_descriptor, source.name)
    target_after = read_named_leaf(parent_descriptor, target.name)
    prior_failures = merge_failures(
        () if move_error is None else (move_error,),
        (*source_after.failures, *target_after.failures),
    )
    if target_after.identity == expected:
        return finish_installed_target(
            parent_descriptor,
            parent_identity,
            source,
            source_after.readable,
            source_after.identity,
            target,
            expected,
            role,
            names,
            rename_noreplace,
            move_error,
            prior_failures,
        )
    if (
        source_after.identity == expected
        and target_after.readable
        and target_after.identity is not None
    ):
        collision = _proof_transient(
            parent_identity,
            target,
            target_after,
            expected,
        )
        try:
            recovery = move_object_to_recovery(
                parent_descriptor,
                parent_identity,
                source,
                expected,
                names,
                rename_noreplace,
            )
        except PublicationCommitContextError as recovery_error:
            recovery_error.replace_transient((*recovery_error.transient, *collision))
            recovery_error.replace_failures(
                merge_failures(prior_failures, recovery_error.failures)
            )
            raise
        context_error = PublicationCommitContextError(
            "retained role was occupied; source preserved as recovery; NEEDS_CONTEXT",
            (recovery,),
            collision,
            prior_failures,
        )
        if move_error is not None:
            raise context_error from move_error
        raise context_error
    if target_after.readable and target_after.identity is not None:
        source_transient = _proof_transient(
            parent_identity,
            source,
            source_after,
            None,
        )
        try:
            recovery = move_object_to_recovery(
                parent_descriptor,
                parent_identity,
                target,
                target_after.identity,
                names,
                rename_noreplace,
            )
        except PublicationCommitContextError as recovery_error:
            recovery_error.replace_transient(
                (*recovery_error.transient, *source_transient)
            )
            recovery_error.replace_failures(
                merge_failures(prior_failures, recovery_error.failures)
            )
            raise
        context_error = PublicationCommitContextError(
            "retention moved an unexpected identity; NEEDS_CONTEXT",
            (recovery,),
            source_transient,
            prior_failures,
        )
        if move_error is not None:
            raise context_error from move_error
        raise context_error
    context_error = PublicationCommitContextError(
        "retention move could not be proved; NEEDS_CONTEXT",
        transient=(
            *_proof_transient(parent_identity, source, source_after, None),
            *_proof_transient(parent_identity, target, target_after, None),
        ),
        failures=prior_failures,
    )
    if move_error is not None:
        raise context_error from move_error
    raise context_error


def _proof_transient(
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


__all__ = ("retain_object",)
