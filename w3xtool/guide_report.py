"""一键玩家攻略骨架：把已解析的地图数据压成“这张图怎么玩”的速查报告。

与 cli 摘要（对象计数、结构诊断）不同，本模块只回答玩家问题：
开局有什么、按什么指令、做什么任务、英雄有谁、装备怎么合、去哪打怪掉宝。

组合四类现成证据，全部只读、纯派生：
- w3i 信息卡（名称/作者/推荐人数/描述）；
- 脚本文本扫描（聊天指令、CreateQuestBJ 任务文本、计时器与播报线索）；
- 预放置单位 + 原版细类表（英雄阵容）；
- 物品关系索引（合成配方、商店出售、怪物直接掉落）。

任何一段证据缺失只让对应段落消失，不影响其它段落。
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .base_names import BASE_CATEGORIES, BASE_NAMES
from .item_relation_models import ItemRelation, ItemRelationKind, RelationObject
from .script_scan import scan_chat_commands
from .script_sources import analysis_script_texts
from .wts import map_wts_table, resolve

if TYPE_CHECKING:
    from .map_data import MapData

# CreateQuestBJ(bj_QUESTTYPE_REQ_DISCOVERED, "标题", "说明", "图标")
_QUEST_CALL = re.compile(
    r"CreateQuestBJ\s*\(\s*[A-Za-z_][A-Za-z0-9_]*\s*,\s*"
    r'"((?:[^"\\]|\\.)*)"\s*,\s*"((?:[^"\\]|\\.)*)"'
)
# CreateTimerDialogBJ(timer, "字面标签")：拼接表达式不匹配，只有整串字面量才收
_TIMER_LABEL = re.compile(r'CreateTimerDialogBJ\s*\([^,]+,\s*"((?:[^"\\]|\\.)*)"\s*\)')
# 玩家可见播报文本（任务提示、波次公告等）
_DISPLAY_TEXT = re.compile(
    r"(?:DisplayTextToForce|DisplayTimedTextToForce|DisplayTextToPlayer|"
    r'DisplayTimedTextToPlayer|BJDebugMsg)\s*\([^"]*?"((?:[^"\\]|\\.)*)"'
)
# 颜色码与换行占位：攻略速查里只留纯文本
_COLOR_CODE = re.compile(r"\|c[0-9A-Fa-f]{8}|\|r")
_NEWLINE_CODE = re.compile(r"\|n")
_WHITESPACE = re.compile(r"\s+")
# 播报线索只保留与流程推进相关的关键词
_CLUE_KEYWORDS = re.compile(r"波|boss|BOSS|Boss|胜利|失败|隐藏|进攻|防守|通关")

_MAX_CLUES = 30
_MAX_SHOP_ITEMS = 12
_MAX_DROP_ENTRIES = 8


@dataclass(frozen=True, slots=True)
class GuideSection:
    """一段有标题的攻略证据，lines 为空表示该段证据缺失。"""

    key: str
    title: str
    lines: tuple[str, ...]


GUIDE_SECTION_TITLES: dict[str, str] = {
    "basic": "基本信息",
    "commands": "聊天指令",
    "quests": "任务说明",
    "heroes": "英雄阵容",
    "recipes": "合成配方",
    "shops": "商店出售",
    "drops": "怪物掉落",
    "clues": "波次与播报线索",
}


def build_guide_sections(md: MapData) -> tuple[GuideSection, ...]:
    """按固定顺序组装攻略段落，证据缺失的段落直接省略。"""
    candidates = (
        GuideSection("basic", GUIDE_SECTION_TITLES["basic"], _basic_lines(md)),
        GuideSection("commands", GUIDE_SECTION_TITLES["commands"], _command_lines(md)),
        GuideSection("quests", GUIDE_SECTION_TITLES["quests"], _quest_lines(md)),
        GuideSection("heroes", GUIDE_SECTION_TITLES["heroes"], _hero_lines(md)),
        GuideSection("recipes", GUIDE_SECTION_TITLES["recipes"], _recipe_lines(md)),
        GuideSection("shops", GUIDE_SECTION_TITLES["shops"], _shop_lines(md)),
        GuideSection("drops", GUIDE_SECTION_TITLES["drops"], _drop_lines(md)),
        GuideSection("clues", GUIDE_SECTION_TITLES["clues"], _clue_lines(md)),
    )
    return tuple(section for section in candidates if section.lines)


def iter_guide_lines(md: MapData, section: str | None = None) -> Iterator[str]:
    """渲染攻略速查行；section 指定单段键名，未知键抛 ValueError。"""
    sections = build_guide_sections(md)
    if section is not None:
        if section not in GUIDE_SECTION_TITLES:
            valid = "、".join(GUIDE_SECTION_TITLES)
            raise ValueError(f"未知攻略段落：{section}（可选：{valid}）")
        sections = tuple(sec for sec in sections if sec.key == section)
    for sec in sections:
        yield f"【{sec.title}】"
        yield from sec.lines
        yield ""


def format_guide_report(md: MapData, section: str | None = None) -> str:
    """返回完整攻略速查文本（段落间空行分隔，结尾无多余空行）。"""
    lines = list(iter_guide_lines(md, section))
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def _basic_lines(md: MapData) -> tuple[str, ...]:
    info = md.w3i
    if info is None:
        return (f"- 地图名：{md.name}",)
    rows = [
        f"- 地图名：{info.map_name or md.name}",
        f"- 作者：{info.author or '未知'}",
        f"- 推荐人数：{info.recommended_players or '未标注'}（玩家位 {len(info.players)}）",
        f"- 尺寸：{info.width}×{info.height}",
    ]
    description = _clean(info.description)
    if description:
        rows.append(f"- 简介：{description}")
    return tuple(rows)


def _command_lines(md: MapData) -> tuple[str, ...]:
    wts = map_wts_table(md)
    seen: set[tuple[str, bool]] = set()
    rows: list[str] = []
    for _source, text in analysis_script_texts(md):
        for command in scan_chat_commands(text):
            if not command.command:
                continue
            key = (command.command, command.exact)
            if key in seen:
                continue
            seen.add(key)
            hint = command.hint
            if hint and wts:
                hint = str(resolve(hint, wts))
            hint = _clean(hint)
            match = "精确" if command.exact else "前缀"
            suffix = f" — {hint}" if hint else ""
            rows.append(f"- 输入 {command.command}（{match}匹配）{suffix}")
    return tuple(rows)


def _quest_lines(md: MapData) -> tuple[str, ...]:
    wts = map_wts_table(md)
    seen: set[tuple[str, str]] = set()
    rows: list[str] = []
    for _source, text in analysis_script_texts(md):
        for match in _QUEST_CALL.finditer(text):
            title = _resolve_text(match.group(1), wts)
            body = _resolve_text(match.group(2), wts)
            if not title or (title, body) in seen:
                continue
            seen.add((title, body))
            rows.append(f"- ◆ {title}")
            if body:
                rows.append(f"  {body}")
    return tuple(rows)


def _hero_lines(md: MapData) -> tuple[str, ...]:
    counts: dict[str, int] = {}
    for unit in md.units:
        if _hero_fine_category(md, unit.type_id) != "英雄":
            continue
        counts[unit.type_id] = counts.get(unit.type_id, 0) + 1
    if not counts:
        return ()
    rows = [
        f"- {_code_name(md, code)}({code}) — 预放置 ×{count}"
        for code, count in sorted(counts.items())
    ]
    return (f"- 共 {len(rows)} 种英雄单位（含明选/隐藏/NPC 英雄模型）", *rows)


def _recipe_lines(md: MapData) -> tuple[str, ...]:
    rows: list[str] = []
    for relation in md.item_relations.for_kind(ItemRelationKind.RECIPE):
        materials = " + ".join(
            f"{_endpoint_name(ing.item)}×{ing.count}" for ing in relation.ingredients
        )
        if not materials:
            continue
        rows.append(
            f"- {_endpoint_name(relation.item)}"
            f"({relation.item.object_id}) = {materials} {_evidence_tag(relation)}"
        )
    return tuple(rows)


def _shop_lines(md: MapData) -> tuple[str, ...]:
    return _grouped_source_lines(md, ItemRelationKind.SHOP_SELL, _MAX_SHOP_ITEMS, "、")


def _drop_lines(md: MapData) -> tuple[str, ...]:
    return _grouped_source_lines(
        md, ItemRelationKind.UNIT_DROP, _MAX_DROP_ENTRIES, "；"
    )


def _clue_lines(md: MapData) -> tuple[str, ...]:
    wts = map_wts_table(md)
    seen: set[str] = set()
    rows: list[str] = []
    texts = analysis_script_texts(md)
    all_text = "\n".join(text for _source, text in texts)
    for match in _TIMER_LABEL.finditer(all_text):
        label = _resolve_text(match.group(1), wts)
        if not label or label in seen:
            continue
        seen.add(label)
        rows.append(f"- 计时器标签：{label}")
    for match in _DISPLAY_TEXT.finditer(all_text):
        clue = _resolve_text(match.group(1), wts)
        if not clue or clue in seen or not _CLUE_KEYWORDS.search(clue):
            continue
        seen.add(clue)
        rows.append(f"- 播报：{clue}")
        if len(rows) >= _MAX_CLUES:
            break
    return tuple(rows)


def _grouped_source_lines(
    md: MapData,
    kind: ItemRelationKind,
    limit: int,
    separator: str,
) -> tuple[str, ...]:
    grouped: dict[str, list[str]] = {}
    seen_entries: dict[str, set[str]] = {}
    for relation in md.item_relations.for_kind(kind):
        source = relation.source
        if source is None:
            continue
        key = f"{_endpoint_name(source)}({source.object_id})"
        chance = "" if relation.chance is None else f" {relation.chance}%"
        entry = f"{_endpoint_name(relation.item)}{chance}"
        # 同一来源的重复槽位（多栏出售/多组掉落）只展示一次。
        if entry in seen_entries.setdefault(key, set()):
            continue
        seen_entries[key].add(entry)
        grouped.setdefault(key, []).append(entry)
    rows: list[str] = []
    for source, items in grouped.items():
        head = items[:limit]
        extra = len(items) - len(head)
        suffix = f" ……另 {extra} 项" if extra > 0 else ""
        rows.append(f"- {source}：{separator.join(head)}{suffix}")
    return tuple(rows)


def _evidence_tag(relation: ItemRelation) -> str:
    parts: list[str] = []
    evidence = relation.evidence
    if evidence.source:
        where = (
            evidence.source
            if not evidence.line
            else f"{evidence.source}:{evidence.line}"
        )
        parts.append(where)
    label = evidence.trigger or evidence.function
    if label:
        parts.append(label)
    return f"〔{' '.join(parts)}〕" if parts else ""


def _endpoint_name(endpoint: RelationObject) -> str:
    """取关系端点名称，缺名时退化为对象码。"""
    return endpoint.name or endpoint.object_id


def _resolve_text(value: str, wts: dict[int, str]) -> str:
    return _clean(str(resolve(value, wts)) if wts else value)


def _clean(text: str) -> str:
    """去掉颜色码/换行占位并压缩空白，输出单行纯文本。"""
    if not text:
        return ""
    plain = _NEWLINE_CODE.sub(" ", _COLOR_CODE.sub("", text))
    return _WHITESPACE.sub(" ", plain).strip()


def _fine_category(code: str) -> str:
    fine = BASE_CATEGORIES.get(code)
    return "" if fine is None else fine[0]


def _hero_fine_category(md: MapData, code: str) -> str:
    """细类判定：标准码直查；自定义码回退到对象定义的标准 base_id 再查。

    自定义英雄（如基于 Hamg 的 H00R）不在原版细类表里，
    但对象定义保留了标准基码，链一次即可判定。
    """
    fine = _fine_category(code)
    if fine:
        return fine
    obj = md.obj_index.get(code)
    if obj is not None:
        return _fine_category(obj.base_id)
    return ""


def _code_name(md: MapData, code: str) -> str:
    obj = md.obj_index.get(code)
    if obj is not None:
        return str(obj.name) or code
    return BASE_NAMES.get(code) or code
