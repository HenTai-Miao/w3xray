"""Resolve explicit campaign object bases without guessing missing definitions."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace
import json

from .map_data import GameObject
from .object_candidate_models import (
    FieldEvidenceState,
    ObjectCandidate,
    ObjectFieldValue,
    ObjectSourceKind,
)
from .object_codes import valid_object_code
from .object_field_selection import (
    build_selection_index,
    object_field_identity,
    object_field_source_priority,
    select_object_field,
)
from .object_layers import binary_layer_priority
from .object_materialization import (
    BaseObjectTable,
    _materialize,
    _materialized_evidence,
)

type Identity = tuple[str, str]


def inherit_campaign_candidates(
    candidates: Iterable[ObjectCandidate], base_objects: BaseObjectTable
) -> tuple[tuple[ObjectCandidate, ...], tuple[str, ...]]:
    """Resolve category-qualified declared base chains with an explicit stack.

    A missing base describes unavailable inheritance evidence, not damaged
    archive bytes. Own confirmed fields survive every incomplete base chain.
    """
    grouped: dict[Identity, tuple[ObjectCandidate, ...]] = {}
    pending: dict[Identity, list[ObjectCandidate]] = {}
    for candidate in candidates:
        pending.setdefault((candidate.category, candidate.obj_id), []).append(candidate)
    grouped = {identity: tuple(rows) for identity, rows in pending.items()}
    parents: dict[Identity, Identity] = {}
    notes: dict[Identity, tuple[str, ...]] = {}
    for identity, rows in tuple(grouped.items()):
        declared = [row for row in rows if row.source]
        if not declared:
            continue
        priority = max(_declaration_priority(row) for row in declared)
        current = [row for row in declared if _declaration_priority(row) == priority]
        pairs = {(row.base_id, row.is_custom) for row in current}
        if len(pairs) != 1 or not valid_object_code(current[0].base_id):
            notes[identity] = (
                f"{identity[0]}:{identity[1]}: 基础ID/自定义声明冲突或无效；未推断继承字段。"
                + json.dumps(
                    [(row.base_id, row.is_custom, row.source) for row in current],
                    ensure_ascii=False,
                ),
            )
            grouped[identity] = tuple(replace(row, base_id="") for row in rows)
            continue
        parent = (identity[0], current[0].base_id)
        if parent == identity:
            continue
        parents[identity] = parent
        builtin = base_objects.get(parent[1])
        if parent not in grouped and (builtin is None or builtin[0] != parent[0]):
            notes[identity] = (
                f"{identity[0]}:{identity[1]}: 已声明基础ID {parent[1]!r} 未在同类别地图/战役共享/基础目录确认；"
                "继承来源未提供，未补造字段；已读取的本对象字段仍保留。声明来源: "
                + " / ".join(dict.fromkeys(row.source for row in current)),
            )
    resolved: dict[Identity, tuple[ObjectCandidate, ...]] = {}
    objects: dict[Identity, GameObject] = {}
    for first in grouped:
        trail: list[Identity] = []
        positions: dict[Identity, int] = {}
        current = first
        while current in grouped and current not in resolved:
            if current in positions:
                cycle = trail[positions[current] :]
                chain = " -> ".join(
                    f"{kind}:{code}" for kind, code in (*cycle, current)
                )
                for identity in cycle:
                    notes[identity] = (
                        f"{identity[0]}:{identity[1]}: 基础对象声明形成循环: {chain}；未推断循环继承字段。声明来源: "
                        + " / ".join(
                            dict.fromkeys(
                                row.source for row in grouped[identity] if row.source
                            )
                        ),
                    )
                    resolved[identity] = _mark_overridden_inherited_fields(
                        identity[0], grouped[identity]
                    )
                    objects[identity] = _materialize(
                        identity, resolved[identity], base_objects
                    )
                break
            positions[current] = len(trail)
            trail.append(current)
            parent = parents.get(current)
            if parent is None or parent not in grouped:
                break
            current = parent
        for identity in reversed(trail):
            if identity in resolved:
                continue
            rows = grouped[identity]
            parent = parents.get(identity)
            if parent in objects:
                assert parent is not None
                rows = (
                    *rows,
                    _inherited_candidate(identity, objects[parent], resolved[parent]),
                )
                if notes.get(parent):
                    notes[identity] = (
                        *notes.get(identity, ()),
                        *(
                            f"{identity[0]}:{identity[1]}: 继承来源 {parent[0]}:{parent[1]} 不完整: {note}"
                            for note in notes[parent]
                        ),
                    )
            resolved[identity] = _mark_overridden_inherited_fields(identity[0], rows)
            objects[identity] = _materialize(identity, resolved[identity], base_objects)
    return (
        tuple(row for identity in grouped for row in resolved[identity]),
        tuple(note for identity in grouped for note in notes.get(identity, ())),
    )


def _mark_overridden_inherited_fields(
    category: str, candidates: tuple[ObjectCandidate, ...]
) -> tuple[ObjectCandidate, ...]:
    """Keep child overrides in inherited evidence before final materialization.

    Only a strictly higher source tier proves an override. Same-tier evidence
    and unknown/conflicting source states remain available without arbitration.
    """
    inherited_indexes = {
        index
        for index, candidate in enumerate(candidates)
        if candidate.ext == "base" and not candidate.source and candidate.fields
    }
    if not inherited_indexes:
        return candidates
    selected: dict[str, ObjectFieldValue] = {}
    selection_index = build_selection_index()
    for candidate in candidates:
        for value in candidate.fields:
            select_object_field(selected, value, category, selection_index)
    non_base_labels: dict[str, int] = {}
    for value in selected.values():
        if value.source_kind is not ObjectSourceKind.BASE:
            label = value.label.casefold()
            non_base_labels[label] = max(
                non_base_labels.get(label, -1),
                object_field_source_priority(value, category),
            )

    def field(value: ObjectFieldValue) -> ObjectFieldValue:
        if value.state is not FieldEvidenceState.CONFIRMED:
            return value
        identity = object_field_identity(value, category)
        winner = selected.get(identity)
        priority = (
            object_field_source_priority(winner, category)
            if winner is not None
            else non_base_labels.get(value.label.casefold(), -1)
            if value.source_kind is ObjectSourceKind.BASE
            else -1
        )
        if priority > object_field_source_priority(value, category):
            return replace(value, state=FieldEvidenceState.OVERRIDDEN)
        return value

    return tuple(
        replace(candidate, fields=tuple(field(value) for value in candidate.fields))
        if index in inherited_indexes
        else candidate
        for index, candidate in enumerate(candidates)
    )


def shared_scope_candidates(
    declared: Iterable[ObjectCandidate],
    resolved: Iterable[ObjectCandidate],
    objects: Mapping[Identity, GameObject],
    scope: str,
) -> tuple[ObjectCandidate, ...]:
    """Share all root definitions while keeping local chapter fields authoritative.

    Root SLK/Strings/Func and binary files use their ordinary source policy to
    resolve the parent first. The resulting current and overridden evidence is
    inherited together; source layers are still recorded in encoded provenance.
    """
    declarations: dict[Identity, list[ObjectCandidate]] = {}
    values: dict[Identity, list[ObjectCandidate]] = {}
    for row in declared:
        declarations.setdefault((row.category, row.obj_id), []).append(row)
    for row in resolved:
        values.setdefault((row.category, row.obj_id), []).append(row)
    result: list[ObjectCandidate] = []
    for identity, rows in declarations.items():
        inherited = _inherited_candidate(
            identity, objects[identity], tuple(values[identity]), shared_scope=scope
        )
        result.extend(
            replace(
                row,
                fields=(),
                refs=(),
                source=f"{scope}!{row.source}" if row.source else "",
                priority_override=_declaration_priority(row) - 100,
            )
            for row in rows
        )
        result.append(
            replace(
                inherited,
                fields=tuple(
                    replace(
                        field,
                        source=field.source
                        if field.source.startswith("base:")
                        or field.source == "base names"
                        else f"{scope}!{field.source}",
                        value_source=f"{scope}!{field.value_source}"
                        if field.value_source
                        else "",
                    )
                    for field in inherited.fields
                ),
            )
        )
    return tuple(result)


def _declaration_priority(candidate: ObjectCandidate) -> int:
    return (
        candidate.priority_override
        if candidate.priority_override is not None
        else binary_layer_priority(candidate.source)
    )


def _inherited_candidate(
    identity: Identity,
    parent: GameObject,
    candidates: tuple[ObjectCandidate, ...],
    *,
    shared_scope: str = "",
) -> ObjectCandidate:
    original = {
        _materialized_evidence((value,), parent.category)[0]: value
        for candidate in candidates
        for value in candidate.fields
    }
    current_keys = {
        (parent.field_sources.get(key, ""), value, token)
        for key, value in parent.field_values.items()
        for token in (key, parent.field_labels.get(key, key))
    }
    blockers = frozenset(parent.field_blockers)
    inherited = []
    for row in parent.field_evidence:
        active = (
            row in blockers
            or row.state is FieldEvidenceState.CONFIRMED
            and any(
                (row.source, row.value, token) in current_keys
                for token in (row.key, row.label)
            )
        )
        value = original.get(row)
        if value is None:
            value = ObjectFieldValue(
                row.key,
                row.label,
                row.value,
                row.source,
                ObjectSourceKind.BASE,
                row.value_source,
                row.value_type,
                row.raw_value,
                row.state,
                row.diagnostic,
                row.encoded_evidence,
            )
        inherited.append(
            replace(
                value,
                state=row.state if active else FieldEvidenceState.OVERRIDDEN,
                priority_override=12 if active else 11,
                encoded_evidence=_inheritance_evidence(
                    row.encoded_evidence, parent, row.source_priority, shared_scope
                ),
            )
        )
    return ObjectCandidate(
        identity[0],
        identity[1],
        parent.obj_id,
        False,
        "base",
        tuple(inherited),
        tuple((key, tuple(values)) for key, values in parent.ref_fields),
    )


def _inheritance_evidence(
    raw: str, parent: GameObject, priority: int, shared_scope: str = ""
) -> str:
    try:
        parsed: object = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        parsed = {"original_encoded_evidence": raw}
    payload: dict[str, object] = (
        {str(key): value for key, value in parsed.items()}
        if isinstance(parsed, dict)
        else {"original_encoded_evidence": parsed}
    )
    previous = payload.get("gamexray_inheritance", ())
    chain = previous if isinstance(previous, list) else ()
    if shared_scope:
        payload["shared_scope"] = shared_scope
    else:
        payload["gamexray_inheritance"] = [
            *chain,
            {"category": parent.category, "object_id": parent.obj_id},
        ]
    payload.setdefault("original_source_priority", priority)
    return json.dumps(payload, ensure_ascii=True)
