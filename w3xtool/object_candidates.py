"""Collect immutable object candidates from every recoverable map source."""

from __future__ import annotations

import struct
from collections.abc import Mapping
from typing import TYPE_CHECKING, Final

from .object_candidate_values import (
    expand_codes as _expand_codes,
    resolved_source_value as _resolved_source_value,
    resolved_value as _resolved_value,
    wts_value_source as _wts_value_source,
)
from .fields import field_type, is_concat_type, label_for
from .extraction_diagnostics import read_component, record_component_parse_issue
from .map_archive_reader import MapArchiveReader
from .object_candidate_models import ObjectCandidate, ObjectFieldValue, ObjectSourceKind
from .references import extract_refs_by_type
from .w3obj import EXT_CATEGORY, parse_object_data, parse_object_data_report

if TYPE_CHECKING:
    from .map_data import MapData


OBJECT_EXTS: Final[tuple[str, ...]] = ("w3u", "w3t", "w3a", "w3q", "w3b", "w3d", "w3h")


def collect_object_candidates(
    archive: MapArchiveReader,
    wts: Mapping[int, str],
    *,
    prefix: str = "war3map",
    md: MapData | None = None,
) -> tuple[ObjectCandidate, ...]:
    """Collect candidates for one binary prefix and shared map text sources."""
    from .object_candidate_text_tables import (
        collect_slk_candidates,
        collect_text_candidates,
    )

    candidates: list[ObjectCandidate] = []
    if prefix == "war3map":
        candidates.extend(collect_text_candidates(archive, wts, md))
        candidates.extend(collect_slk_candidates(archive, wts, md))
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
        except KeyError, OSError, ValueError, struct.error:
            return ()
    category = EXT_CATEGORY.get(ext, ext)
    result: list[ObjectCandidate] = []
    for item in parsed:
        obj_id = (
            item.new_id if item.is_custom and item.new_id.strip("\x00") else item.old_id
        )
        values: list[ObjectFieldValue] = []
        for mod in item.mods:
            label = label_for(mod.field_id)
            key = mod.field_id
            if mod.level:
                label = f"{label} (等级{mod.level})"
                key = f"{key}:{mod.level}"
            raw_value = _resolved_source_value(mod.value, wts)
            value = _resolved_value(mod.value, wts)
            if is_concat_type(mod.field_id):
                value = _expand_codes(value)
            values.append(
                ObjectFieldValue(
                    key,
                    label,
                    value,
                    filename,
                    ObjectSourceKind.BINARY,
                    _wts_value_source(mod.value, wts, prefix),
                    field_type(mod.field_id),
                    raw_value,
                ),
            )
        refs = _refs_tuple(extract_refs_by_type(item.mods, field_type))
        result.append(
            ObjectCandidate(
                category, obj_id, item.old_id, item.is_custom, ext, tuple(values), refs
            )
        )
    return tuple(result)


def _refs_tuple(
    refs: list[tuple[str, list[str]]],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return tuple((label, tuple(codes)) for label, codes in refs)


def _candidate_sort_key(
    candidate: ObjectCandidate,
) -> tuple[
    str,
    str,
    str,
    str,
    int,
    tuple[tuple[str, str, str, str, int, str, str, str], ...],
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
            (
                field.key,
                field.label,
                field.value,
                field.source,
                int(field.source_kind),
                field.value_source,
                field.value_type,
                "" if field.raw_value is None else field.raw_value,
            )
            for field in candidate.fields
        ),
        candidate.refs,
    )
