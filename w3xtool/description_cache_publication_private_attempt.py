"""Independent error capture for one private publication leaf."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import assert_never

from .description_cache_publication_errors import (
    DescriptionCachePublicationError,
    PublicationCommitContextError,
)
from .description_cache_publication_evidence import finalize_error_evidence
from .description_cache_publication_fs import DirectoryIdentity
from .description_cache_publication_models import RetainedCacheRecord
from .description_cache_publication_named_leaf import capture_named_transient
from .description_cache_publication_stage import BoundDescriptionCacheStage
from .description_cache_publication_stage_normalization import (
    capture_transient_record,
)


@dataclass(frozen=True, slots=True)
class PrivateAttempt:
    record: RetainedCacheRecord | None = None
    error: DescriptionCachePublicationError | None = None


def attempt_private(
    bound: BoundDescriptionCacheStage,
    path: Path,
    held_identity: DirectoryIdentity | None,
    operation: Callable[[], RetainedCacheRecord | None],
) -> PrivateAttempt:
    """Capture one failure so the other private name is still attempted."""
    try:
        return PrivateAttempt(record=operation())
    except Exception as cause:  # noqa: BROAD_EXCEPT_OK - independent private attempt
        match cause:
            case DescriptionCachePublicationError() as publication_error:
                return PrivateAttempt(error=publication_error)
            case Exception() as ordinary_error:
                error = PublicationCommitContextError(
                    f"private-artifact finalization raised an ordinary exception: "
                    f"{ordinary_error}; NEEDS_CONTEXT",
                    failures=(ordinary_error,),
                )
            case unreachable:
                assert_never(unreachable)
        match held_identity:
            case None:
                fallback = capture_named_transient(
                    bound.parent_descriptor,
                    bound.stage.parent,
                    bound.parent_identity,
                    path,
                )
            case (device, inode):
                fallback = capture_transient_record(
                    bound.parent_descriptor,
                    path,
                    bound.parent_identity,
                    (device, inode),
                )
            case unreachable:
                assert_never(unreachable)
        finalized = finalize_error_evidence(
            bound.parent_descriptor,
            bound.stage.parent,
            bound.parent_identity,
            error,
            later_evidence=fallback,
        )
        return PrivateAttempt(error=finalized)


def record_tuple(
    record: RetainedCacheRecord | None,
) -> tuple[RetainedCacheRecord, ...]:
    match record:
        case None:
            return ()
        case RetainedCacheRecord():
            return (record,)
        case unreachable:
            assert_never(unreachable)


__all__ = ("PrivateAttempt", "attempt_private", "record_tuple")
