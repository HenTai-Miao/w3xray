"""Immutable complete object-text evidence and indexes."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final


class ObjectTextState(StrEnum):
    """Resolution state for one object-text role and level."""

    MAP_VALUE = "地图原值"
    CLIENT_FILL = "客户端补全"
    CACHE_FILL = "可信缓存补全"
    MAP_EXPLICIT_EMPTY = "作者明确清空"
    AUTHOR_UNDEFINED = "作者未定义"
    SOURCE_UNAVAILABLE = "源数据不可用"
    SOURCE_CONFLICT = "来源冲突"


@dataclass(frozen=True, slots=True)
class ObjectTextRecord:
    """One lossless source variant for an object text role."""

    category: str
    object_id: str
    base_id: str
    object_name: str
    is_custom: bool
    role: str
    field_key: str
    field_label: str
    level: int | None
    raw_value: str
    readable_value: str
    source_kind: str
    source_path: str
    state: ObjectTextState
    placeholder: bool
    conflict_group: str
    evidence_ordinal: int


@dataclass(frozen=True, slots=True)
class ObjectTextIndex:
    """Stable immutable complete-text rows with object reverse lookup."""

    records: tuple[ObjectTextRecord, ...]
    _by_object: Mapping[tuple[str, str], tuple[ObjectTextRecord, ...]]

    @classmethod
    def build(cls, records: Iterable[ObjectTextRecord]) -> ObjectTextIndex:
        """Sort records and build immutable object lookup tables."""
        ordered = tuple(sorted(records, key=_record_sort_key))
        grouped: dict[tuple[str, str], list[ObjectTextRecord]] = {}
        for record in ordered:
            grouped.setdefault((record.category, record.object_id), []).append(record)
        by_object = MappingProxyType(
            {identity: tuple(values) for identity, values in grouped.items()},
        )
        return cls(records=ordered, _by_object=by_object)

    def for_object(
        self,
        category: str,
        object_id: str,
    ) -> tuple[ObjectTextRecord, ...]:
        """Return every text row for one exact category/object identity."""
        return self._by_object.get((category, object_id), ())

    def counts_by_state(self) -> Mapping[ObjectTextState, int]:
        """Count rows per state in enum declaration order."""
        counts = Counter(record.state for record in self.records)
        return MappingProxyType(
            {state: counts[state] for state in ObjectTextState if counts[state]},
        )


def _record_sort_key(
    record: ObjectTextRecord,
) -> tuple[str, bytes, str, int, str, str, str, int]:
    level = -1 if record.level is None else record.level
    return (
        record.category.casefold(),
        record.object_id.encode("latin-1", "replace"),
        record.role.casefold(),
        level,
        record.field_key.casefold(),
        record.source_path.casefold(),
        record.raw_value,
        record.evidence_ordinal,
    )


_EMPTY_INDEX: Final = ObjectTextIndex.build(())


def empty_object_text_index() -> ObjectTextIndex:
    """Return the shared empty immutable index."""
    return _EMPTY_INDEX
