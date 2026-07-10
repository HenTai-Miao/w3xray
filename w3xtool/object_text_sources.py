"""Discover and merge Warcraft text-format object tables."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from .map_archive_reader import AnonymousTextObjectArchive, MapArchiveReader
from .textobj import classify, looks_like_text_object, parse_text_objects
from .war3_encoding import decode_warcraft_string


class TextObjectSourceKind(StrEnum):
    FUNC = "func"
    STRINGS = "strings"
    ANONYMOUS = "anonymous"


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


_TRUSTED_NAME: Final[re.Pattern[str]] = re.compile(
    r"(?:^|[\\/])(?:[a-z]+)?(?:unit|item|ability|upgrade)(func|strings)\.txt$",
    re.IGNORECASE,
)
_DISPLAY_FIELDS: Final[frozenset[str]] = frozenset(
    {"name", "propernames", "tip", "ubertip", "description", "editorsuffix"},
)
_MAX_TEXT_OBJECT_BYTES: Final = 4 * 1024 * 1024
_ANONYMOUS_HEAD_BYTES: Final = 8 * 1024
_RACES: Final[tuple[str, ...]] = ("Human", "Orc", "Undead", "NightElf", "Neutral")
_TRUSTED_REFERENCE_NAMES: Final[tuple[str, ...]] = (
    "units\\itemfunc.txt",
    "units\\itemstrings.txt",
    "units\\campaignunitfunc.txt",
    "units\\campaignunitstrings.txt",
    "Units\\HumanUnitFunc.txt",
    "Units\\HumanUnitStrings.txt",
    "units\\campaignabilityfunc.txt",
    "units\\campaignabilitystrings.txt",
    "Units\\HumanAbilityFunc.txt",
    "Units\\HumanAbilityStrings.txt",
    "Units\\CampaignUpgradeFunc.txt",
    "Units\\campaignupgradestrings.txt",
    "Units\\HumanUpgradeFunc.txt",
    "Units\\HumanUpgradeStrings.txt",
    "Units\\NeutralUpgradeFunc.txt",
    "Units\\NeutralUpgradeStrings.txt",
) + tuple(
    f"Units\\{race}{object_type}{source}.txt"
    for race in _RACES
    for object_type in ("Unit", "Ability", "Upgrade")
    for source in ("Func", "Strings")
)


def collect_text_object_records(
    archive: MapArchiveReader,
    known_names: Sequence[str] = (),
) -> tuple[TextObjectRecord, ...]:
    """Collect named trusted sources and optional anonymous object-table blocks."""
    records: list[TextObjectRecord] = []
    for name in _trusted_names(archive, known_names):
        kind = _trusted_source_kind(name)
        if kind is None or not archive.has_file(name):
            continue
        try:
            payload = archive.read_file(name)
        except (KeyError, OSError, ValueError):
            continue
        records.extend(_records_from_payload(payload, name, kind, minimum_objects=1))
    if isinstance(archive, AnonymousTextObjectArchive):
        records.extend(_anonymous_records(archive))
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


def _anonymous_records(archive: AnonymousTextObjectArchive) -> tuple[TextObjectRecord, ...]:
    records: list[TextObjectRecord] = []
    for index, block in archive.iter_blocks():
        if block.file_size > _MAX_TEXT_OBJECT_BYTES:
            continue
        try:
            head = archive.peek_block(block, _ANONYMOUS_HEAD_BYTES)[:_ANONYMOUS_HEAD_BYTES]
        except (OSError, ValueError):
            continue
        if not looks_like_text_object(head) or b"name=" not in head.lower():
            continue
        try:
            payload = archive.read_block_anon(block)
        except (OSError, ValueError):
            continue
        if payload is None:
            continue
        records.extend(
            _records_from_payload(
                payload,
                f"anonymous:block:{index:06d}",
                TextObjectSourceKind.ANONYMOUS,
                minimum_objects=8,
            )
        )
    return tuple(records)


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


def _trusted_names(archive: MapArchiveReader, known_names: Sequence[str]) -> tuple[str, ...]:
    candidates: dict[str, str] = {}
    for name in _TRUSTED_REFERENCE_NAMES:
        _add_candidate(candidates, name)
    for name in (*known_names, *archive.list_files()):
        if _trusted_source_kind(name) is not None:
            _add_candidate(candidates, name)
    return tuple(sorted(candidates.values(), key=_source_name_key))


def _add_candidate(candidates: dict[str, str], name: str) -> None:
    normalized = _normalized_name(name)
    previous = candidates.get(normalized)
    if previous is None or _source_name_key(name) < _source_name_key(previous):
        candidates[normalized] = name


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
                _normalized_name(source_name),
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


def _trusted_source_kind(name: str) -> TextObjectSourceKind | None:
    match = _TRUSTED_NAME.search(name)
    if match is None:
        return None
    return TextObjectSourceKind.FUNC if match.group(1).casefold() == "func" else TextObjectSourceKind.STRINGS


def _immutable_mapping(values: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType(dict(values))


def _normalized_name(name: str) -> str:
    return name.replace("/", "\\").casefold()


def _source_name_key(name: str) -> tuple[str, str]:
    return _normalized_name(name), name


def _record_sort_key(record: TextObjectRecord) -> tuple[str, str, str, str, tuple[tuple[str, str], ...]]:
    return (
        record.category.casefold(),
        record.obj_id.casefold(),
        *_source_name_key(record.source_name),
        tuple(sorted(record.fields.items())),
    )
