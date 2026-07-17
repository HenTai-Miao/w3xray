"""Durable caller boundary around atomic retention moves."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Never, assert_never

from .description_cache_publication_errors import (
    DescriptionCachePublicationError,
    PublicationCommitContextError,
    RetainedObjectInstalledContextError,
    installed_context_error,
    merge_failures,
)
from .description_cache_publication_evidence import (
    finalize_error_evidence,
    require_live_retained_evidence,
)
from .description_cache_publication_fs import DirectoryIdentity
from .description_cache_publication_models import (
    RetainedCacheRecord,
    RetainedCacheRole,
)
from .description_cache_publication_named_leaf import capture_named_transient
from .description_cache_publication_retention import retain_object
from .description_cache_publication_retention_names import RetainedCacheNames


type Rename = Callable[[int, str, str], None]
type Sync = Callable[[int], None]


def retain_durably(
    parent_descriptor: int,
    parent: Path,
    parent_identity: DirectoryIdentity,
    source: Path,
    expected: DirectoryIdentity,
    names: RetainedCacheNames,
    role: RetainedCacheRole,
    rename_noreplace: Rename,
    sync_parent: Sync,
) -> RetainedCacheRecord:
    """Move once, synchronize every outcome, and return only live evidence."""
    try:
        retained = retain_object(
            parent_descriptor,
            parent_identity,
            source,
            expected,
            names,
            role,
            rename_noreplace,
        )
    except RetainedObjectInstalledContextError as installed_error:
        _synchronize_installed_error(
            parent_descriptor,
            parent,
            parent_identity,
            source,
            installed_error,
            sync_parent,
        )
    except Exception as retention_cause:  # noqa: BROAD_EXCEPT_OK - durable retention
        match retention_cause:
            case DescriptionCachePublicationError() as publication_error:
                retention_error = publication_error
            case Exception() as ordinary_error:
                retention_error = PublicationCommitContextError(
                    f"retention raised an ordinary exception: {ordinary_error}; "
                    "NEEDS_CONTEXT",
                    failures=(ordinary_error,),
                )
            case unreachable:
                assert_never(unreachable)
        try:
            sync_parent(parent_descriptor)
        except Exception as sync_error:  # noqa: BROAD_EXCEPT_OK - durability sync
            source_evidence = capture_named_transient(
                parent_descriptor,
                parent,
                parent_identity,
                source,
            )
            context_error = PublicationCommitContextError(
                "retention error could not be durably synchronized; NEEDS_CONTEXT",
                retention_error.retained,
                (*retention_error.transient, *source_evidence.transient),
                merge_failures(
                    merge_failures(
                        (*retention_error.failures, retention_error),
                        (sync_error,),
                    ),
                    source_evidence.failures,
                ),
            )
            finalized = finalize_error_evidence(
                parent_descriptor,
                parent,
                parent_identity,
                context_error,
            )
            raise finalized
        raise finalize_error_evidence(
            parent_descriptor,
            parent,
            parent_identity,
            retention_error,
            later_evidence=capture_named_transient(
                parent_descriptor,
                parent,
                parent_identity,
                source,
            ),
        )
    try:
        sync_parent(parent_descriptor)
    except Exception as sync_error:  # noqa: BROAD_EXCEPT_OK - durability sync
        source_evidence = capture_named_transient(
            parent_descriptor,
            parent,
            parent_identity,
            source,
        )
        context_error = PublicationCommitContextError(
            "retained object could not be durably synchronized; NEEDS_CONTEXT",
            (retained,),
            source_evidence.transient,
            merge_failures((sync_error,), source_evidence.failures),
        )
        finalized = finalize_error_evidence(
            parent_descriptor,
            parent,
            parent_identity,
            context_error,
        )
        raise installed_context_error(retained, finalized)
    source_evidence = capture_named_transient(
        parent_descriptor,
        parent,
        parent_identity,
        source,
    )
    if source_evidence.transient or source_evidence.failures:
        context_error = PublicationCommitContextError(
            "retention source name was reacquired before durability boundary; "
            "NEEDS_CONTEXT",
            (retained,),
            source_evidence.transient,
            source_evidence.failures,
        )
        finalized = finalize_error_evidence(
            parent_descriptor,
            parent,
            parent_identity,
            context_error,
        )
        raise installed_context_error(retained, finalized)
    try:
        live = require_live_retained_evidence(
            parent_descriptor,
            parent,
            parent_identity,
            (retained,),
        )
    except Exception as evidence_cause:  # noqa: BROAD_EXCEPT_OK - evidence boundary
        match evidence_cause:
            case DescriptionCachePublicationError() as publication_error:
                evidence_error = publication_error
            case Exception() as ordinary_error:
                evidence_error = PublicationCommitContextError(
                    f"retained-evidence proof raised an ordinary exception: "
                    f"{ordinary_error}; NEEDS_CONTEXT",
                    failures=(ordinary_error,),
                )
            case unreachable:
                assert_never(unreachable)
        finalized = finalize_error_evidence(
            parent_descriptor,
            parent,
            parent_identity,
            evidence_error,
        )
        raise installed_context_error(retained, finalized)
    return live[0]


def _synchronize_installed_error(
    parent_descriptor: int,
    parent: Path,
    parent_identity: DirectoryIdentity,
    source: Path,
    installed_error: RetainedObjectInstalledContextError,
    sync_parent: Sync,
) -> Never:
    try:
        sync_parent(parent_descriptor)
    except Exception as sync_error:  # noqa: BROAD_EXCEPT_OK - installed sync
        context_error = PublicationCommitContextError(
            "installed retained target could not be durably synchronized; "
            "NEEDS_CONTEXT",
            installed_error.retained,
            installed_error.transient,
            merge_failures((*installed_error.failures, installed_error), (sync_error,)),
        )
        finalized = finalize_error_evidence(
            parent_descriptor,
            parent,
            parent_identity,
            context_error,
            later_evidence=capture_named_transient(
                parent_descriptor,
                parent,
                parent_identity,
                source,
            ),
        )
        raise installed_context_error(installed_error.installed, finalized)
    finalized = finalize_error_evidence(
        parent_descriptor,
        parent,
        parent_identity,
        installed_error,
        later_evidence=capture_named_transient(
            parent_descriptor,
            parent,
            parent_identity,
            source,
        ),
    )
    raise installed_context_error(installed_error.installed, finalized)


__all__ = ("retain_durably",)
