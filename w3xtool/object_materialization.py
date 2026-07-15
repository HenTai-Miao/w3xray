"""Materialize normalized object candidates into public map objects."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Final

from .base_names import BASE_NAMES
from .map_data import GameObject, GameObjectFieldEvidence
from .object_candidates import ObjectCandidate, ObjectFieldValue, ObjectSourceKind
from .object_field_selection import (
    object_field_source_priority,
    public_object_field_key,
    select_object_field,
    selected_display_value,
)

BaseObjectTable = Mapping[str, tuple[str, Sequence[tuple[str, str]]]]

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
        _ = index.setdefault(item.obj_id, item)
    return index


def build_object_identity_index(
    objects: Iterable[GameObject],
) -> dict[tuple[str, str], GameObject]:
    """Index final objects by exact category and rawcode identity."""
    index: dict[tuple[str, str], GameObject] = {}
    for item in objects:
        _ = index.setdefault((item.category, item.obj_id), item)
    return index


def merge_object_candidates(
    candidates: Iterable[ObjectCandidate],
    base_objects: BaseObjectTable,
) -> tuple[GameObject, ...]:
    """Merge every candidate by category and object id in deterministic order."""
    grouped: dict[tuple[str, str], list[ObjectCandidate]] = {}
    for candidate in candidates:
        grouped.setdefault((candidate.category, candidate.obj_id), []).append(candidate)
    keys = sorted(
        grouped,
        key=lambda item: (item[0].casefold(), item[1].encode("latin-1", "replace")),
    )
    return tuple(_materialize(key, tuple(grouped[key]), base_objects) for key in keys)


def named_base_candidates(base_objects: BaseObjectTable) -> tuple[ObjectCandidate, ...]:
    """Build displayable candidates for bundled bases that have known names."""
    result: list[ObjectCandidate] = []
    for code, (category, fields) in sorted(base_objects.items()):
        name = BASE_NAMES.get(code)
        if not name:
            continue
        values = [
            ObjectFieldValue(
                "display:name", "名称", name, "base names", ObjectSourceKind.BASE
            )
        ]
        values.extend(
            ObjectFieldValue(
                f"base:{label}",
                label,
                str(value),
                f"base:{code}",
                ObjectSourceKind.BASE,
            )
            for label, value in fields
        )
        result.append(
            ObjectCandidate(category, code, code, False, "base", tuple(values), ())
        )
    return tuple(result)


def _materialize(
    identity: tuple[str, str],
    candidates: tuple[ObjectCandidate, ...],
    base_objects: BaseObjectTable,
) -> GameObject:
    category, obj_id = identity
    representative = max(candidates, key=_candidate_identity_rank)
    selected: dict[str, ObjectFieldValue] = {}
    evidence_values: list[ObjectFieldValue] = []
    inherited = base_objects.get(representative.base_id)
    if inherited is not None and inherited[0] == category:
        for label, value in inherited[1]:
            base_field = ObjectFieldValue(
                f"base:{label}",
                label,
                str(value),
                f"base:{representative.base_id}",
                ObjectSourceKind.BASE,
            )
            evidence_values.append(base_field)
            select_object_field(selected, base_field, category)
    for candidate in candidates:
        for value in candidate.fields:
            evidence_values.append(value)
            select_object_field(selected, value, category)
    ordered = tuple(
        sorted(selected.items(), key=lambda item: (item[1].label.casefold(), item[0]))
    )
    fields = [(value.label, value.value) for _identity, value in ordered]
    field_values = {
        public_object_field_key(identity, value): value.value
        for identity, value in ordered
    }
    field_labels = {
        public_object_field_key(identity, value): value.label
        for identity, value in ordered
    }
    field_sources = {
        public_object_field_key(identity, value): value.source
        for identity, value in ordered
    }
    name = selected_display_value(selected, "display:name") or selected_display_value(
        selected, "display:propernames"
    )
    if not name:
        name = (
            BASE_NAMES.get(representative.base_id) or BASE_NAMES.get(obj_id) or obj_id
        )
    name = name.split("\n", 1)[0][:60]
    selected_icon = selected.get("display:icon")
    icon = "" if selected_icon is None else selected_icon.value.split(",", 1)[0].strip()
    icon_evidence = (
        None
        if selected_icon is None
        else _materialized_evidence((selected_icon,), category)[0]
    )
    refs = _merge_refs(candidates)
    search_text = " ".join(
        (obj_id, representative.base_id, name, *(value for _label, value in fields))
    )
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
        field_labels=field_labels,
        field_sources=field_sources,
        field_evidence=_materialized_evidence(evidence_values, category),
        icon_field_evidence=icon_evidence,
    )


def _materialized_evidence(
    values: Iterable[ObjectFieldValue],
    category: str,
) -> tuple[GameObjectFieldEvidence, ...]:
    unique = {
        GameObjectFieldEvidence(
            key=value.key,
            label=value.label,
            value=value.value,
            source=value.source,
            source_priority=object_field_source_priority(value, category),
            value_type=value.value_type,
            raw_value=value.raw_value,
            value_source=value.value_source,
        )
        for value in values
    }
    return tuple(
        sorted(
            unique,
            key=lambda row: (
                row.key.casefold(),
                row.key,
                -row.source_priority,
                row.source.casefold(),
                row.source,
                row.value,
                row.label.casefold(),
                row.label,
                row.value_type.casefold(),
                row.value_type,
                row.raw_value is not None,
                "" if row.raw_value is None else row.raw_value,
                row.value_source.casefold(),
                row.value_source,
            ),
        )
    )


def _candidate_identity_rank(
    candidate: ObjectCandidate,
) -> tuple[int, int, bool, str, str]:
    source_rank = max((int(value.source_kind) for value in candidate.fields), default=0)
    return (
        _EXT_RANK.get(candidate.ext, 20),
        source_rank,
        candidate.base_id != candidate.obj_id,
        candidate.base_id,
        candidate.ext,
    )


def _merge_refs(candidates: tuple[ObjectCandidate, ...]) -> list[tuple[str, list[str]]]:
    edges = {
        (label, code)
        for candidate in candidates
        for label, codes in candidate.refs
        for code in codes
        if code
    }
    grouped: dict[str, list[str]] = {}
    for label, code in sorted(
        edges, key=lambda item: (item[0].casefold(), item[0], item[1])
    ):
        grouped.setdefault(label, []).append(code)
    return [(label, grouped[label]) for label in grouped]
