"""No-replace publication when a trusted-cache destination is absent."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import assert_never

from .description_cache_publication_errors import (
    DescriptionCachePublicationError,
    PublicationCommitContextError,
    RetainedObjectInstalledContextError,
    merge_failures,
    merge_retained,
)
from .description_cache_publication_fs import DirectoryIdentity, object_identity
from .description_cache_publication_models import (
    DescriptionCachePublicationProof,
    DescriptionCachePublicationResult,
    RetainedCacheRecord,
    RetainedCacheRole,
)
from .description_cache_publication_named_leaf import capture_named_transient
from .trusted_description_cache_models import VerifiedDescriptionCache


type Rename = Callable[[int, str, str], None]
type Validate = Callable[[Path], VerifiedDescriptionCache]
type BoundRetain = Callable[
    [Path, DirectoryIdentity, RetainedCacheRole],
    RetainedCacheRecord,
]
type Sync = Callable[[int], None]


def publish_absent(
    parent_descriptor: int,
    parent_identity: DirectoryIdentity,
    stage: Path,
    output: Path,
    stage_identity: DirectoryIdentity,
    stage_verified: VerifiedDescriptionCache,
    rename_noreplace: Rename,
    require_valid: Validate,
    retain: BoundRetain,
    sync_parent: Sync,
) -> DescriptionCachePublicationProof:
    """Publish one stage and retain any installed output that later fails."""
    post_install_error: DescriptionCachePublicationError | None = None
    try:
        rename_noreplace(parent_descriptor, stage.name, output.name)
    except Exception as rename_cause:  # noqa: BROAD_EXCEPT_OK - install reproof
        installed, rename_error = _reprove_absent_install(
            parent_descriptor,
            parent_identity,
            stage,
            output,
            stage_identity,
        )
        rename_error.replace_failures(
            merge_failures((rename_cause,), rename_error.failures)
        )
        if not installed:
            raise rename_error from rename_cause
        post_install_error = rename_error
    try:
        if post_install_error is not None:
            raise post_install_error
        sync_parent(parent_descriptor)
        published = require_valid(output)
        _require_identity(parent_descriptor, output.name, stage_identity)
        if published != stage_verified:
            raise DescriptionCachePublicationError(
                "published output differs from the descriptor-verified stage"
            )
    except Exception as cause:  # noqa: BROAD_EXCEPT_OK - post-install retention
        match cause:
            case DescriptionCachePublicationError() as typed_error:
                publication_error = typed_error
            case Exception() as ordinary_error:
                publication_error = DescriptionCachePublicationError(
                    str(ordinary_error),
                    failures=(ordinary_error,),
                )
            case unreachable:
                assert_never(unreachable)
        try:
            retained = retain(
                output,
                stage_identity,
                RetainedCacheRole.FAILED_OUTPUT,
            )
        except Exception as retention_cause:  # noqa: BROAD_EXCEPT_OK - retain boundary
            match retention_cause:
                case DescriptionCachePublicationError() as typed_error:
                    retention_error = typed_error
                case Exception() as ordinary_error:
                    retention_error = PublicationCommitContextError(
                        f"failed-output retention raised an ordinary exception: "
                        f"{ordinary_error}; NEEDS_CONTEXT",
                        failures=(ordinary_error,),
                    )
                case unreachable:
                    assert_never(unreachable)
            detail = (
                f"{publication_error}; failed-output retention failed: "
                f"{retention_error}; NEEDS_CONTEXT"
            )
            retained_evidence = merge_retained(
                publication_error.retained,
                retention_error.retained,
            )
            transient_evidence = tuple(
                dict.fromkeys(
                    (*publication_error.transient, *retention_error.transient)
                )
            )
            failure_evidence = merge_failures(
                (*publication_error.failures, publication_error),
                (*retention_error.failures, retention_error),
            )
            match retention_error:
                case RetainedObjectInstalledContextError(installed=installed):
                    combined_error = RetainedObjectInstalledContextError(
                        installed,
                        detail,
                        retained_evidence,
                        transient_evidence,
                        failure_evidence,
                    )
                case DescriptionCachePublicationError():
                    combined_error = PublicationCommitContextError(
                        detail,
                        retained_evidence,
                        transient_evidence,
                        failure_evidence,
                    )
                case unreachable:
                    assert_never(unreachable)
            raise combined_error from retention_cause
        publication_error.replace_retained(
            merge_retained(publication_error.retained, (retained,))
        )
        if publication_error is not cause:
            publication_error.replace_failures(
                merge_failures(publication_error.failures, (cause,))
            )
        raise publication_error
    return DescriptionCachePublicationProof(
        DescriptionCachePublicationResult(stage_verified)
    )


def _reprove_absent_install(
    parent_descriptor: int,
    parent_identity: DirectoryIdentity,
    stage: Path,
    output: Path,
    expected: DirectoryIdentity,
) -> tuple[bool, DescriptionCachePublicationError]:
    output_evidence = capture_named_transient(
        parent_descriptor,
        output.parent,
        parent_identity,
        output,
    )
    stage_evidence = capture_named_transient(
        parent_descriptor,
        stage.parent,
        parent_identity,
        stage,
    )
    output_identity = (
        output_evidence.transient[0].identity if output_evidence.transient else None
    )
    stage_identity = (
        stage_evidence.transient[0].identity if stage_evidence.transient else None
    )
    installed = bool(output_identity == expected and stage_identity != expected)
    return installed, PublicationCommitContextError(
        "absent-output rename completion required namespace reproof; NEEDS_CONTEXT",
        transient=tuple(
            dict.fromkeys((*output_evidence.transient, *stage_evidence.transient))
        ),
        failures=merge_failures(
            output_evidence.failures,
            stage_evidence.failures,
        ),
    )


def _require_identity(
    parent_descriptor: int,
    name: str,
    expected: DirectoryIdentity,
) -> None:
    if object_identity(parent_descriptor, name) != expected:
        raise DescriptionCachePublicationError("published cache changed identity")


__all__ = ("publish_absent",)
