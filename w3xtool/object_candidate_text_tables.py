"""Collect object candidates from text tables and embedded SLK tables."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, assert_never

from .fields import field_type
from .object_candidate_models import ObjectCandidate, ObjectFieldValue, ObjectSourceKind
from .object_candidate_values import (
    resolved_source_value,
    resolved_value,
    retain_field,
    wts_value_source,
)
from .object_text_sources import TextObjectSourceKind, collect_text_object_records
from .references import extract_refs_by_column
from .slk_objects import (
    SLK_CATEGORY_FILES,
    is_noise_col,
    parse_category_objects,
    slk_col_label,
)

if TYPE_CHECKING:
    from .map_archive_reader import MapArchiveReader
    from .map_data import MapData


def collect_text_candidates(
    archive: MapArchiveReader,
    wts: Mapping[int, str],
    md: MapData | None,
) -> tuple[ObjectCandidate, ...]:
    """Collect candidates from trusted and bounded anonymous text tables."""
    result: list[ObjectCandidate] = []
    for record in collect_text_object_records(archive, md=md):
        resolved = {
            key: resolved_value(value, wts) for key, value in record.fields.items()
        }
        fields = tuple(
            ObjectFieldValue(
                key,
                slk_col_label(key),
                value,
                record.field_sources.get(key, record.source_name),
                _text_source_kind(record.source_kind),
                wts_value_source(record.fields[key], wts, "war3map"),
                field_type(key),
                resolved_source_value(record.fields[key], wts),
            )
            for key, value in sorted(
                resolved.items(),
                key=lambda item: (item[0].casefold(), item[0]),
            )
            if retain_field(
                record.category,
                key,
                slk_col_label(key),
                value,
                field_type(key),
            )
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


def collect_slk_candidates(
    archive: MapArchiveReader,
    wts: Mapping[int, str],
    md: MapData | None,
) -> tuple[ObjectCandidate, ...]:
    """Collect candidates from every supported embedded SLK family."""
    result: list[ObjectCandidate] = []
    source = "war3map *Data.slk"
    for category in SLK_CATEGORY_FILES:
        for code, row in sorted(
            parse_category_objects(archive, category, md=md).items()
        ):
            resolved = {key: resolved_value(value, wts) for key, value in row.items()}
            fields = tuple(
                ObjectFieldValue(
                    key,
                    slk_col_label(key),
                    value,
                    source,
                    ObjectSourceKind.SLK,
                    wts_value_source(row[key], wts, "war3map"),
                    field_type(key),
                    resolved_source_value(row[key], wts),
                )
                for key, value in sorted(
                    resolved.items(),
                    key=lambda item: (item[0].casefold(), item[0]),
                )
                if not is_noise_col(key, category)
                and retain_field(
                    category,
                    key,
                    slk_col_label(key),
                    value,
                    field_type(key),
                )
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


def _text_source_kind(kind: TextObjectSourceKind) -> ObjectSourceKind:
    match kind:
        case TextObjectSourceKind.FUNC:
            return ObjectSourceKind.TEXT_FUNC
        case TextObjectSourceKind.STRINGS:
            return ObjectSourceKind.TEXT_STRINGS
        case TextObjectSourceKind.ANONYMOUS:
            return ObjectSourceKind.TEXT_ANONYMOUS
        case unreachable:
            assert_never(unreachable)


def _refs_tuple(
    refs: list[tuple[str, list[str]]],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return tuple((label, tuple(codes)) for label, codes in refs)
