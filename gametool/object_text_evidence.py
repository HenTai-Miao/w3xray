"""Collect and normalize object-text evidence without resolving precedence."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, assert_never

from .description_cache import DescriptionCache
from .object_candidates import ObjectCandidate, ObjectFieldValue, ObjectSourceKind
from .object_candidate_models import FieldEvidenceState
from .object_layers import binary_layer_priority, split_field_column
from .object_text_models import TextSourcePriority
from .object_text_roles import classify_text_field, semantic_field_for_role
from .textobj import _sub_westring

if TYPE_CHECKING:
    from .client_object_data import ClientBaseObject


type TextIdentity = tuple[str, str, str, str, int | None]

_COLOR: Final = re.compile(r"\|c[0-9a-fA-F]{8}|\|r", re.IGNORECASE)
_PLACEHOLDERS: Final = frozenset({"-", "_", ",", '""', "''"})


@dataclass(frozen=True, slots=True)
class TextEvidence:
    """One exact text field before source-priority resolution."""

    role: str
    semantic_field: str
    level: int | None
    field_key: str
    field_label: str
    raw_value: str
    source_kind: str
    source_path: str
    source_priority: int
    placeholder: bool


def collect_map_text_evidence(
    candidates: tuple[ObjectCandidate, ...],
) -> dict[TextIdentity, tuple[TextEvidence, ...]]:
    """Collect every recognized map candidate without collapsing conflicts."""
    grouped: dict[TextIdentity, list[TextEvidence]] = {}
    for candidate in candidates:
        for field in candidate.fields:
            if field.state is not FieldEvidenceState.CONFIRMED:
                continue
            text_key, column = split_field_column(field.key)
            role = classify_text_field(
                candidate.category,
                text_key,
                field.label,
                field.value_type,
            )
            if role is None:
                continue
            semantic_field = role.semantic_field + (
                f":column:{column}" if column is not None else ""
            )
            key = (
                candidate.category,
                candidate.obj_id,
                semantic_field,
                role.role,
                role.level,
            )
            raw_value = field.value if field.raw_value is None else field.raw_value
            grouped.setdefault(key, []).append(
                TextEvidence(
                    role.role,
                    semantic_field,
                    role.level,
                    field.key,
                    field.label,
                    raw_value,
                    map_source_label(field.source_kind),
                    source_path(field),
                    int(TextSourcePriority.CAMPAIGN_INHERITED)
                    if field.priority_override is not None
                    and field.source_kind is not ObjectSourceKind.BASE
                    else map_text_source_priority(field.source_kind, field.source),
                    is_placeholder(raw_value),
                ),
            )
    return {key: unique_text_evidence(values) for key, values in grouped.items()}


def collect_client_text_evidence(
    client_objects: tuple[ClientBaseObject, ...],
) -> dict[TextIdentity, tuple[TextEvidence, ...]]:
    """Collect source-bearing text from the closed-source-safe client snapshot."""
    grouped: dict[TextIdentity, list[TextEvidence]] = {}
    for item in client_objects:
        for field in item.evidence_fields:
            if field.state is not FieldEvidenceState.CONFIRMED:
                continue
            role = classify_text_field(
                item.category,
                field.key,
                field.label,
                field.value_type,
            )
            if role is None:
                continue
            _text_key, column = split_field_column(field.key)
            semantic_field = role.semantic_field + (
                f":column:{column}" if column is not None else ""
            )
            key = (
                item.category,
                item.obj_id,
                semantic_field,
                role.role,
                role.level,
            )
            raw_value = field.value if field.raw_value is None else field.raw_value
            grouped.setdefault(key, []).append(
                TextEvidence(
                    role.role,
                    semantic_field,
                    role.level,
                    field.key,
                    field.label,
                    raw_value,
                    "Warcraft客户端",
                    source_path(field),
                    int(TextSourcePriority.CLIENT),
                    raw_value == "" or is_placeholder(raw_value),
                ),
            )
    return {key: unique_text_evidence(values) for key, values in grouped.items()}


def cache_text_evidence(
    cache: DescriptionCache,
    key: TextIdentity,
) -> tuple[TextEvidence, ...]:
    """Adapt validated cache entries to the common evidence representation."""
    category, base_id, semantic_field, role, level = key
    if semantic_field != semantic_field_for_role(role):
        return ()
    return tuple(
        TextEvidence(
            entry.role,
            semantic_field,
            entry.level,
            entry.role,
            entry.role,
            entry.raw_value,
            "可信描述缓存",
            entry.source_path,
            int(TextSourcePriority.TRUSTED_CACHE),
            False,
        )
        for entry in cache.lookup(category, base_id, role, level)
    )


def synthetic_text_evidence(identity: TextIdentity) -> TextEvidence:
    """Create one empty state row when no source has the expected role."""
    _category, _object_id, semantic_field, role, level = identity
    return TextEvidence(role, semantic_field, level, role, role, "", "", "", 0, False)


def unique_text_evidence(values: Iterable[TextEvidence]) -> tuple[TextEvidence, ...]:
    """Deduplicate exact evidence while preserving deterministic ordering."""
    return tuple(sorted(set(values), key=text_evidence_sort_key))


def readable_text(value: str) -> str:
    """Remove color syntax and expand newlines without trimming content."""
    return _COLOR.sub("", _sub_westring(value)).replace("|n", "\n").replace("\\n", "\n")


def is_placeholder(value: str) -> bool:
    """Recognize only the fixed author-undefined placeholder set."""
    return value.strip() in _PLACEHOLDERS


def map_source_label(kind: ObjectSourceKind) -> str:
    """Render exhaustive map-source kinds for GUI and TSV evidence."""
    match kind:
        case ObjectSourceKind.BASE:
            return "内置基础对象"
        case ObjectSourceKind.TEXT_ANONYMOUS:
            return "地图匿名文本块"
        case ObjectSourceKind.SLK:
            return "地图SLK"
        case ObjectSourceKind.TEXT_FUNC | ObjectSourceKind.TEXT_STRINGS:
            return "地图文本"
        case ObjectSourceKind.BINARY:
            return "地图二进制"
        case unreachable:
            assert_never(unreachable)


def map_text_source_priority(kind: ObjectSourceKind, source: str = "") -> int:
    """Map every candidate source kind to the complete-text precedence scale."""
    match kind:
        case ObjectSourceKind.BASE:
            return int(TextSourcePriority.CLIENT)
        case ObjectSourceKind.TEXT_ANONYMOUS:
            return int(TextSourcePriority.MAP_ANONYMOUS)
        case ObjectSourceKind.SLK:
            return int(TextSourcePriority.MAP_SLK)
        case ObjectSourceKind.TEXT_FUNC:
            return int(TextSourcePriority.MAP_FUNCTION_TEXT)
        case ObjectSourceKind.BINARY:
            return {
                32: int(TextSourcePriority.CAMPAIGN_BINARY),
                35: int(TextSourcePriority.CAMPAIGN_SKIN),
                40: int(TextSourcePriority.MAP_BINARY),
                45: int(TextSourcePriority.MAP_SKIN),
            }[binary_layer_priority(source)]
        case ObjectSourceKind.TEXT_STRINGS:
            return int(TextSourcePriority.MAP_TEXT_STRINGS)
        case unreachable:
            assert_never(unreachable)


def source_path(field: ObjectFieldValue) -> str:
    """Join the field container and resolved WTS value source."""
    return (
        field.source
        if not field.value_source
        else f"{field.source} -> {field.value_source}"
    )


def text_evidence_sort_key(
    row: TextEvidence,
) -> tuple[str, str, int, int, str, str, str, str]:
    """Return a primitive stable evidence key."""
    return (
        row.role.casefold(),
        row.semantic_field.casefold(),
        -1 if row.level is None else row.level,
        -row.source_priority,
        row.source_kind,
        row.source_path.casefold(),
        row.field_key.casefold(),
        row.raw_value,
    )
