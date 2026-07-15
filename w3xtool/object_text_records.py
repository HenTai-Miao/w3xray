"""Immutable text-object records and deterministic cross-source merging."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from .object_text_names import TextObjectSourceKind, normalized_name, source_name_key

_DISPLAY_FIELDS: Final = frozenset(
    {"name", "propernames", "tip", "ubertip", "description", "editorsuffix"}
)


@dataclass(frozen=True, slots=True)
class TextObjectRecord:
    category: str
    obj_id: str
    fields: Mapping[str, str]
    field_sources: Mapping[str, str]
    source_name: str
    source_kind: TextObjectSourceKind

    def __post_init__(self) -> None:
        object.__setattr__(self, "fields", _immutable_mapping(self.fields))
        object.__setattr__(
            self,
            "field_sources",
            _immutable_mapping(self.field_sources),
        )


def merge_text_object_records(
    records: Sequence[TextObjectRecord],
) -> tuple[TextObjectRecord, ...]:
    """Merge records per object while preserving deterministic field provenance."""
    grouped: dict[tuple[str, str], list[TextObjectRecord]] = {}
    for record in records:
        grouped.setdefault((record.category, record.obj_id), []).append(record)
    return tuple(
        _merge_group(grouped[key])
        for key in sorted(
            grouped,
            key=lambda item: (item[0].casefold(), item[1].casefold(), item),
        )
    )


def text_object_record_sort_key(
    record: TextObjectRecord,
) -> tuple[str, str, str, str, tuple[tuple[str, str], ...]]:
    return (
        record.category.casefold(),
        record.obj_id.casefold(),
        *source_name_key(record.source_name),
        tuple(sorted(record.fields.items())),
    )


def _merge_group(records: Sequence[TextObjectRecord]) -> TextObjectRecord:
    ordered = tuple(sorted(records, key=text_object_record_sort_key))
    selected: dict[str, tuple[int, str, str, str]] = {}
    for record in ordered:
        for field_name, value in record.fields.items():
            if not value:
                continue
            source_name = record.field_sources.get(field_name, record.source_name)
            candidate = (
                _field_rank(record.source_kind, field_name),
                normalized_name(source_name),
                source_name,
                value,
            )
            previous = selected.get(field_name)
            if previous is None or candidate > previous:
                selected[field_name] = candidate
    representative = ordered[-1]
    fields = {
        name: selected[name][3]
        for name in sorted(selected, key=lambda value: (value.casefold(), value))
    }
    sources = {name: selected[name][2] for name in fields}
    return TextObjectRecord(
        category=representative.category,
        obj_id=representative.obj_id,
        fields=fields,
        field_sources=sources,
        source_name=representative.source_name,
        source_kind=representative.source_kind,
    )


def _field_rank(kind: TextObjectSourceKind, field_name: str) -> int:
    if field_name.casefold() in _DISPLAY_FIELDS:
        return 30 if kind is TextObjectSourceKind.STRINGS else 20
    return 30 if kind is TextObjectSourceKind.FUNC else 20


def _immutable_mapping(values: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType(dict(values))
