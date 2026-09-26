"""Semantic, lossless object detail presentation for the GUI."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Final

from .item_relation_presentation import (
    format_object_relation_sections as format_object_relation_sections,
)
from .map_data import GameObject
from .object_text_presentation import (
    format_complete_text_section as format_complete_text_section,
)
from .textobj import clean_text


@dataclass(frozen=True, slots=True)
class ObjectDetailField:
    key: str
    label: str
    value: str
    source: str


_GROUP_ORDER: Final = (
    "文本与界面",
    "战斗与数值",
    "资源与外观",
    "技能与依赖",
    "其他字段",
)
_RESOURCE_WORDS: Final = ("图标", "模型", "贴图", "声音", "文件", "art", "file", "path")
_COMBAT_WORDS: Final = (
    "生命",
    "魔法",
    "攻击",
    "护甲",
    "伤害",
    "冷却",
    "距离",
    "范围",
    "速度",
    "持续",
    "间隔",
    "消耗",
    "金币",
    "木材",
    "hp",
    "mana",
    "cool",
    "cost",
    "dmg",
    "rng",
    "area",
    "dur",
)
_DEPENDENCY_WORDS: Final = (
    "技能",
    "依赖",
    "需求",
    "升级",
    "单位",
    "buff",
    "effect",
    "requires",
    "abil",
)
_TEXT_WORDS: Final = (
    "名称",
    "名字",
    "提示",
    "说明",
    "描述",
    "称谓",
    "name",
    "tip",
    "description",
)
_DEFAULT_VALUES: Final = frozenset(("-", "_"))
_PLACEMENT_SHOWN_LIMIT: Final = 3


def back_reference_note(
    category: str | None,
    placements: tuple[tuple[int, float, float], ...],
) -> str:
    """Explain where a referencing unit stands, or why no static spot exists.

    ``placements`` holds (player, x, y) from the map's pre-placed instances of
    the referencing object; only unit referents get a note, everything else
    keeps the bare reference line.
    """
    if category != "单位":
        return ""
    if not placements:
        return "未预放置，游戏内由脚本/触发创建（位置由触发逻辑决定）"
    shown = placements[:_PLACEMENT_SHOWN_LIMIT]
    parts = [f"玩家{player} ({x:g}, {y:g})" for player, x, y in shown]
    tail = f" 等{len(placements)}处" if len(placements) > len(shown) else ""
    return f"预放置 {len(placements)} 处：{'、'.join(parts)}{tail}"


def object_detail_title(obj: GameObject) -> str:
    """Return one clean line suitable for the detail-panel heading."""
    cleaned = clean_text(obj.name) or obj.obj_id
    return cleaned.splitlines()[0]


def format_object_summary(obj: GameObject) -> str:
    """Return the stable identity summary shown before all object evidence."""
    lines = [
        "【对象摘要】",
        f"名称：{clean_text(obj.name) or obj.obj_id}",
        f"分类：{obj.category}",
        f"对象 ID：{obj.obj_id}（10进制 {obj.decimal}）",
        f"基础 ID：{obj.base_id}",
        f"类型：{'自定义' if obj.is_custom else '原始'}",
    ]
    if obj.icon:
        lines.append(f"图标路径：{obj.icon}")
    return "\n".join(lines) + "\n"


def format_object_fields(obj: GameObject, detailed: bool = True) -> str:
    """Return grouped readable text without dropping any materialized field.

    ``detailed=False``（当前信息模式）只保留四组语义字段；其他字段大墙、
    未设置/默认字段与数据来源属于核对细节，留给完整证据模式。
    """
    lines: list[str] = []

    groups: dict[str, list[ObjectDetailField]] = {name: [] for name in _GROUP_ORDER}
    defaults: list[ObjectDetailField] = []
    fields = _object_fields(obj)
    for field in fields:
        if not field.value or field.value.strip() in _DEFAULT_VALUES:
            defaults.append(field)
        else:
            groups[_field_group(field)].append(field)
    for group in _GROUP_ORDER:
        if not detailed and group == "其他字段":
            continue
        items = groups[group]
        if not items:
            continue
        lines.extend(("", f"── {group}（{len(items)}）──"))
        lines.extend(_merged_field_lines(items))
    if detailed and defaults:
        lines.extend(("", f"── 未设置/默认字段（{len(defaults)}）──"))
        lines.extend(
            f"{item.label}：{'（已清空）' if not item.value else '（默认）'}"
            for item in defaults
        )
    sources = Counter(field.source for field in fields if field.source)
    if detailed and sources:
        lines.extend(("", f"── 数据来源（{len(sources)}）──"))
        lines.extend(
            f"{source}：{count} 个字段" for source, count in sorted(sources.items())
        )
    if not fields:
        lines.extend(("", "（无可用字段）"))
    return "\n".join(lines) + "\n"


def format_object_detail(obj: GameObject) -> str:
    """Return the legacy combined summary and materialized-field view."""
    return format_object_summary(obj) + format_object_fields(obj)


def _merged_field_lines(items: list[ObjectDetailField]) -> list[str]:
    """Merge fields sharing one readable value into a single labeled line.

    同组内多个字段常承载同一文本（描述/提示文本成对重复），
    合并后形如“描述｜提示文本：Tier 1…”，字段数计入组标题不变。
    """
    merged: list[list[str]] = []
    index_by_value: dict[str, int] = {}
    for item in items:
        value = clean_text(item.value)
        if value in index_by_value:
            merged[index_by_value[value]][0] += f"｜{item.label}"
            continue
        index_by_value[value] = len(merged)
        merged.append([item.label, value])
    return [f"{labels}: {value}" for labels, value in merged]


def _object_fields(obj: GameObject) -> tuple[ObjectDetailField, ...]:
    if not obj.field_values:
        return tuple(
            ObjectDetailField("", label, value, "") for label, value in obj.fields
        )
    legacy = tuple(obj.fields)
    result: list[ObjectDetailField] = []
    for index, (key, value) in enumerate(obj.field_values.items()):
        label = obj.field_labels.get(key)
        if label is None and index < len(legacy) and legacy[index][1] == value:
            label = legacy[index][0]
        result.append(
            ObjectDetailField(key, label or key, value, obj.field_sources.get(key, ""))
        )
    return tuple(result)


def _field_group(field: ObjectDetailField) -> str:
    text = f"{field.key} {field.label}".casefold()
    if any(word in text for word in _RESOURCE_WORDS):
        return "资源与外观"
    if any(word in text for word in _COMBAT_WORDS):
        return "战斗与数值"
    if any(word in text for word in _DEPENDENCY_WORDS):
        return "技能与依赖"
    if any(word in text for word in _TEXT_WORDS):
        return "文本与界面"
    return "其他字段"
