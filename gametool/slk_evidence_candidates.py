"""Carry typed SLK certainty and source records through object collection."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
import json

from .extraction_diagnostics import DiagnosticTarget, record_component_parse_issue
from .fields import field_type
from .object_candidate_models import (
    FieldEvidenceState,
    ObjectCandidate,
    ObjectFieldValue,
    ObjectSourceKind,
)
from .object_candidate_values import (
    resolved_source_value,
    resolved_value,
    wts_value_source,
)
from .object_codes import valid_object_code
from .object_field_selection import object_field_identity
from .references import extract_refs_by_column
from .slk_objects import (
    SlkArchive,
    is_noise_col,
    parse_category_evidence,
    slk_col_label,
)


def collect_category_candidates(
    archive: SlkArchive,
    category: str,
    wts: Mapping[int, str],
    md: DiagnosticTarget | None,
) -> tuple[ObjectCandidate, ...]:
    groups: dict[tuple[str, str], list[tuple[ObjectFieldValue, str, bool]]] = {}
    objects: dict[str, list[ObjectFieldValue]] = {}
    for source in parse_category_evidence(archive, category, md=md):
        if not source.identity_confirmed:
            continue
        table = source.table
        columns = {column.number: column for column in table.columns}
        for row in table.rows:
            if row.key is None or not valid_object_code(row.key):
                continue
            objects.setdefault(row.key, [])
            for index in row.cell_indexes:
                cell = table.cells[index]
                column = columns.get(cell.x) if cell.x is not None else None
                if column is None or cell.x == 1:
                    continue
                for name in column.candidate_names:
                    if is_noise_col(name, category):
                        continue
                    raw = table.records[cell.record_index].fields[cell.field_index].raw
                    semantic = cell.value if cell.value is not None else raw
                    encoded = json.dumps(
                        {
                            "source": source.source,
                            "category": category,
                            "cell": table.cell_payload(index),
                            "record": table.record_payload(cell.record_index),
                        },
                        ensure_ascii=True,
                    )
                    value = ObjectFieldValue(
                        name,
                        slk_col_label(name),
                        resolved_value(semantic, wts),
                        source.source,
                        ObjectSourceKind.SLK,
                        wts_value_source(semantic, wts, "war3map"),
                        field_type(name)
                        or (
                            "string"
                            if cell.value_kind == "quoted"
                            else "slk:" + cell.value_kind
                        ),
                        resolved_source_value(semantic, wts),
                        encoded_evidence=encoded,
                    )
                    identity = (row.key, object_field_identity(value, category))
                    uncertain = (
                        not cell.valid
                        or column.name is None
                        or (row.key, name) in table.blocked_fields
                    )
                    groups.setdefault(identity, []).append(
                        (value, cell.value_kind, uncertain)
                    )
    for (code, _identity), entries in groups.items():
        values = {
            (kind, value.raw_value)
            for value, kind, _uncertain in entries
            if kind != "opaque"
        }
        keys = {value.key for value, _kind, _uncertain in entries}
        uncertain = any(unknown for _value, _kind, unknown in entries) or len(keys) > 1
        state = (
            FieldEvidenceState.CONFLICT
            if len(values) > 1
            else FieldEvidenceState.UNKNOWN
            if uncertain
            else FieldEvidenceState.CONFIRMED
        )
        diagnostic = ""
        if state is not FieldEvidenceState.CONFIRMED:
            diagnostic = "SLK 字段未确认：来源、单元格或语义列存在冲突/未知；未选取任一值或继承值。"
            if md is not None:
                detail = {
                    "code": "semantic_field_conflict",
                    "category": category,
                    "object_id": code,
                    "state": state.value,
                    "message": diagnostic,
                    "evidence": [
                        json.loads(value.encoded_evidence)
                        for value, _kind, _uncertain in entries
                    ],
                }
                record_component_parse_issue(
                    md,
                    "slk",
                    " | ".join(
                        dict.fromkeys(
                            value.source for value, _kind, _uncertain in entries
                        )
                    ),
                    json.dumps(detail, ensure_ascii=True),
                )
        objects[code].extend(
            replace(value, state=state, diagnostic=diagnostic)
            for value, _kind, _uncertain in entries
        )
    result: list[ObjectCandidate] = []
    for code, fields in objects.items():
        confirmed = {
            value.key: value.value
            for value in fields
            if value.state is FieldEvidenceState.CONFIRMED
        }
        refs = tuple(
            (label, tuple(codes))
            for label, codes in extract_refs_by_column(confirmed, category)
        )
        result.append(
            ObjectCandidate(category, code, code, True, "slk", tuple(fields), refs)
        )
    return tuple(result)
