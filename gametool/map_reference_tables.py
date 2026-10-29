"""Adapt loaded map objects to the existing lossless object-table schemas."""

from __future__ import annotations

import csv
from dataclasses import replace
import io
import json
from pathlib import Path
from collections.abc import Mapping

from .batch_tsv import format_tsv_rows
from .csv_fields import full_csv_fields
from .knowledge_object_exports import _object_description, format_object_fields
from .map_data import MapData
from .map_reference_identity import MapObjectIdentity
from .map_reference_records import demote_builtin_fields
from .object_layers import binary_wts_member
from .pack_query_objects import (
    OBJECT_TABLES,
    ObjectTable,
    object_field_table,
    object_table,
)
from .reference_models import ReferenceRecord, ReferenceSource


def _rows(text: str) -> tuple[tuple[str, ...], ...]:
    with full_csv_fields():
        return tuple(
            tuple(row)
            for row in csv.reader(
                io.StringIO(text, newline=""), delimiter="\t", strict=True
            )
        )


def map_object_tables(
    md: MapData,
    identities: Mapping[tuple[str, str], MapObjectIdentity] | None = None,
) -> dict[str, ObjectTable]:
    """Keep map definitions and script clues, without duplicating builtin/shared objects."""
    objects = {
        category: [
            obj
            for obj in md.objects.get(category, ())
            if obj.ext not in {"base", "campaign"}
        ]
        for category in OBJECT_TABLES
    }
    identities = identities or {}
    selected = replace(md, objects=objects)
    exported = _rows(format_object_fields(selected, include_evidence=True))
    header = exported[0]
    # Keep every original candidate beside its materialized value. In particular,
    # a confirmed but overridden value is still source evidence, not disposable.
    extra_header = (
        "二进制类型",
        "等级",
        "数据列",
        "对象序号",
        "字段序号",
        "字节偏移",
        "结束偏移",
        "原始字节Base64",
        "结束标记",
        "对象扩展整数",
    )
    added_header = tuple(
        name
        for name in ("证据状态", "值类型", "编码证据", "诊断")
        if name not in header
    )
    full_header = (*header, *added_header, *extra_header)
    rows = [full_header]
    rows.extend(
        (*row, *("" for _ in (*added_header, *extra_header))) for row in exported[1:]
    )
    # Exported rows are already envelope-encoded. Additional original rows pass
    # through the same formatter once, before the shared schema decodes them.
    original_rows: list[tuple[str, ...]] = []
    for category, bucket in objects.items():
        for obj in bucket:
            declared = identities.get((category, obj.obj_id), MapObjectIdentity())
            for binary in declared.binary_fields:
                values = {
                    "分类": category,
                    "ID": obj.obj_id,
                    "名称": obj.name,
                    "字段键": binary.key,
                    "字段名": binary.label,
                    "值": binary.value,
                    "来源": binary.member,
                    "证据状态": "confirmed",
                    "值类型": {0: "int", 1: "real", 2: "unreal", 3: "string"}.get(
                        binary.storage_type, ""
                    ),
                    "原始值": binary.value,
                    "证据角色": "二进制原始修改",
                    "二进制类型": str(binary.storage_type),
                    "等级": str(binary.level),
                    "数据列": str(binary.data_pointer),
                    "对象序号": str(binary.object_ordinal),
                    "字段序号": str(binary.field_ordinal),
                    "字节偏移": str(binary.offset),
                    "结束偏移": str(binary.end_offset),
                    "原始字节Base64": binary.raw_bytes_base64,
                    "结束标记": str(binary.trailer),
                    "对象扩展整数": json.dumps(binary.extra_ints),
                }
                original_rows.append(
                    tuple(values.get(name, "") for name in full_header)
                )
    rows.extend(_rows(format_tsv_rows(original_rows)))
    tables = {"对象字段.tsv": object_field_table(tuple(rows))}
    for category, bucket in objects.items():
        id_rows = [
            (
                "分类",
                "ID",
                "数值",
                "基础ID",
                "名称",
                "自定义",
                "说明",
                "证据种类",
                "完整身份声明",
                "身份诊断",
            )
        ]
        id_rows.extend(
            (
                category,
                obj.obj_id,
                str(obj.decimal),
                identities.get((category, obj.obj_id), MapObjectIdentity()).base_id,
                obj.name,
                identities.get((category, obj.obj_id), MapObjectIdentity()).custom,
                _object_description(obj),
                obj.ext,
                json.dumps(
                    identities[(category, obj.obj_id)].declarations, ensure_ascii=False
                )
                if (category, obj.obj_id) in identities
                else "未记录；不从SLK/文本/脚本引用推断",
                "\n".join(
                    identities.get(
                        (category, obj.obj_id), MapObjectIdentity()
                    ).diagnostics
                ),
            )
            for obj in bucket
        )
        tables[f"对象ID/{category}.tsv"] = object_table(
            category, _rows(format_tsv_rows(id_rows))
        )
    return tables


