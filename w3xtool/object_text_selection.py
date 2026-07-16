"""Select current object text while retaining every unique source row."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from typing import assert_never

from .object_text_evidence import (
    TextEvidence,
    TextIdentity,
    synthetic_text_evidence,
    unique_text_evidence,
)
from .object_text_models import (
    ObjectTextState,
    TextSelectionReason,
    TextSourcePriority,
)


@dataclass(frozen=True, slots=True)
class SelectedTextEvidence:
    """One retained evidence row annotated with its selection outcome."""

    evidence: TextEvidence
    state: ObjectTextState
    conflict_group: str
    is_current: bool
    selection_reason: TextSelectionReason


def select_text_identity(
    identity: TextIdentity,
    map_values: tuple[TextEvidence, ...],
    client_values: tuple[TextEvidence, ...],
    cache_values: tuple[TextEvidence, ...],
    client_text_available: bool,
) -> tuple[SelectedTextEvidence, ...]:
    """Select the highest usable priority and annotate all unique evidence."""
    retained = unique_text_evidence((*map_values, *client_values, *cache_values))
    usable = tuple(row for row in retained if not row.placeholder)
    if not usable:
        missing = synthetic_text_evidence(identity)
        missing_state = (
            ObjectTextState.AUTHOR_UNDEFINED
            if client_text_available
            else ObjectTextState.SOURCE_UNAVAILABLE
        )
        return (
            *(
                SelectedTextEvidence(
                    row,
                    ObjectTextState.AUTHOR_UNDEFINED,
                    "",
                    False,
                    TextSelectionReason.PLACEHOLDER_SKIPPED,
                )
                for row in retained
            ),
            SelectedTextEvidence(
                missing,
                missing_state,
                "",
                False,
                TextSelectionReason.NO_SOURCE,
            ),
        )

    highest_priority = max(row.source_priority for row in usable)
    raw_values_by_priority: dict[int, set[str]] = defaultdict(set)
    for row in usable:
        raw_values_by_priority[row.source_priority].add(row.raw_value)
    conflicts = {
        priority: _conflict_group(identity, priority, raw_values)
        for priority, raw_values in raw_values_by_priority.items()
        if len(raw_values) > 1
    }
    return tuple(
        _select_row(row, highest_priority, conflicts.get(row.source_priority, ""))
        for row in retained
    )


def _select_row(
    row: TextEvidence,
    highest_priority: int,
    conflict_group: str,
) -> SelectedTextEvidence:
    if row.placeholder:
        return SelectedTextEvidence(
            row,
            ObjectTextState.AUTHOR_UNDEFINED,
            "",
            False,
            TextSelectionReason.PLACEHOLDER_SKIPPED,
        )
    is_current = row.source_priority == highest_priority
    state = ObjectTextState.SOURCE_CONFLICT if conflict_group else _source_state(row)
    if not is_current:
        reason = TextSelectionReason.LOWER_PRIORITY
    elif conflict_group:
        reason = TextSelectionReason.SAME_PRIORITY_CONFLICT
    elif row.raw_value == "":
        reason = TextSelectionReason.EXPLICIT_EMPTY
    else:
        reason = TextSelectionReason.HIGHEST_PRIORITY_VALUE
    return SelectedTextEvidence(row, state, conflict_group, is_current, reason)


def _source_state(row: TextEvidence) -> ObjectTextState:
    priority = TextSourcePriority(row.source_priority)
    match priority:
        case (
            TextSourcePriority.MAP_TEXT_STRINGS
            | TextSourcePriority.MAP_BINARY
            | TextSourcePriority.MAP_FUNCTION_TEXT
            | TextSourcePriority.MAP_SLK
            | TextSourcePriority.MAP_ANONYMOUS
        ):
            return (
                ObjectTextState.MAP_EXPLICIT_EMPTY
                if row.raw_value == ""
                else ObjectTextState.MAP_VALUE
            )
        case TextSourcePriority.CLIENT:
            return ObjectTextState.CLIENT_FILL
        case TextSourcePriority.TRUSTED_CACHE:
            return ObjectTextState.CACHE_FILL
        case unreachable:
            assert_never(unreachable)


def _conflict_group(
    identity: TextIdentity,
    priority: int,
    raw_values: set[str],
) -> str:
    payload = "\x1f".join(
        (*map(str, identity), str(priority), *sorted(raw_values)),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


__all__ = ("SelectedTextEvidence", "select_text_identity")
