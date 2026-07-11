"""Object ID, box-ID and object text/icon exports for knowledge packs."""

from __future__ import annotations

from collections.abc import Iterable

from .api import GameObject, MapData
from .knowledge_io import safe_filename, tsv, write_text


def write_object_ids(md: MapData, out_dir: str) -> int:
    """Write per-category object ID TSV files."""
    count = 0
    for category, objects in sorted(md.objects.items()):
        rows = ["分类\tID\t10进制\t基础ID\t名称\t自定义\t说明"]
        for obj in sorted_unique_objects(objects):
            rows.append("\t".join((
                tsv(category),
                tsv(obj.obj_id),
                str(obj.decimal),
                tsv(obj.base_id),
                tsv(obj.name),
                "是" if obj.is_custom else "否",
                tsv(_object_description(obj)),
            )))
        count += write_text(out_dir, f"{safe_filename(category)}.tsv", "\n".join(rows) + "\n")
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
            rows.append("\t".join((
                tsv(obj.category),
                tsv(obj.obj_id),
                tsv(obj.name),
                tsv(obj.icon),
                "",
                "",
            )))
        for label, value in text_fields:
            rows.append("\t".join((
                tsv(obj.category),
                tsv(obj.obj_id),
                tsv(obj.name),
                tsv(obj.icon),
                tsv(label),
                tsv(value),
            )))
    return "\n".join(rows) + "\n"


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
