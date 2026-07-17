"""Creation and descriptor ownership for one private cache stage."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os
from pathlib import Path
import sys
from types import TracebackType
from typing import Final, Self, assert_never

from .description_cache_publication_descriptor_close import (
    DescriptorCloseLedger,
    close_publication_descriptors,
)
from .description_cache_publication_errors import (
    DescriptionCacheConcurrentDestinationError,
    DescriptionCachePublicationError,
    PublicationCommitContextError,
    merge_failures,
)
from .description_cache_publication_evidence import finalize_error_evidence
from .description_cache_publication_fs import DirectoryIdentity, directory_identity
from .description_cache_publication_named_leaf import (
    capture_named_transient,
)
from .description_cache_publication_parent_identity import (
    parent_descriptor_identity,
    require_parent_identity,
)
from .description_cache_publication_retention_names import RetainedCacheNames
from .description_cache_publication_stage_normalization import (
    capture_transient_record,
    raise_normalized_stage_creation_failure,
)
from .description_cache_publication_stage_identity import descriptor_identity


_DIRECTORY_FLAGS: Final = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
type Rename = Callable[[int, str, str], None]
type Sync = Callable[[int], None]


@dataclass(frozen=True, slots=True)
class BoundDescriptionCacheStage:
    """The exact parent and captured stage held for one publication attempt."""

    parent_descriptor: int
    stage_descriptor: int
    stage: Path
    parent_identity: DirectoryIdentity
    stage_identity: DirectoryIdentity
    close_ledger: DescriptorCloseLedger

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        _exception_type: type[BaseException] | None,
        _exception: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        close_publication_descriptors(
            (
                ("stage", self.stage_descriptor),
                ("parent", self.parent_descriptor),
            ),
            _exception,
            self.close_ledger,
        )


def create_stage_and_capture(
    stage: Path,
    output: Path,
    names: RetainedCacheNames,
    rename_noreplace: Rename,
    sync_parent: Sync,
) -> BoundDescriptionCacheStage:
    """Create, capture, synchronize, and return one private stage."""
    try:
        parent_descriptor = os.open(stage.parent, _DIRECTORY_FLAGS)
    except OSError as exc:
        raise PublicationCommitContextError(
            "cannot bind publication parent before stage creation; NEEDS_CONTEXT",
            failures=(exc,),
        ) from exc
    stage_descriptor = -1
    parent_identity: DirectoryIdentity | None = None
    directory_expected: DirectoryIdentity | None = None
    held_expected: DirectoryIdentity | None = None
    created = False
    collision_handled = False
    transferred = False
    try:
        parent_identity = parent_descriptor_identity(parent_descriptor)
        require_parent_identity(parent_descriptor, stage.parent, parent_identity)
        try:
            os.mkdir(stage.name, mode=0o700, dir_fd=parent_descriptor)
        except FileExistsError as exc:
            collision_handled = True
            collision_evidence = capture_transient_record(
                parent_descriptor,
                stage,
                parent_identity,
                None,
            )
            collision_error = DescriptionCacheConcurrentDestinationError(
                "private stage name was acquired concurrently",
                transient=collision_evidence.transient,
                failures=merge_failures((exc,), collision_evidence.failures),
            )
            finalized = finalize_error_evidence(
                parent_descriptor,
                stage.parent,
                parent_identity,
                collision_error,
                parent_loss_evidence=capture_named_transient(
                    parent_descriptor,
                    stage.parent,
                    parent_identity,
                    output,
                ),
            )
            raise finalized
        created = True
        directory_expected = directory_identity(parent_descriptor, stage.name)
        stage_descriptor = os.open(
            stage.name,
            _DIRECTORY_FLAGS,
            dir_fd=parent_descriptor,
        )
        held_expected = descriptor_identity(stage_descriptor)
        if held_expected != directory_expected:
            raise PublicationCommitContextError(
                "stage leaf changed between first proof and descriptor capture; "
                "NEEDS_CONTEXT"
            )
        require_parent_identity(parent_descriptor, stage.parent, parent_identity)
        sync_parent(parent_descriptor)
        require_parent_identity(parent_descriptor, stage.parent, parent_identity)
        bound = BoundDescriptionCacheStage(
            parent_descriptor,
            stage_descriptor,
            stage,
            parent_identity,
            directory_expected,
            DescriptorCloseLedger(),
        )
        transferred = True
        return bound
    except Exception as exc:  # noqa: BROAD_EXCEPT_OK - created-stage normalization
        if collision_handled:
            match exc:
                case DescriptionCachePublicationError():
                    raise
                case Exception() as ordinary_error:
                    pass
                case unreachable:
                    assert_never(unreachable)
            if parent_identity is None:
                raise PublicationCommitContextError(
                    "stage collision lost its parent identity; NEEDS_CONTEXT"
                ) from ordinary_error
            collision_failure = PublicationCommitContextError(
                "stage-collision evidence raised an ordinary exception; NEEDS_CONTEXT",
                failures=(ordinary_error,),
            )
            finalized = finalize_error_evidence(
                parent_descriptor,
                stage.parent,
                parent_identity,
                collision_failure,
                parent_loss_evidence=capture_named_transient(
                    parent_descriptor,
                    stage.parent,
                    parent_identity,
                    output,
                ),
            )
            finalized.replace_failures(
                merge_failures(finalized.failures, (ordinary_error,))
            )
            raise finalized
        if parent_identity is None:
            match exc:
                case DescriptionCachePublicationError():
                    raise
                case Exception() as ordinary_error:
                    context_error = PublicationCommitContextError(
                        "stage parent identity is unavailable; NEEDS_CONTEXT",
                        failures=(ordinary_error,),
                    )
                case unreachable:
                    assert_never(unreachable)
            raise context_error from ordinary_error
        if not created:
            match exc:
                case DescriptionCachePublicationError() as publication_error:
                    creation_error = publication_error
                case Exception() as ordinary_error:
                    creation_error = PublicationCommitContextError(
                        "stage creation could not start safely; NEEDS_CONTEXT",
                        failures=(ordinary_error,),
                    )
                case unreachable:
                    assert_never(unreachable)
            finalized = finalize_error_evidence(
                parent_descriptor,
                stage.parent,
                parent_identity,
                creation_error,
                parent_loss_evidence=capture_named_transient(
                    parent_descriptor,
                    stage.parent,
                    parent_identity,
                    output,
                ),
            )
            raise finalized
        raise_normalized_stage_creation_failure(
            parent_descriptor,
            stage,
            output,
            parent_identity,
            directory_expected,
            held_expected,
            names,
            rename_noreplace,
            sync_parent,
            exc,
        )
    finally:
        if not transferred:
            descriptors = (
                (
                    ("stage", stage_descriptor),
                    ("parent", parent_descriptor),
                )
                if stage_descriptor >= 0
                else (("parent", parent_descriptor),)
            )
            close_publication_descriptors(
                descriptors,
                sys.exception(),
                DescriptorCloseLedger(),
            )


__all__ = (
    "BoundDescriptionCacheStage",
    "create_stage_and_capture",
    "descriptor_identity",
)
