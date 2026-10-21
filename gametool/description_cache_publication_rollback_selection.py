"""Select the one live name that can participate in an exact rollback."""

from __future__ import annotations

from pathlib import Path

from .description_cache_publication_errors import (
    PublicationCommitContextError,
    merge_failures,
)
from .description_cache_publication_fs import DirectoryIdentity
from .description_cache_publication_models import (
    PublicationTransientRecord,
    RetainedCacheRecord,
)
from .description_cache_publication_named_leaf import (
    read_named_leaf,
    reprove_retained,
    reprove_transient,
)


def select_live_identity_path(
    parent_descriptor: int,
    parent: Path,
    parent_identity: DirectoryIdentity,
    candidates: tuple[Path, ...],
    expected: DirectoryIdentity,
    records: tuple[RetainedCacheRecord, ...],
    transient: tuple[PublicationTransientRecord, ...],
) -> Path:
    """Return the unique current name for one rollback identity."""
    if not candidates:
        raise _selection_error(
            "previous generation has no rollback candidates; NEEDS_CONTEXT",
            parent_descriptor,
            parent,
            parent_identity,
            records,
            transient,
            (),
        )
    expected_parent = candidates[0].parent
    live: list[Path] = []
    unreadable: list[PublicationTransientRecord] = []
    failures: tuple[Exception, ...] = ()
    for path in dict.fromkeys(candidates):
        if path.parent != expected_parent:
            continue
        proof = read_named_leaf(parent_descriptor, path.name)
        failures = merge_failures(failures, proof.failures)
        if not proof.readable:
            unreadable.append(
                PublicationTransientRecord(parent, path.name, parent_identity, None)
            )
        if proof.identity == expected:
            live.append(path)
    if failures or len(live) != 1:
        raise _selection_error(
            "previous generation has no unique live rollback name; NEEDS_CONTEXT",
            parent_descriptor,
            parent,
            parent_identity,
            records,
            (*transient, *unreadable),
            failures,
        )
    return live[0]


def _selection_error(
    detail: str,
    parent_descriptor: int,
    parent: Path,
    parent_identity: DirectoryIdentity,
    records: tuple[RetainedCacheRecord, ...],
    transient: tuple[PublicationTransientRecord, ...],
    failures: tuple[Exception, ...],
) -> PublicationCommitContextError:
    proof = reprove_retained(
        parent_descriptor,
        parent,
        parent_identity,
        records,
    )
    current_transient = reprove_transient(
        parent_descriptor,
        parent,
        parent_identity,
        (*transient, *proof.transient),
    )
    return PublicationCommitContextError(
        detail,
        proof.retained,
        current_transient.transient,
        merge_failures(
            failures,
            (*proof.failures, *current_transient.failures),
        ),
    )


__all__ = ("select_live_identity_path",)
