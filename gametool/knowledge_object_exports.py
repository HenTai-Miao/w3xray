"""Object ID, box-ID and object text/icon exports for knowledge packs."""

from __future__ import annotations

from collections.abc import Iterable
import json

from .api import GameObject, MapData
from .batch_tsv import format_tsv_rows
from .knowledge_io import safe_filename, tsv, write_text
from .object_candidate_models import FieldEvidenceState
from .map_data import GameObjectFieldEvidence


def write_object_ids(md: MapData, out_dir: str) -> int:
    """Write per-category object ID TSV files."""
    count = 0
    for category, objects in sorted(md.objects.items()):
        rows = [("分类", "ID", "10进制", "基础ID", "名称", "自定义", "说明")]
        for obj in sorted_unique_objects(objects):
            rows.append(
                (
                    category,
                    obj.obj_id,
                    str(obj.decimal),
                    obj.base_id,
                    obj.name,
                    "是" if obj.is_custom else "否",
                    _object_description(obj),
                )
            )
        count += write_text(
            out_dir, f"{safe_filename(category)}.tsv", format_tsv_rows(rows)
        )
    return count


def write_box_ids(md: MapData, out_dir: str) -> int:
    """Write legacy box-compatible ID text files."""
    count = 0
    for category, objects in sorted(md.objects.items()):
        count += write_text(
            out_dir,
            f"{safe_filename(category)}ID.txt",
            format_box_id_text(objects, category=category),
        )
    return count


def sorted_unique_objects(objects: Iterable[GameObject]) -> tuple[GameObject, ...]:
    """Return first-seen objects once, ordered by rawcode latin-1 bytes."""
    by_id: dict[str, GameObject] = {}
    for obj in objects:
        by_id.setdefault(obj.obj_id, obj)
    return tuple(
        by_id[key]
        for key in sorted(by_id, key=lambda code: code.encode("latin-1", "replace"))
    )


