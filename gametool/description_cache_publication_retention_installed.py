"""Postcondition handling after an intended retained target is exact."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .description_cache_publication_errors import (
    PublicationCommitContextError,
    RetainedObjectInstalledContextError,
    merge_failures,
    merge_retained,
)
from .description_cache_publication_fs import DirectoryIdentity
from .description_cache_publication_models import (
    PublicationTransientRecord,
    RetainedCacheRecord,
    RetainedCacheRole,
)
from .description_cache_publication_retention_names import RetainedCacheNames
from .description_cache_publication_retention_recovery import (
    move_object_to_recovery,
)


type Rename = Callable[[int, str, str], None]


def finish_installed_target(
    parent_descriptor: int,
    parent_identity: DirectoryIdentity,
    source: Path,
    source_readable: bool,
    source_identity: DirectoryIdentity | None,
    target: Path,
    expected: DirectoryIdentity,
    role: RetainedCacheRole,
    names: RetainedCacheNames,
    rename_noreplace: Rename,
    move_error: Exception | None,
    prior_failures: tuple[Exception, ...],
) -> RetainedCacheRecord:
    """Return only a clean intended target or raise the no-rollback subtype."""
    intended = RetainedCacheRecord(target, role, *expected)
    source_transient = _source_transient(
        parent_identity,
        source,
        source_readable,
        source_identity,
    )
    if source_readable and source_identity is not None:
        try:
            recovery = move_object_to_recovery(
                parent_descriptor,
                parent_identity,
                source,
                source_identity,
                names,
                rename_noreplace,
            )
        except PublicationCommitContextError as recovery_error:
            installed_error = RetainedObjectInstalledContextError(
                intended,
                str(recovery_error),
                merge_retained((intended,), recovery_error.retained),
                (*source_transient, *recovery_error.transient),
                merge_failures(prior_failures, recovery_error.failures),
            )
            raise installed_error from recovery_error
        context_error = RetainedObjectInstalledContextError(
            intended,
            "retention source name was reacquired; NEEDS_CONTEXT",
            (intended, recovery),
            failures=prior_failures,
        )
        if move_error is not None:
            raise context_error from move_error
        raise context_error
    if move_error is not None or source_transient:
        context_error = RetainedObjectInstalledContextError(
            intended,
            "retention target was installed but move completion is uncertain; "
            "NEEDS_CONTEXT",
            (intended,),
            source_transient,
            prior_failures,
        )
        if move_error is not None:
            raise context_error from move_error
        raise context_error
    return intended


def _source_transient(
    parent_identity: DirectoryIdentity,
    source: Path,
    readable: bool,
    identity: DirectoryIdentity | None,
) -> tuple[PublicationTransientRecord, ...]:
    if readable and identity is None:
        return ()
    return (
        PublicationTransientRecord(
            source.parent,
            source.name,
            parent_identity,
            identity,
        ),
    )


__all__ = ("finish_installed_target",)