def bind_map_record(
    record: ReferenceRecord,
    scope: str,
    sources: dict[str, ReferenceSource],
    members: dict[str, str],
    identity: MapObjectIdentity = MapObjectIdentity(),
) -> ReferenceRecord:
    """Replace virtual table paths with the actual archive/member source identities."""
    values = []
    dependencies = [
        source for _base, _custom, source, _ordinal in identity.declarations
    ]
    declared_base = dict(record.details).get("基础ID", "")
    for value in record.values:
        if value.source.startswith("builtin:"):
            values.append(value)
            continue
        provenance = value.provenance
        if provenance.startswith("base:"):
            source_id = "builtin:base_objects"
        elif provenance == "base names":
            source_id = "builtin:base_names"
        elif provenance in sources:
            source_id = provenance
        else:
            source_id = members.get(provenance.replace("/", "\\").casefold(), scope)
        extras = dict(value.extras)
        for location in extras.get("值来源", "").splitlines():
            dependency = location.split("#", 1)[0]
            if dependency in sources:
                dependencies.append(dependency)
            normalized = dependency.replace("/", "\\").casefold()
            if normalized in members:
                dependencies.append(members[normalized])
        if (
            extras.get("证据角色") == "二进制原始修改"
            and value.value.startswith("TRIGSTR_")
            and value.value.removeprefix("TRIGSTR_").isdecimal()
        ):
            wts_member = binary_wts_member(value.provenance)
            dependency = wts_member.replace("/", "\\").casefold()
            if dependency in members:
                dependencies.append(members[dependency])
        state = extras.get("证据状态") or "confirmed"
        if state == "overridden" and value.state == "overridden-campaign":
            state = value.state
        if extras.get("证据角色") == "二进制原始修改":
            state = "raw-binary-evidence"
        values.append(
            replace(
                value,
                source=source_id,
                value_type=extras.get("值类型") or value.value_type,
                state=(
                    "base-reference"
                    if source_id.startswith("builtin:") and not declared_base
                    else value.state
                )
                if state == "confirmed"
                else state,
            )
        )
    script = dict(record.details).get("证据种类") == "script"
    source_ids = tuple(
        dict.fromkeys((scope, *dependencies, *(value.source for value in values)))
    )
    details = tuple(
        (
            label,
            "脚本引用；未确认对象定义/基础ID/自定义状态"
            if script
            else "地图归档对象定义",
        )
        if label == "身份来源"
        else (label, value)
        for label, value in record.details
    )
    diagnostics = tuple(
        dict.fromkeys(
            value
            for field in values
            for label, value in field.extras
            if label == "诊断" and value
        )
    )
    identity_note = dict(record.details).get("身份诊断")
    if identity_note:
        diagnostics = (*diagnostics, identity_note)
    # A source belongs to this root only when the ledger identifies it. Unknown
    # provenance retains the complete text and the verified archive boundary.
    assert all(
        source in sources or source.startswith("builtin:") for source in source_ids
    )
    return demote_builtin_fields(
        replace(
            record,
            scope=scope,
            sources=source_ids,
            values=tuple(values),
            details=details,
            diagnostics=diagnostics,
            state="script-reference" if script else "map-evidence",
        )
    )


def virtual_table_key(scope: str, relative: str) -> tuple[Path, str]:
    """Pure lookup key only; never open or publish this synthetic path."""
    return Path(scope), relative.replace("\\", "/")
