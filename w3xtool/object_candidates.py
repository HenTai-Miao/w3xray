"""Collect immutable object candidates from every recoverable map source."""

from __future__ import annotations

import struct
from collections.abc import Mapping
from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING, Final, assert_never

from .base_names import BASE_NAMES
from .fields import field_type, is_concat_type, label_for
from .extraction_diagnostics import read_component, record_component_parse_issue
from .map_archive_reader import MapArchiveReader
from .object_text_sources import TextObjectSourceKind, collect_text_object_records
from .references import extract_refs_by_column, extract_refs_by_type
from .slk_objects import SLK_CATEGORY_FILES, is_noise_col, parse_category_objects, slk_col_label
from .textobj import _sub_westring
from .w3obj import EXT_CATEGORY, parse_object_data, parse_object_data_report
from .wts import resolve

if TYPE_CHECKING:
    from .map_data import MapData


class ObjectSourceKind(IntEnum):
    BASE = 10
    SLK = 20
    TEXT_FUNC = 30
    BINARY = 40
    TEXT_STRINGS = 50


@dataclass(frozen=True, slots=True)
class ObjectFieldValue:
    key: str
    label: str
    value: str
    source: str
    source_kind: ObjectSourceKind


@dataclass(frozen=True, slots=True)
class ObjectCandidate:
    category: str
    obj_id: str
    base_id: str
    is_custom: bool
    ext: str
    fields: tuple[ObjectFieldValue, ...]
    refs: tuple[tuple[str, tuple[str, ...]], ...]


OBJECT_EXTS: Final[tuple[str, ...]] = ("w3u", "w3t", "w3a", "w3q", "w3b", "w3d", "w3h")
ICON_FIELDS: Final[Mapping[str, str]] = {
    "w3u": "uico",
    "w3t": "iico",
    "w3a": "aart",
    "w3q": "gar1",
    "w3h": "fart",
    "w3b": "bgsc",
    "w3d": "dfil",
}
_DISPLAY_TEXT_FIELDS: Final[frozenset[str]] = frozenset(
    {"name", "propernames", "tip", "ubertip", "description", "art", "icon", "ico"}
)


def collect_object_candidates(
    archive: MapArchiveReader,
    wts: Mapping[int, str],
    *,
    prefix: str = "war3map",
    md: MapData | None = None,
) -> tuple[ObjectCandidate, ...]:
    """Collect candidates for one binary prefix and shared map text sources."""
    candidates: list[ObjectCandidate] = []
    if prefix == "war3map":
        candidates.extend(_collect_text_candidates(archive, wts, md))
        candidates.extend(_collect_slk_candidates(archive, wts, md))
    for ext in OBJECT_EXTS:
        candidates.extend(
            collect_binary_object_candidates(archive, wts, ext, prefix=prefix, md=md),
        )
    return tuple(sorted(candidates, key=_candidate_sort_key))


def collect_binary_object_candidates(
    archive: MapArchiveReader,
    wts: Mapping[int, str],
    ext: str,
    *,
    prefix: str = "war3map",
    md: MapData | None = None,
) -> tuple[ObjectCandidate, ...]:
    """Parse one binary object file without affecting candidates from other sources."""
    filename = f"{prefix}.{ext}"
    if not archive.has_file(filename):
        return ()
    if md is not None:
        payload = read_component(
            md,
            "object-binary",
            filename,
            lambda: archive.read_file(filename),
            stage="read",
        )
        if payload is None:
            return ()
        report = parse_object_data_report(payload, ext)
        for issue in report.issues:
            record_component_parse_issue(md, "object-binary", filename, issue)
        parsed = report.objects
    else:
        try:
            parsed = parse_object_data(archive.read_file(filename), ext)
        except (KeyError, OSError, ValueError, struct.error):
            return ()
    category = EXT_CATEGORY.get(ext, ext)
    result: list[ObjectCandidate] = []
    for item in parsed:
        obj_id = item.new_id if item.is_custom and item.new_id.strip("\x00") else item.old_id
        values: list[ObjectFieldValue] = []
        for mod in item.mods:
            label = label_for(mod.field_id)
            key = mod.field_id
            if mod.level:
                label = f"{label} (等级{mod.level})"
                key = f"{key}:{mod.level}"
            value = _resolved_value(mod.value, wts)
            if is_concat_type(mod.field_id):
                value = _expand_codes(value)
            values.append(ObjectFieldValue(key, label, value, filename, ObjectSourceKind.BINARY))
        refs = _refs_tuple(extract_refs_by_type(item.mods, field_type))
        result.append(
            ObjectCandidate(category, obj_id, item.old_id, item.is_custom, ext, tuple(values), refs)
        )
    return tuple(result)


