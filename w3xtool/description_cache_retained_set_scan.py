"""One complete relevant-sibling interval and its classified report rows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .description_cache_retained_binding import BoundActiveCache
from .description_cache_retained_classification import inspect_retained_artifact
from .description_cache_retained_integrity_models import (
    DESCRIPTION_CACHE_RETENTION_SCHEMA,
    CacheArtifactKind,
    DescriptionCacheRetentionError,
    DescriptionCacheRetentionReport,
    MalformedDescriptionCacheArtifact,
    RetainedDescriptionCacheArtifact,
    RetentionArtifactReason,
    SiblingState,
    TransientDescriptionCacheArtifact,
)
from .description_cache_retained_siblings import (
    BACKUP_PREFIX,
    RETAINED_PREFIX,
    STAGE_PREFIX,
    capture_relevant_siblings,
    parse_backup_name,
    parse_retained_name,
    parse_stage_name,
    transaction_prefix,
)
from .description_cache_retained_tree_snapshot import RetainedScanBounds


@dataclass(frozen=True, slots=True)
class ArtifactSetRound:
    """One complete sibling interval plus every derived report row."""

    siblings: tuple[SiblingState, ...]
    report: DescriptionCacheRetentionReport


def scan_artifact_set(
    bound: BoundActiveCache,
    bounds: RetainedScanBounds,
) -> ArtifactSetRound:
    """Capture, classify, and recapture every relevant sibling once."""
    before = capture_relevant_siblings(bound.parent_descriptor, bound.root.name)
    _require_active_state(bound, before)
    retained: list[RetainedDescriptionCacheArtifact] = []
    transient: list[TransientDescriptionCacheArtifact] = []
    malformed: list[MalformedDescriptionCacheArtifact] = []
    for state in before:
        if state.name == bound.root.name:
            continue
        parsed = parse_retained_name(state.name)
        if parsed is not None:
            retained.append(inspect_retained_artifact(bound, state, *parsed, bounds))
        elif state.name.startswith(RETAINED_PREFIX):
            malformed.append(
                _malformed(
                    bound.root,
                    state,
                    RETAINED_PREFIX,
                    RetentionArtifactReason.MALFORMED_RETAINED_NAME,
                )
            )
        else:
            _classify_stage_or_backup(bound.root, state, transient, malformed)
    after = capture_relevant_siblings(bound.parent_descriptor, bound.root.name)
    if before != after:
        raise DescriptionCacheRetentionError(
            "publication-relevant sibling namespace changed during a round"
        )
    _require_active_state(bound, after)
    report = DescriptionCacheRetentionReport(
        DESCRIPTION_CACHE_RETENTION_SCHEMA,
        bound.root,
        bound.root_identity[0],
        bound.root_identity[1],
        tuple(
            sorted(
                retained,
                key=lambda item: (
                    item.path.as_posix().encode("utf-8"),
                    item.role.value,
                ),
            )
        ),
        tuple(
            sorted(
                transient,
                key=lambda item: (
                    item.path.as_posix().encode("utf-8"),
                    item.reason.value,
                ),
            )
        ),
        tuple(
            sorted(
                malformed,
                key=lambda item: (
                    item.path.as_posix().encode("utf-8"),
                    item.reason.value,
                ),
            )
        ),
    )
    return ArtifactSetRound(before, report)


def _classify_stage_or_backup(
    active: Path,
    state: SiblingState,
    transient: list[TransientDescriptionCacheArtifact],
    malformed: list[MalformedDescriptionCacheArtifact],
) -> None:
    stage_id = parse_stage_name(state.name)
    backup_id = parse_backup_name(state.name)
    if stage_id is not None:
        normal = RetentionArtifactReason.STAGE_TRANSIENT
        transaction_id = stage_id
    elif backup_id is not None:
        normal = RetentionArtifactReason.BACKUP_TRANSIENT
        transaction_id = backup_id
    elif state.name.startswith(STAGE_PREFIX):
        malformed.append(
            _malformed(
                active,
                state,
                STAGE_PREFIX,
                RetentionArtifactReason.MALFORMED_STAGE_NAME,
            )
        )
        return
    else:
        malformed.append(
            _malformed(
                active,
                state,
                BACKUP_PREFIX,
                RetentionArtifactReason.MALFORMED_BACKUP_NAME,
            )
        )
        return
    reason = (
        RetentionArtifactReason.UNREADABLE_TRANSIENT
        if state.kind is CacheArtifactKind.UNKNOWN
        else normal
    )
    transient.append(
        TransientDescriptionCacheArtifact(
            active.parent / state.name,
            transaction_id,
            state.kind,
            state.device,
            state.inode,
            reason,
        )
    )


def _malformed(
    active: Path,
    state: SiblingState,
    prefix: str,
    reason: RetentionArtifactReason,
) -> MalformedDescriptionCacheArtifact:
    return MalformedDescriptionCacheArtifact(
        active.parent / state.name,
        transaction_prefix(state.name, prefix),
        state.kind,
        state.device,
        state.inode,
        reason,
    )


def _require_active_state(
    bound: BoundActiveCache,
    states: tuple[SiblingState, ...],
) -> None:
    matches = tuple(state for state in states if state.name == bound.root.name)
    if len(matches) != 1:
        raise DescriptionCacheRetentionError(
            "active root disappeared during enumeration"
        )
    state = matches[0]
    if (
        state.kind is not CacheArtifactKind.DIRECTORY
        or (state.device, state.inode) != bound.root_identity
    ):
        raise DescriptionCacheRetentionError(
            "active root identity changed during enumeration"
        )


__all__ = ("ArtifactSetRound", "scan_artifact_set")
