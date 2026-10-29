"""Campaign reference inheritance with explicit scope and override evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from .object_candidate_models import ObjectFieldValue, ObjectSourceKind
from .object_field_selection import object_field_identity
from .reference_models import ReferenceRecord, ReferenceValue


def _field_identity(value: ReferenceValue, category: str) -> str:
    return object_field_identity(
        ObjectFieldValue(
            value.key,
            value.label,
            value.value,
            value.provenance,
            ObjectSourceKind.BASE
            if value.source.startswith("builtin:")
            else ObjectSourceKind.BINARY,
            value_type=value.value_type,
        ),
        category,
    )


def demote_builtin_fields(
    record: ReferenceRecord, overriding: tuple[ReferenceValue, ...] = ()
) -> ReferenceRecord:
    """Raw or materialized map declarations both suppress matching vanilla defaults."""
    explicit = {
        _field_identity(value, record.category)
        for value in (*record.values, *overriding)
        if not value.source.startswith("builtin:")
        and not value.state.startswith("overridden")
    }
    return replace(
        record,
        values=tuple(
            replace(value, state="overridden-base")
            if value.source.startswith("builtin:")
            and _field_identity(value, record.category) in explicit
            else value
            for value in record.values
        ),
    )


def inherit_campaign_record(
    record: ReferenceRecord,
    shared: Mapping[tuple[str, str], ReferenceRecord],
    *,
    campaign_scope: bool = True,
) -> ReferenceRecord:
    """Only a unique declared base can inherit a category-qualified shared object.

    Local empty and uncertain fields still override the corresponding inherited
    field. Every inherited field retains its original source and is labelled with
    its campaign state; the shared object itself remains a single root record.
    """
    base_id = dict(record.details).get("基础ID", "")
    parent = shared.get((record.category, base_id)) if base_id else None
    if parent is None:
        return record
    parent = demote_builtin_fields(parent)
    record = demote_builtin_fields(record, parent.values)
    local = tuple(
        value for value in record.values if not value.source.startswith("builtin:")
    )
    overridden = {_field_identity(value, record.category) for value in local}
    inherited = tuple(
        replace(
            value,
            object_id=record.id,
            state=("overridden-campaign" if campaign_scope else "overridden")
            if _field_identity(value, record.category) in overridden
            else ("campaign-inherited" if campaign_scope else "inherited-evidence")
            if value.state
            in {
                "map-evidence",
                "inherited-evidence",
                "base-reference",
                "campaign-inherited",
            }
            else "campaign-raw-evidence"
            if campaign_scope and value.state == "raw-binary-evidence"
            else value.state,
            extras=(*value.extras, ("共享来源范围", parent.scope)),
        )
        for value in parent.values
    )
    label = record.label if "display:name" in overridden else parent.label
    return replace(
        record,
        label=label,
        aliases=tuple(dict.fromkeys((*record.aliases, *parent.aliases))),
        sources=tuple(dict.fromkeys((*record.sources, *parent.sources))),
        values=(*record.values, *inherited),
        details=(
            *record.details,
            ("共享基础范围", parent.scope),
            ("共享基础ID", parent.id),
        ),
        diagnostics=tuple(dict.fromkeys((*record.diagnostics, *parent.diagnostics))),
    )


def resolve_scope_records(
    records: tuple[ReferenceRecord, ...],
    shared: Mapping[tuple[str, str], ReferenceRecord],
    builtin: Mapping[tuple[str, str], ReferenceRecord],
    *,
    campaign_scope: bool = False,
) -> tuple[tuple[ReferenceRecord, ...], tuple[str, ...]]:
    """Resolve every explicit same-scope base chain iteratively, with full diagnostics."""
    local = {
        (record.category, record.id): demote_builtin_fields(record)
        for record in records
    }
    resolved: dict[tuple[str, str], ReferenceRecord] = {}
    diagnostics: list[str] = []
    for first in local:
        trail: list[tuple[str, str]] = []
        positions: dict[tuple[str, str], int] = {}
        current = first
        while current in local and current not in resolved:
            if current in positions:
                cycle = trail[positions[current] :]
                chain = " -> ".join(
                    f"{category}:{code}" for category, code in (*cycle, current)
                )
                for identity in cycle:
                    row = local[identity]
                    note = f"{row.scope} {row.category}:{row.id}: 基础对象声明形成循环: {chain}；未推断继承值。"
                    diagnostics.append(note)
                    resolved[identity] = replace(
                        row, diagnostics=(*row.diagnostics, note)
                    )
                break
            positions[current] = len(trail)
            trail.append(current)
            row = local[current]
            base_id = dict(row.details).get("基础ID", "")
            parent_id = (row.category, base_id)
            if not base_id or parent_id == current or parent_id not in local:
                break
            current = parent_id
        for identity in reversed(trail):
            if identity in resolved:
                continue
            row = local[identity]
            base_id = dict(row.details).get("基础ID", "")
            parent_id = (row.category, base_id)
            parent = (
                resolved.get(parent_id)
                if parent_id != identity and parent_id in local
                else shared.get(parent_id)
            )
            if parent is not None:
                row = inherit_campaign_record(
                    row,
                    {parent_id: parent},
                    campaign_scope=campaign_scope or parent.scope != row.scope,
                )
                diagnostics.extend(
                    f"{row.scope} {row.category}:{row.id}: 继承来源 "
                    f"{parent.scope} {parent.category}:{parent.id} 不完整: {note}"
                    for note in parent.diagnostics
                )
            elif base_id and parent_id not in builtin:
                note = f"{row.scope} {row.category}:{row.id}: 已声明基础ID {base_id!r} 未在同类别地图/战役共享/基础目录确认；未补造继承字段。"
                diagnostics.append(note)
                row = replace(row, diagnostics=(*row.diagnostics, note))
            resolved[identity] = row
    return tuple(resolved[(row.category, row.id)] for row in records), tuple(
        diagnostics
    )
