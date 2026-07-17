"""Immutable snapshots of every legal held-stage location."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import assert_never

from .description_cache_publication_errors import merge_failures
from .description_cache_publication_fs import DirectoryIdentity
from .description_cache_publication_models import (
    PublicationTransientRecord,
    RetainedCacheRecord,
    RetainedCacheRole,
)
from .description_cache_publication_named_leaf import read_named_leaf
from .description_cache_publication_retention_names import RetainedCacheNames
from .description_cache_publication_stage import BoundDescriptionCacheStage


@dataclass(frozen=True, slots=True)
class _StageLocationState:
    path: Path
    role: RetainedCacheRole | None
    readable: bool
    identity: DirectoryIdentity | None
    failure: OSError | None


def _snapshot_locations(
    bound: BoundDescriptionCacheStage,
    output: Path,
    names: RetainedCacheNames,
) -> tuple[_StageLocationState, ...]:
    states: list[_StageLocationState] = []
    for path, role in (
        (output, None),
        (
            names.path(RetainedCacheRole.PREVIOUS),
            RetainedCacheRole.PREVIOUS,
        ),
        (
            names.path(RetainedCacheRole.FAILED_STAGE),
            RetainedCacheRole.FAILED_STAGE,
        ),
        (
            names.path(RetainedCacheRole.FAILED_OUTPUT),
            RetainedCacheRole.FAILED_OUTPUT,
        ),
        (
            names.path(RetainedCacheRole.RECOVERY),
            RetainedCacheRole.RECOVERY,
        ),
    ):
        proof = read_named_leaf(bound.parent_descriptor, path.name)
        states.append(
            _StageLocationState(
                path,
                role,
                proof.readable,
                proof.identity,
                proof.failure,
            )
        )
    return tuple(states)


def _snapshot_failures(
    states: tuple[_StageLocationState, ...],
) -> tuple[Exception, ...]:
    failures: tuple[Exception, ...] = ()
    for state in states:
        if state.failure is not None:
            failures = merge_failures(failures, (state.failure,))
    return failures


def _retained_match(
    state: _StageLocationState,
) -> RetainedCacheRecord | None:
    match state.role:
        case None:
            return None
        case RetainedCacheRole() as role:
            if state.identity is None:
                return None
            return RetainedCacheRecord(state.path, role, *state.identity)
        case unreachable:
            assert_never(unreachable)


def _is_known_state(
    state: _StageLocationState,
    records: tuple[RetainedCacheRecord, ...],
) -> bool:
    return any(
        record.path == state.path and record.identity == state.identity
        for record in records
    )


def _known_records_match(
    states: tuple[_StageLocationState, ...],
    records: tuple[RetainedCacheRecord, ...],
) -> bool:
    return all(
        any(
            state.readable
            and state.path == record.path
            and state.identity == record.identity
            for state in states
        )
        for record in records
    )


def _state_transient(
    bound: BoundDescriptionCacheStage,
    state: _StageLocationState,
) -> PublicationTransientRecord:
    return PublicationTransientRecord(
        bound.stage.parent,
        state.path.name,
        bound.parent_identity,
        state.identity,
    )


def _snapshot_as_transient(
    bound: BoundDescriptionCacheStage,
    states: tuple[_StageLocationState, ...],
) -> tuple[PublicationTransientRecord, ...]:
    return tuple(
        PublicationTransientRecord(
            bound.stage.parent,
            state.path.name,
            bound.parent_identity,
            state.identity,
            bound.stage_identity if state.identity == bound.stage_identity else None,
        )
        for state in states
        if not state.readable or state.identity is not None
    )


__all__ = ()