def _collect_text_candidates(
    archive: MapArchiveReader,
    wts: Mapping[int, str],
    md: MapData | None,
) -> tuple[ObjectCandidate, ...]:
    result: list[ObjectCandidate] = []
    for record in collect_text_object_records(archive, md=md):
        resolved = {key: _resolved_value(value, wts) for key, value in record.fields.items()}
        fields = tuple(
            ObjectFieldValue(
                key,
                slk_col_label(key),
                value,
                record.field_sources.get(key, record.source_name),
                _text_source_kind(record.source_kind, key),
            )
            for key, value in sorted(resolved.items(), key=lambda item: (item[0].casefold(), item[0]))
            if value
        )
        result.append(
            ObjectCandidate(
                record.category,
                record.obj_id,
                record.obj_id,
                True,
                "txt",
                fields,
                _refs_tuple(extract_refs_by_column(resolved, record.category)),
            )
        )
    return tuple(result)


def _collect_slk_candidates(
    archive: MapArchiveReader,
    wts: Mapping[int, str],
    md: MapData | None,
) -> tuple[ObjectCandidate, ...]:
    result: list[ObjectCandidate] = []
    source = "war3map *Data.slk"
    for category in SLK_CATEGORY_FILES:
        for code, row in sorted(parse_category_objects(archive, category, md=md).items()):
            resolved = {key: _resolved_value(value, wts) for key, value in row.items()}
            fields = tuple(
                ObjectFieldValue(key, slk_col_label(key), value, source, ObjectSourceKind.SLK)
                for key, value in sorted(resolved.items(), key=lambda item: (item[0].casefold(), item[0]))
                if value and not is_noise_col(key, category)
            )
            result.append(
                ObjectCandidate(
                    category,
                    code,
                    code,
                    True,
                    "slk",
                    fields,
                    _refs_tuple(extract_refs_by_column(resolved, category)),
                )
            )
    return tuple(result)


def _text_source_kind(kind: TextObjectSourceKind, field_name: str) -> ObjectSourceKind:
    match kind:
        case TextObjectSourceKind.FUNC:
            return ObjectSourceKind.TEXT_FUNC
        case TextObjectSourceKind.STRINGS:
            return ObjectSourceKind.TEXT_STRINGS
        case TextObjectSourceKind.ANONYMOUS:
            return (
                ObjectSourceKind.TEXT_STRINGS
                if field_name.casefold() in _DISPLAY_TEXT_FIELDS
                else ObjectSourceKind.TEXT_FUNC
            )
        case unreachable:
            assert_never(unreachable)


def _resolved_value(value: int | float | str, wts: Mapping[int, str]) -> str:
    resolved = resolve(value, wts)
    if isinstance(resolved, float):
        formatted = str(int(resolved)) if resolved.is_integer() else f"{resolved:.4g}"
    else:
        formatted = str(resolved)
    return _sub_westring(formatted)


def _expand_codes(value: str) -> str:
    if "," not in value:
        return value
    parts = tuple(part.strip() for part in value.split(","))
    return ", ".join(f"{BASE_NAMES[part]}({part})" if part in BASE_NAMES else part for part in parts)


def _refs_tuple(refs: list[tuple[str, list[str]]]) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return tuple((label, tuple(codes)) for label, codes in refs)


def _candidate_sort_key(
    candidate: ObjectCandidate,
) -> tuple[
    str,
    str,
    str,
    str,
    int,
    tuple[tuple[str, str, str, str, int], ...],
    tuple[tuple[str, tuple[str, ...]], ...],
]:
    """Return a fully primitive sort key for deterministic collection."""
    return (
        candidate.category.casefold(),
        candidate.obj_id,
        candidate.ext,
        candidate.base_id,
        int(candidate.is_custom),
        tuple(
            (field.key, field.label, field.value, field.source, int(field.source_kind))
            for field in candidate.fields
        ),
        candidate.refs,
    )
