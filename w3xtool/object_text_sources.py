"""Discover and merge Warcraft text-format object tables."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from .extraction_diagnostics import ComponentParseError, read_component, record_component_parse_issue
from .map_archive_reader import AnonymousTextObjectArchive, MapArchiveReader
from .object_text_names import (
    TextObjectSourceKind as TextObjectSourceKind,
    normalized_name,
    source_name_key,
    trusted_names,
    trusted_source_kind,
)
from .textobj import classify, looks_like_text_object, parse_text_objects
from .war3_encoding import decode_warcraft_string

if TYPE_CHECKING:
    from .map_data import MapData


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
        object.__setattr__(self, "field_sources", _immutable_mapping(self.field_sources))


_DISPLAY_FIELDS: Final[frozenset[str]] = frozenset(
    {"name", "propernames", "tip", "ubertip", "description", "editorsuffix"},
)
_MAX_TEXT_OBJECT_BYTES: Final = 4 * 1024 * 1024
_ANONYMOUS_HEAD_BYTES: Final = 8 * 1024


def collect_text_object_records(
    archive: MapArchiveReader,
    known_names: Sequence[str] = (),
    *,
    md: MapData | None = None,
) -> tuple[TextObjectRecord, ...]:
    """Collect named trusted sources and optional anonymous object-table blocks."""
    records: list[TextObjectRecord] = []
    for name in trusted_names(archive, known_names):
        kind = trusted_source_kind(name)
        if kind is None or not archive.has_file(name):
            continue
        if md is not None:
            payload = read_component(
                md,
                "object-text",
                name,
                lambda source=name: archive.read_file(source),
                stage="read",
            )
            if payload is None:
                continue
        else:
            try:
                payload = archive.read_file(name)
            except (KeyError, OSError, ValueError):
                continue
        payload_bytes = payload
        source_kind = kind
        if md is None:
            parsed_records = _records_from_payload(
                payload_bytes,
                name,
                source_kind,
                minimum_objects=1,
            )
        else:
            parsed_result = read_component(
                md,
                "object-text",
                name,
                lambda: _require_named_records(payload_bytes, name, source_kind),
                stage="parse",
            )
            if parsed_result is None:
                continue
            parsed_records, empty_sections = parsed_result
            if empty_sections:
                record_component_parse_issue(
                    md,
                    "object-text",
                    name,
                    f"ignored {empty_sections} object section(s) without fields",
                )
        records.extend(parsed_records)
    if isinstance(archive, AnonymousTextObjectArchive):
        records.extend(_anonymous_records(archive, md))
    return tuple(sorted(records, key=_record_sort_key))


def merge_text_object_records(
    records: Sequence[TextObjectRecord],
) -> tuple[TextObjectRecord, ...]:
    """Merge records per object while preserving deterministic field provenance."""
    grouped: dict[tuple[str, str], list[TextObjectRecord]] = {}
    for record in records:
        grouped.setdefault((record.category, record.obj_id), []).append(record)
    return tuple(
        _merge_group(grouped[key])
        for key in sorted(grouped, key=lambda item: (item[0].casefold(), item[1].casefold(), item))
    )


def _anonymous_records(
    archive: AnonymousTextObjectArchive,
    md: MapData | None,
) -> tuple[TextObjectRecord, ...]:
    records: list[TextObjectRecord] = []
    for index, block in archive.iter_blocks():
        if block.file_size > _MAX_TEXT_OBJECT_BYTES:
            continue
        source_name = f"anonymous:block:{index:06d}"
        if md is not None:
            head_result = read_component(
                md,
                "object-text",
                source_name,
                lambda: archive.peek_block(block, _ANONYMOUS_HEAD_BYTES)[:_ANONYMOUS_HEAD_BYTES],
                stage="probe",
            )
            if head_result is None:
                continue
            head = head_result
        else:
            try:
                head = archive.peek_block(block, _ANONYMOUS_HEAD_BYTES)[:_ANONYMOUS_HEAD_BYTES]
            except (OSError, ValueError):
                continue
        if not looks_like_text_object(head) or b"name=" not in head.lower():
            continue
        if md is not None:
            payload = read_component(
                md,
                "object-text",
                source_name,
                lambda: archive.read_block_anon(block),
                stage="read",
            )
        else:
            try:
                payload = archive.read_block_anon(block)
            except (OSError, ValueError):
                continue
        if payload is None:
            continue
        payload_bytes = payload
        if md is None:
            parsed_records = _records_from_payload(
                payload_bytes,
                source_name,
                TextObjectSourceKind.ANONYMOUS,
                minimum_objects=8,
            )
        else:
            parsed_records = read_component(
                md,
                "object-text",
                source_name,
                lambda: _records_from_payload(
                    payload_bytes,
                    source_name,
                    TextObjectSourceKind.ANONYMOUS,
                    minimum_objects=8,
                ),
                stage="parse",
            ) or ()
        records.extend(parsed_records)
    return tuple(records)


def _require_named_records(
    payload: bytes,
    source_name: str,
    source_kind: TextObjectSourceKind,
) -> tuple[tuple[TextObjectRecord, ...], int]:
    records = _records_from_payload(payload, source_name, source_kind, minimum_objects=1)
    if payload.strip() and not records:
        raise ComponentParseError(f"no valid object sections in {source_name}")
    sections = parse_text_objects(decode_warcraft_string(payload))
    return records, sum(not fields for _obj_id, fields in sections)


def _records_from_payload(
    payload: bytes,
    source_name: str,
    source_kind: TextObjectSourceKind,
    *,
    minimum_objects: int,
) -> tuple[TextObjectRecord, ...]:
    if len(payload) > _MAX_TEXT_OBJECT_BYTES:
        return ()
    objects = tuple((obj_id, fields) for obj_id, fields in parse_text_objects(decode_warcraft_string(payload)) if fields)
    if len(objects) < minimum_objects:
        return ()
    category = classify(
        [obj_id for obj_id, _fields in objects],
        {field_name for _obj_id, fields in objects for field_name in fields},
    )
    return tuple(
        TextObjectRecord(
            category=category,
            obj_id=obj_id,
            fields=_immutable_mapping(fields),
            field_sources=_immutable_mapping({field_name: source_name for field_name in fields}),
            source_name=source_name,
            source_kind=source_kind,
        )
        for obj_id, fields in objects
    )


def _merge_group(records: Sequence[TextObjectRecord]) -> TextObjectRecord:
    ordered = tuple(sorted(records, key=_record_sort_key))
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
    fields = {name: selected[name][3] for name in sorted(selected, key=lambda value: (value.casefold(), value))}
    sources = {name: selected[name][2] for name in fields}
    return TextObjectRecord(
        category=representative.category,
        obj_id=representative.obj_id,
        fields=_immutable_mapping(fields),
        field_sources=_immutable_mapping(sources),
        source_name=representative.source_name,
        source_kind=representative.source_kind,
    )


def _field_rank(kind: TextObjectSourceKind, field_name: str) -> int:
    if field_name.casefold() in _DISPLAY_FIELDS:
        return 30 if kind is TextObjectSourceKind.STRINGS else 20
    return 30 if kind is TextObjectSourceKind.FUNC else 20


def _immutable_mapping(values: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType(dict(values))


def _record_sort_key(record: TextObjectRecord) -> tuple[str, str, str, str, tuple[tuple[str, str], ...]]:
    return (
        record.category.casefold(),
        record.obj_id.casefold(),
        *source_name_key(record.source_name),
        tuple(sorted(record.fields.items())),
    )
