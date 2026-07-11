"""Collect and materialize object candidates through one deterministic pipeline."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, assert_never

from .base_objects import BASE_OBJECTS
from .map_archive_reader import MapArchiveReader
from .map_data import GameObject, MapData
from .object_candidates import ObjectCandidate, ObjectSourceKind, collect_object_candidates
from .object_materialization import (
    BaseObjectTable,
    build_object_index,
    merge_object_candidates,
    named_base_candidates,
)

if TYPE_CHECKING:
    from .game_data_source import GameDataSource


def populate_object_pipeline(
    md: MapData,
    candidates: Iterable[ObjectCandidate],
    base_objects: BaseObjectTable = BASE_OBJECTS,
    *,
    include_named_bases: bool = True,
) -> None:
    """Replace object buckets and index from one final candidate merge."""
    source_candidates = tuple(candidates)
    all_candidates = source_candidates
    if source_candidates and include_named_bases:
        all_candidates += named_base_candidates(base_objects)
    md.object_source_counts = _object_source_counts(all_candidates)
    objects = merge_object_candidates(all_candidates, base_objects)
    buckets: dict[str, list[GameObject]] = {}
    for item in objects:
        buckets.setdefault(item.category, []).append(item)
    md.objects = buckets
    md.obj_index = build_object_index(objects)


def _object_source_counts(candidates: tuple[ObjectCandidate, ...]) -> dict[str, int]:
    identities: set[tuple[str, str]] = set()
    for candidate in candidates:
        kinds = {field.source_kind for field in candidate.fields}
        if not kinds:
            kinds = {_source_kind_from_ext(candidate.ext)}
        for kind in kinds:
            identities.add((_source_label(kind), candidate.obj_id))
    counts: dict[str, int] = {}
    for label, _obj_id in sorted(identities):
        counts[label] = counts.get(label, 0) + 1
    return counts


def _source_kind_from_ext(ext: str) -> ObjectSourceKind:
    if ext == "slk":
        return ObjectSourceKind.SLK
    if ext == "txt":
        return ObjectSourceKind.TEXT_FUNC
    if ext == "base":
        return ObjectSourceKind.BASE
    return ObjectSourceKind.BINARY


def _source_label(kind: ObjectSourceKind) -> str:
    match kind:
        case ObjectSourceKind.BASE:
            return "base"
        case ObjectSourceKind.SLK:
            return "slk"
        case ObjectSourceKind.TEXT_FUNC | ObjectSourceKind.TEXT_STRINGS:
            return "text"
        case ObjectSourceKind.BINARY:
            return "binary"
        case unreachable:
            assert_never(unreachable)


def load_object_pipeline(
    md: MapData,
    archive: MapArchiveReader,
    wts: Mapping[int, str],
    *,
    prefix: str = "war3map",
    base_objects: BaseObjectTable = BASE_OBJECTS,
    game_data_source: GameDataSource | None = None,
) -> None:
    """Collect and materialize one object-source prefix through the unified pipeline."""
    if game_data_source is not None:
        from .client_object_data import collect_client_base_objects, merge_client_base_objects

        client_objects = collect_client_base_objects(game_data_source)
        base_objects = merge_client_base_objects(base_objects, client_objects)
    candidates = collect_object_candidates(archive, wts, prefix=prefix)
    populate_object_pipeline(md, candidates, base_objects)


def add_base_objects(
    md: MapData,
    base_objects: BaseObjectTable = BASE_OBJECTS,
) -> None:
    """Compatibility path that adds named bases without creating duplicates."""
    existing = build_object_index(item for values in md.objects.values() for item in values)
    additions = merge_object_candidates(named_base_candidates(base_objects), base_objects)
    for item in additions:
        if item.obj_id in existing:
            continue
        md.objects.setdefault(item.category, []).append(item)
        existing[item.obj_id] = item
    md.obj_index = existing
