"""Deterministically merge object candidates into final public objects."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Final

from .base_names import BASE_NAMES
from .base_objects import BASE_OBJECTS
from .map_archive_reader import MapArchiveReader
from .map_data import GameObject, MapData
from .object_candidates import (
    ObjectCandidate,
    ObjectFieldValue,
    ObjectSourceKind,
    collect_object_candidates,
)

BaseObjectTable = Mapping[str, tuple[str, Sequence[tuple[str, str]]]]

_DISPLAY_ALIASES: Final[Mapping[str, str]] = {
    "name": "display:name",
    "unam": "display:name",
    "anam": "display:name",
    "gnam": "display:name",
    "bnam": "display:name",
    "dnam": "display:name",
    "fnam": "display:name",
    "propernames": "display:propernames",
    "tip": "display:tip",
    "ubertip": "display:description",
    "description": "display:description",
    "icon": "display:icon",
    "art": "display:icon",
    "ico": "display:icon",
    "uico": "display:icon",
    "iico": "display:icon",
    "aart": "display:icon",
    "aical": "display:icon",
    "gico": "display:icon",
    "gar1": "display:icon",
    "fart": "display:icon",
    "bgsc": "display:icon",
    "dfil": "display:icon",
}
_NON_DISPLAY_ALIASES: Final[Mapping[str, str]] = {
    "hp": "field:unit:hit-points",
    "hitpoints": "field:unit:hit-points",
    "uhpm": "field:unit:hit-points",
}
_EXT_RANK: Final[Mapping[str, int]] = {
    "base": 0,
    "slk": 10,
    "txt": 20,
    "w3u": 30,
    "w3t": 30,
    "w3a": 30,
    "w3q": 30,
    "w3b": 30,
    "w3d": 30,
    "w3h": 30,
}


def build_object_index(objects: Iterable[GameObject]) -> dict[str, GameObject]:
    """Index only final object ids, never custom-object base aliases."""
    index: dict[str, GameObject] = {}
    for item in objects:
        index.setdefault(item.obj_id, item)
    return index


def merge_object_candidates(
    candidates: Iterable[ObjectCandidate],
    base_objects: BaseObjectTable,
) -> tuple[GameObject, ...]:
    """Merge every candidate by category and object id in deterministic order."""
    grouped: dict[tuple[str, str], list[ObjectCandidate]] = {}
    for candidate in candidates:
        grouped.setdefault((candidate.category, candidate.obj_id), []).append(candidate)
    keys = sorted(grouped, key=lambda item: (item[0].casefold(), item[1].encode("latin-1", "replace")))
    return tuple(_materialize(key, tuple(grouped[key]), base_objects) for key in keys)


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
        all_candidates += _named_base_candidates(base_objects)
    objects = merge_object_candidates(all_candidates, base_objects)
    buckets: dict[str, list[GameObject]] = {}
    for item in objects:
        buckets.setdefault(item.category, []).append(item)
    md.objects = buckets
    md.obj_index = build_object_index(objects)


def load_object_pipeline(
    md: MapData,
    archive: MapArchiveReader,
    wts: Mapping[int, str],
    *,
    prefix: str = "war3map",
    base_objects: BaseObjectTable = BASE_OBJECTS,
) -> None:
    """Collect and materialize one object-source prefix through the unified pipeline."""
    candidates = collect_object_candidates(archive, wts, prefix=prefix)
    populate_object_pipeline(md, candidates, base_objects)


def add_base_objects(
    md: MapData,
    base_objects: BaseObjectTable = BASE_OBJECTS,
) -> None:
    """Compatibility path that adds named bases without creating duplicates."""
    existing = build_object_index(item for values in md.objects.values() for item in values)
    additions = merge_object_candidates(_named_base_candidates(base_objects), base_objects)
    for item in additions:
        if item.obj_id in existing:
            continue
        md.objects.setdefault(item.category, []).append(item)
        existing[item.obj_id] = item
    md.obj_index = existing


def _materialize(
    identity: tuple[str, str],
    candidates: tuple[ObjectCandidate, ...],
    base_objects: BaseObjectTable,
) -> GameObject:
    category, obj_id = identity
    representative = max(candidates, key=_candidate_identity_rank)
    selected: dict[str, ObjectFieldValue] = {}
    inherited = base_objects.get(representative.base_id)
    if inherited is not None and inherited[0] == category:
        for label, value in inherited[1]:
            base_field = ObjectFieldValue(
                f"base:{label}", label, str(value), f"base:{representative.base_id}", ObjectSourceKind.BASE
            )
            _select_field(selected, base_field)
    for candidate in candidates:
        for value in candidate.fields:
            if value.value:
                _select_field(selected, value)
    ordered = tuple(sorted(selected.items(), key=lambda item: (item[1].label.casefold(), item[0])))
    fields = [(value.label, value.value) for _identity, value in ordered]
    field_values = {_public_field_key(identity, value): value.value for identity, value in ordered}
    field_sources = {_public_field_key(identity, value): value.source for identity, value in ordered}
    name = _display_value(selected, "display:name") or _display_value(selected, "display:propernames")
    if not name:
        name = BASE_NAMES.get(representative.base_id) or BASE_NAMES.get(obj_id) or obj_id
    name = name.split("\n", 1)[0][:60]
    icon = _display_value(selected, "display:icon").split(",", 1)[0].strip()
    refs = _merge_refs(candidates)
    search_text = " ".join((obj_id, representative.base_id, name, *(value for _label, value in fields)))
    return GameObject(
        category=category,
        ext=representative.ext,
        obj_id=obj_id,
        base_id=representative.base_id,
        name=name,
        is_custom=any(candidate.is_custom for candidate in candidates),
        fields=fields,
        search_text=search_text,
        icon=icon,
        ref_fields=refs,
        field_values=field_values,
        field_sources=field_sources,
    )


def _select_field(selected: dict[str, ObjectFieldValue], value: ObjectFieldValue) -> None:
    identity = _field_identity(value)
    previous = selected.get(identity)
    if previous is None or _field_rank(value, identity) > _field_rank(previous, identity):
        selected[identity] = value


def _field_identity(value: ObjectFieldValue) -> str:
    key = value.key.casefold()
    alias = _DISPLAY_ALIASES.get(key)
    if alias is None and key.startswith("display:"):
        alias = key
    non_display_key = key.removeprefix("binary:")
    return alias or _NON_DISPLAY_ALIASES.get(non_display_key) or f"field:{value.label.casefold()}"


def _public_field_key(identity: str, value: ObjectFieldValue) -> str:
    return identity if identity.startswith("display:") else value.key


def _field_rank(
    value: ObjectFieldValue,
    identity: str,
) -> tuple[int, str, str, str, str, str, str, str, str]:
    priority = int(value.source_kind)
    if value.source_kind is ObjectSourceKind.TEXT_STRINGS and not identity.startswith("display:"):
        priority = 15
    normalized_source = value.source.replace("/", "\\")
    return (
        priority,
        normalized_source.casefold(),
        normalized_source,
        value.source,
        value.key.casefold(),
        value.key,
        value.label.casefold(),
        value.label,
        value.value,
    )


def _candidate_identity_rank(candidate: ObjectCandidate) -> tuple[int, int, str, str, str]:
    source_rank = max((int(value.source_kind) for value in candidate.fields), default=0)
    return (
        _EXT_RANK.get(candidate.ext, 20),
        source_rank,
        candidate.base_id != candidate.obj_id,
        candidate.base_id,
        candidate.ext,
    )


def _display_value(selected: Mapping[str, ObjectFieldValue], identity: str) -> str:
    value = selected.get(identity)
    return "" if value is None else value.value


def _merge_refs(candidates: tuple[ObjectCandidate, ...]) -> list[tuple[str, list[str]]]:
    edges = {
        (label, code)
        for candidate in candidates
        for label, codes in candidate.refs
        for code in codes
        if code
    }
    grouped: dict[str, list[str]] = {}
    for label, code in sorted(edges, key=lambda item: (item[0].casefold(), item[0], item[1])):
        grouped.setdefault(label, []).append(code)
    return [(label, grouped[label]) for label in grouped]


def _named_base_candidates(base_objects: BaseObjectTable) -> tuple[ObjectCandidate, ...]:
    result: list[ObjectCandidate] = []
    for code, (category, fields) in sorted(base_objects.items()):
        name = BASE_NAMES.get(code)
        if not name:
            continue
        values = [ObjectFieldValue("display:name", "名称", name, "base names", ObjectSourceKind.BASE)]
        values.extend(
            ObjectFieldValue(f"base:{label}", label, str(value), f"base:{code}", ObjectSourceKind.BASE)
            for label, value in fields
        )
        result.append(ObjectCandidate(category, code, code, False, "base", tuple(values), ()))
    return tuple(result)