def format_box_id_text(
    objects: Iterable[GameObject],
    *,
    category: str | None = None,
) -> str:
    """Return the plain ID/name/description format used by legacy map tools."""
    blocks: list[str] = []
    for obj in sorted_unique_objects(objects):
        description = _normalize_box_value(_object_description(obj) or "-")
        prefix = (
            f"描述：称谓：{_normalize_box_value(_propernames(obj) or '-')}\n\n"
            if category == "单位"
            else "描述："
        )
        blocks.append(
            f"ID：{_normalize_box_value(obj.obj_id)}\n"
            f"名字：{_normalize_box_value(obj.name)}\n"
            f"{prefix}{description}"
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def format_object_text_icons(md: MapData) -> str:
    """Return object names, readable text fields and icons as TSV."""
    rows = ["分类\tID\t名称\t图标\t文本字段\t文本内容"]
    for obj in _all_objects(md):
        text_fields = _text_fields(obj)
        if not text_fields and obj.icon:
            rows.append(
                "\t".join(
                    (
                        tsv(obj.category),
                        tsv(obj.obj_id),
                        tsv(obj.name),
                        tsv(obj.icon),
                        "",
                        "",
                    )
                )
            )
        for label, value in text_fields:
            rows.append(
                "\t".join(
                    (
                        tsv(obj.category),
                        tsv(obj.obj_id),
                        tsv(obj.name),
                        tsv(obj.icon),
                        tsv(label),
                        tsv(value),
                    )
                )
            )
    return "\n".join(rows) + "\n"


def format_object_fields(md: MapData) -> str:
    """Return every materialized object field and its winning source as TSV."""
    detailed = any(
        row.encoded_evidence or row.state is not FieldEvidenceState.CONFIRMED
        for obj in _all_objects(md)
        for row in obj.field_evidence
    )
    rows = [
        (
            "分类",
            "ID",
            "名称",
            "字段键",
            "字段名",
            "值",
            "来源",
            *(("证据状态", "值类型", "编码证据", "诊断") if detailed else ()),
        )
    ]
    for obj in _all_objects(md):
        evidence_index = _field_evidence_index(obj) if detailed else {}
        if obj.field_values:
            legacy_fields = tuple(obj.fields)
            for index, (key, value) in enumerate(obj.field_values.items()):
                label = obj.field_labels.get(key)
                if (
                    label is None
                    and index < len(legacy_fields)
                    and legacy_fields[index][1] == value
                ):
                    label = legacy_fields[index][0]
                rows.append(
                    (
                        obj.category,
                        obj.obj_id,
                        obj.name,
                        key,
                        label or key,
                        value,
                        obj.field_sources.get(key, ""),
                        *(
                            _field_extras(obj, key, label or key, value, evidence_index)
                            if detailed
                            else ()
                        ),
                    )
                )
        else:
            for label, value in obj.fields:
                rows.append(
                    (
                        obj.category,
                        obj.obj_id,
                        obj.name,
                        "",
                        label,
                        value,
                        "",
                        *(("confirmed", "", "", "") if detailed else ()),
                    )
                )
        if detailed:
            active = frozenset(obj.field_blockers)
            for row in obj.field_evidence:
                if row.state is FieldEvidenceState.CONFIRMED:
                    continue
                rows.append(
                    (
                        obj.category,
                        obj.obj_id,
                        obj.name,
                        row.key,
                        row.label,
                        row.value,
                        row.source,
                        row.state.value if row in active else "overridden",
                        row.value_type,
                        row.encoded_evidence,
                        row.diagnostic,
                    )
                )
    return format_tsv_rows(rows)


def _field_evidence_index(
    obj: GameObject,
) -> dict[tuple[str, str, str, str], list[GameObjectFieldEvidence]]:
    indexed: dict[tuple[str, str, str, str], list[GameObjectFieldEvidence]] = {}
    for row in obj.field_evidence:
        if row.state is not FieldEvidenceState.CONFIRMED:
            continue
        for role, token in (("key", row.key), ("label", row.label)):
            indexed.setdefault((row.source, row.value, role, token), []).append(row)
    return indexed


def _field_extras(
    obj: GameObject,
    key: str,
    label: str,
    value: str,
    index: dict[tuple[str, str, str, str], list[GameObjectFieldEvidence]],
) -> tuple[str, ...]:
    source = obj.field_sources.get(key, "")
    evidence = index.get(
        (source, value, "key", key), index.get((source, value, "label", label), [])
    )
    encoded = [
        json.loads(row.encoded_evidence) for row in evidence if row.encoded_evidence
    ]
    return (
        "confirmed",
        " / ".join(dict.fromkeys(row.value_type for row in evidence if row.value_type)),
        json.dumps(encoded, ensure_ascii=True) if encoded else "",
        "",
    )


def _all_objects(md: MapData) -> Iterable[GameObject]:
    for objects in md.objects.values():
        yield from objects


def _text_fields(obj: GameObject) -> list[tuple[str, str]]:
    wanted = ("名称", "提示", "说明", "描述", "Ubertip", "Description", "EditorSuffix")
    return [
        (str(label), str(value))
        for label, value in obj.fields
        if str(value) and any(token in str(label) for token in wanted)
    ]


def _object_description(obj: GameObject) -> str:
    canonical = obj.field_values.get("display:description")
    if canonical is not None:
        return canonical
    text_fields = _text_fields(obj)
    for label, value in text_fields:
        if _is_long_description_label(label):
            return value
    for label, value in text_fields:
        if _is_short_description_label(label):
            return value
    return ""


def _propernames(obj: GameObject) -> str:
    canonical = obj.field_values.get("display:propernames")
    if canonical is not None:
        return canonical
    for label, value in obj.fields:
        if label in {"Propernames", "称谓"} and value:
            return value
    return ""


def _normalize_box_value(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _is_long_description_label(label: str) -> bool:
    return (
        label in {"说明", "描述", "Ubertip", "Description", "提示文本"}
        or "扩展" in label
    )


def _is_short_description_label(label: str) -> bool:
    return "提示" in label or label in {"Tip", "EditorSuffix"}
