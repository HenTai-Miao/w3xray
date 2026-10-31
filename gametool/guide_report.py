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

from .script_sources import analysis_script_sources

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .base_catalog import fine_category_for
from .base_objects import BASE_OBJECTS
from .item_relation_models import (
    ItemRelation,
    ItemRelationKind,
    RelationObject,
    RelationCompleteness,
    RelationConfidence,
)
from .pack_query_cli import (
    _item_trigger_grant_lines,
    script_death_drop_lines,
    use_item_loot_lines,
)
from .script_scan import scan_chat_commands
from .script_trigger_acquisition import (
    format_trigger_acquisitions,
    trigger_acquisitions,
)
from .script_behavior_index import ScriptBehaviorCall, build_script_behavior_index
from .script_literal_decoding import decode_script_literal
from .query_coordinates import coordinates_from_text
from .placement_positions import (
    PositionGroups,
    doodad_position_groups,
    unit_position_groups,
)
from .static_numbers import format_number
from .placement_identity import PlacementObjectIndex
from .wts import map_wts_table, resolve

if TYPE_CHECKING:
    from .map_data import MapData

# Exact text argument roles; earlier player/force strings are not messages.
_DISPLAY_ARGUMENTS = {
    "DisplayTextToForce": 1,
    "DisplayTimedTextToForce": 2,
    "DisplayTextToPlayer": 3,
    "DisplayTimedTextToPlayer": 4,
    "BJDebugMsg": 0,
}
# 颜色码与换行占位：攻略速查里只留纯文本
_COLOR_CODE = re.compile(r"\|c[0-9A-Fa-f]{8}|\|r")
_NEWLINE_CODE = re.compile(r"\|n")
_WHITESPACE = re.compile(r"\s+")
# 播报线索只保留与流程推进相关的关键词
_CLUE_KEYWORDS = re.compile(r"波|boss|BOSS|Boss|胜利|失败|隐藏|进攻|防守|通关")


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
    "drops": "怪物与可破坏物掉落",
    "loot": "开箱与兑换产出",
    "clues": "波次与播报线索",
}


def build_guide_sections(md: MapData) -> tuple[GuideSection, ...]:
    """按固定顺序组装攻略段落，证据缺失的段落直接省略。"""
    positions = _placement_coords(md)
    calls = build_script_behavior_index(analysis_script_sources(md)).calls
    candidates = (
        GuideSection("basic", GUIDE_SECTION_TITLES["basic"], _basic_lines(md)),
        GuideSection("commands", GUIDE_SECTION_TITLES["commands"], _command_lines(md)),
        GuideSection("quests", GUIDE_SECTION_TITLES["quests"], _quest_lines(md, calls)),
        GuideSection("heroes", GUIDE_SECTION_TITLES["heroes"], _hero_lines(md)),
        GuideSection("recipes", GUIDE_SECTION_TITLES["recipes"], _recipe_lines(md)),
        GuideSection(
            "shops", GUIDE_SECTION_TITLES["shops"], _shop_lines(md, positions)
        ),
        GuideSection(
            "drops", GUIDE_SECTION_TITLES["drops"], _drop_lines(md, positions)
        ),
        GuideSection("loot", GUIDE_SECTION_TITLES["loot"], _loot_lines(md)),
        GuideSection("clues", GUIDE_SECTION_TITLES["clues"], _clue_lines(md, calls)),
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
    # 战役容器 (.w3n): 指令/任务/掉落/合成都在任务关里, 空段不是「无内容」——
    # 尾附逐关指引, 防止把容器级空段误读成这图没指令/没掉落
    is_campaign = str(md.path).lower().endswith(".w3n")
    hint = (
        "- 战役容器：指令/任务/掉落/合成在各任务关里——逐关查询用 "
        "`pack-query <战役包> <命令> <词>`（自动按「== 子地图 名 ==」聚合）"
    )
    # 尾部 near 模板: 报告里首个 @坐标 → 可直接复制执行的坐标反查 (near 联动)
    if section in (None, "shops", "drops"):
        for line in lines:
            point = coordinates_from_text(line) if "@" in line else None
            if point:
                lines.append("")
                lines.append(f"- 坐标反查模板：near {point[0]} {point[1]}")
                break
    if is_campaign and section is None:
        lines.append("")
        lines.append(hint)
    elif is_campaign and not lines:
        # --section 单段在容器上为空时旧版什么都不印, 玩家会以为命令失效
        return hint
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
    for _source, text, lua in analysis_script_sources(md):
        for command in scan_chat_commands(text, lua=lua):
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


def _quest_lines(md: MapData, calls: tuple[ScriptBehaviorCall, ...]) -> tuple[str, ...]:
    wts = map_wts_table(md)
    seen: set[tuple[str, str]] = set()
    rows: list[str] = []
    for call in calls:
        if _text_api(call) != "CreateQuestBJ":
            continue
        title, body = _call_text(call, 1, wts), _call_text(call, 2, wts)
        if call.binding != "standard-global" or title is None or body is None:
            rows.extend(_unresolved_text_call(call, "任务"))
            continue
        if not title or (title, body) in seen:
            continue
        seen.add((title, body))
        rows.append(f"- ◆ {title}")
        if body:
            rows.append(f"  {body}")
    return tuple(rows)


def _hero_lines(md: MapData) -> tuple[str, ...]:
    objects = PlacementObjectIndex(md)
    counts: dict[str, int] = {}
    candidates: list[str] = []
    for unit in md.units:
        identity = objects.placement(unit.type_id, ("单位", "物品"))
        if identity.category != "单位" or identity.fine != "英雄":
            obj = objects.objects.get(("单位", unit.type_id))
            if (
                identity.diagnostic
                and obj is not None
                and fine_category_for(obj.base_id, obj.obj_id, category="单位")
                == "英雄"
            ):
                candidates.append(
                    f"- 未确认预放置英雄候选 {unit.type_id}"
                    f" @({format_number(unit.x)},{format_number(unit.y)})：{identity.diagnostic}"
                )
            continue
        counts[unit.type_id] = counts.get(unit.type_id, 0) + 1
    if not counts:
        # 预放置为 0 不等于没有英雄: 很多 RPG 由脚本/选择系统在运行时生成。
        # 对象表里确有英雄类单位时, 用一行说明替代整段缺失 (迷失国度即此形态)。
        hero_objs = [
            code
            for (category, code), obj in objects.objects.items()
            if category == "单位"
            and obj.ext != "script"
            and fine_category_for(obj.base_id, code, category=category) == "英雄"
        ]
        if not hero_objs:
            return tuple(candidates)
        return (
            f"- {'未确认预放置英雄单位' if candidates else '无预放置英雄单位'}；对象表含 {len(hero_objs)} 个英雄类单位"
            "（英雄可能由脚本/选择系统在运行时生成）",
            *candidates,
        )
    rows = [
        f"- {objects.name('单位', code)}({code}) — 预放置 ×{count}"
        for code, count in sorted(counts.items())
    ]
    return (
        f"- 共 {len(rows)} 种英雄单位（含明选/隐藏/NPC 英雄模型）",
        *rows,
        *candidates,
    )


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


def _shop_lines(md: MapData, coords: PositionGroups | None = None) -> tuple[str, ...]:
    objects = PlacementObjectIndex(md)
    confirmed = unit_position_groups(md, confirmed_only=True)
    preplaced = {
        (unit.type_id, unit.x, unit.y)
        for unit in md.units
        if objects.placement(unit.type_id, ("单位", "物品")).category == "单位"
    }
    script_points = {
        (code, x, y) for code, points in confirmed.items() for x, y in points
    } - preplaced
    if coords:
        for code, points in coords.items():
            if objects.placement(code, ("单位", "物品")).category == "单位":
                confirmed[code] = tuple(
                    dict.fromkeys((*confirmed.get(code, ()), *points))
                )
    rows: list[str] = []
    for kind in (ItemRelationKind.SHOP_SELL, ItemRelationKind.SHOP_MAKE):
        lines = _grouped_source_lines(
            md,
            kind,
            "、",
            coords=confirmed,
            exclude_candidates=True,
            preplaced_points=preplaced,
            script_points=script_points,
        )
        rows.extend(
            lines
            if kind is ItemRelationKind.SHOP_SELL
            else ("- 制造：" + line.removeprefix("- ") for line in lines)
        )
        for relation in md.item_relations.for_kind(kind):
            if not _candidate_relation(relation):
                continue
            source = relation.source
            name = (
                "未记录来源"
                if source is None
                else f"{_endpoint_name(source)}({source.object_id})"
            )
            point = (
                "位置未确认"
                if relation.x is None or relation.y is None
                else f"({format_number(relation.x)}, {format_number(relation.y)})"
            )
            rows.append(
                f"- 未确认商店线索：{name} @{point} -> {_endpoint_name(relation.item)}({relation.item.object_id}) [{kind.value}]；{relation.confidence.value}/{relation.completeness.value}；{relation.unresolved_reason} {_evidence_tag(relation)} 实例{relation.instance_serial} / {relation.evidence.location}"
            )
    return tuple(rows)


def _drop_lines(md: MapData, coords: PositionGroups | None = None) -> tuple[str, ...]:
    objects = PlacementObjectIndex(md)
    rows = list(
        _grouped_source_lines(
            md,
            ItemRelationKind.UNIT_DROP,
            "；",
            coords=_placement_coords(md) if coords is None else coords,
            exclude_candidates=True,
        )
    )
    # 可破坏物掉落 (箱子/路障) 是独立关系类型——迷失国度 75 行此类证据
    # 此前整类不进 drops 段, 玩家只看得到「怪物掉落」
    rows.extend(
        _grouped_source_lines(
            md,
            ItemRelationKind.DESTRUCTABLE_DROP,
            "；",
            coords=doodad_position_groups(md),
            exclude_candidates=True,
        )
    )
    for relation in md.item_relations.records:
        if relation.kind not in (
            ItemRelationKind.UNIT_DROP,
            ItemRelationKind.DESTRUCTABLE_DROP,
        ) or not _candidate_relation(relation):
            continue
        source = relation.source
        label = (
            "未记录来源"
            if source is None
            else f"{_endpoint_name(source)}({source.object_id})"
        )
        point = (
            "坐标未记录"
            if relation.x is None or relation.y is None
            else f"({format_number(relation.x)}, {format_number(relation.y)})"
        )
        chance = "" if relation.chance is None else f"；原始概率/权重 {relation.chance}"
        rows.append(
            f"- 未确认预放置掉落线索：{label} @{point} -> {_endpoint_name(relation.item)}({relation.item.object_id}){chance}；{relation.confidence.value}/{relation.completeness.value}；{relation.unresolved_reason} {_evidence_tag(relation)} 实例{relation.instance_serial} / 偏移{relation.evidence.offset}"
        )
    # 脚本死亡触发证据与关系表满量并列——guide drops 段曾只读掉落表,
    # BossFH 直落 I01F 类证据在玩家最常跑的出口缺席 (与 pack-query
    # drop 兜底同源正则, 语义一致: 掷骰不写保底, 奖池 N 选 1)。
    seen: set[str] = set(rows)
    for source, text, lua in analysis_script_sources(md):
        if lua is None:
            rows.append(
                f"- 来源语言未知，保留脚本原文，未按 JASS/Lua 推断掉落：{source}"
            )
            continue
        evidence = (
            format_trigger_acquisitions(
                trigger_acquisitions(text, lua=True),
                lambda code: _code_name(md, code, objects),
                source=source,
                death=True,
            )
            if lua is True
            else script_death_drop_lines(
                text, lambda code: _code_name(md, code, objects)
            )
        )
        if lua is True:
            # Identical calls at different offsets remain separate evidence rows.
            rows.extend(evidence)
            seen.update(evidence)
            continue
        for line in evidence:
            if line not in seen:
                seen.add(line)
                rows.append(line)
        rows.extend(
            format_trigger_acquisitions(
                tuple(
                    record
                    for record in trigger_acquisitions(text, lua=False)
                    if record.graph is not None and (record.node or record.value_proof)
                ),
                lambda code: _code_name(md, code, objects),
                source=source,
                death=True,
            )
        )
    return tuple(rows)


def _loot_lines(md: MapData) -> tuple[str, ...]:
    """开箱与兑换产出: 使用/拾取触发的数组池与直接发放 (与 where 同源, 满量)。"""
    rows: list[str] = []
    objects = PlacementObjectIndex(md)
    seen: set[str] = set()
    for source, text, lua in analysis_script_sources(md):
        if lua is None:
            rows.append(
                f"- 来源语言未知，保留脚本原文，未按 JASS/Lua 推断开箱兑换：{source}"
            )
            continue
        if lua is True:
            records = tuple(
                record
                for record in trigger_acquisitions(text, lua=True)
                if record.input_items or record.kind in {"拾取", "使用"}
            )
            lines = format_trigger_acquisitions(
                records,
                lambda code: _code_name(md, code, objects),
                source=source,
                death=False,
            )
            rows.extend(lines)
            seen.update(lines)
            continue
        else:
            lines = list(
                use_item_loot_lines(text, lambda code: _code_name(md, code, objects))
            )
            lines.extend(
                _item_trigger_grant_lines(
                    text, [], lambda code: _code_name(md, code, objects), label_all=True
                )
            )
        for line in lines:
            if line not in seen:
                seen.add(line)
                rows.append(line)
        records = tuple(
            record
            for record in trigger_acquisitions(text, lua=False)
            if record.graph is not None
            and (record.node or record.value_proof)
            and (record.input_items or record.kind in {"拾取", "使用"})
        )
        rows.extend(
            format_trigger_acquisitions(
                records,
                lambda code: _code_name(md, code, objects),
                source=source,
                death=False,
            )
        )
    return tuple(rows)


def _clue_lines(md: MapData, calls: tuple[ScriptBehaviorCall, ...]) -> tuple[str, ...]:
    wts = map_wts_table(md)
    seen: set[str] = set()
    rows: list[str] = []
    for call in calls:
        api = _text_api(call)
        index = 1 if api == "CreateTimerDialogBJ" else _DISPLAY_ARGUMENTS.get(api)
        if index is None:
            continue
        value = _call_text(call, index, wts)
        if call.binding != "standard-global" or value is None:
            rows.extend(_unresolved_text_call(call, "计时器/播报"))
            continue
        if not value or value in seen:
            continue
        if api != "CreateTimerDialogBJ" and not _CLUE_KEYWORDS.search(value):
            continue
        seen.add(value)
        rows.append(
            f"- {'计时器标签' if api == 'CreateTimerDialogBJ' else '播报'}：{value}"
        )
    return tuple(rows)  # 线索全量: 匹配多少收多少, 不设条数上限


def _placement_coords(md: MapData) -> PositionGroups:
    """Keep all preplaced and script coordinate evidence per unit code."""
    return unit_position_groups(md)


def _grouped_source_lines(
    md: MapData,
    kind: ItemRelationKind,
    separator: str,
    coords: PositionGroups | None = None,
    *,
    exclude_candidates: bool = False,
    preplaced_points: set[tuple[str, float, float]] | None = None,
    script_points: set[tuple[str, float, float]] | None = None,
) -> tuple[str, ...]:
    grouped: dict[
        tuple[str, str, str],
        dict[tuple[float, float] | None, dict[tuple[object, ...], str]],
    ] = {}
    for relation in md.item_relations.for_kind(kind):
        if exclude_candidates and _candidate_relation(relation):
            continue
        source = relation.source
        if source is None:
            continue
        key = (
            source.category,
            source.object_id,
            f"{_endpoint_name(source)}({source.object_id})",
        )
        point = (
            (relation.x, relation.y)
            if relation.x is not None and relation.y is not None
            else None
        )
        chance = "" if relation.chance is None else f" {relation.chance}%"
        group = (
            ""
            if relation.group_index is None
            else f"（掉落组{relation.group_index + 1}）"
        )
        entry = f"{_endpoint_name(relation.item)}{chance}{group}"
        identity = (
            relation.item.object_id,
            relation.chance,
            relation.group_index,
            relation.entry_index,
            relation.slot,
        )
        grouped.setdefault(key, {}).setdefault(point, {})[identity] = entry
    preplaced = {(unit.type_id, unit.x, unit.y) for unit in md.units}
    preplaced.update((doodad.type_id, doodad.x, doodad.y) for doodad in md.doodads)
    if preplaced_points is not None:
        preplaced = preplaced_points
    rows: list[str] = []
    for (_category, code, source), by_point in grouped.items():
        general = by_point.get(None, {})
        points: dict[tuple[float, float], None] = {}
        if general and coords:
            points.update((point, None) for point in coords.get(code, ()))
        points.update((point, None) for point in by_point if point is not None)
        if not points:
            rows.append(f"- {source}：{separator.join(general.values())}")
            continue
        for x, y in points:
            items = {**general, **by_point.get((x, y), {})}
            note = (
                ""
                if (code, x, y) in preplaced
                else " [关系记录位置]"
                if (x, y) in by_point
                else " [脚本位置]"
                if script_points is None or (code, x, y) in script_points
                else " [位置证据]"
            )
            rows.append(
                f"- {source}：{separator.join(items.values())}  @({format_number(x)},{format_number(y)}){note}"
            )
    return tuple(rows)


def _candidate_relation(relation: ItemRelation) -> bool:
    return (
        relation.confidence is RelationConfidence.CLUE
        or relation.completeness is RelationCompleteness.CONFLICT
    )


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


def _code_name(
    md: MapData, code: str, objects: PlacementObjectIndex | None = None
) -> str:
    objects = objects if objects is not None else PlacementObjectIndex(md)
    categories = set(objects.categories.get(code, ()))
    base = BASE_OBJECTS.get(code)
    if base is not None:
        categories.add(base[0])
    if len(categories) == 1:
        return objects.name(next(iter(categories)), code)
    if categories:
        return "同码候选：" + " / ".join(
            f"{objects.name(category, code)}[{category}]"
            for category in sorted(categories)
        )
    return code


def _text_api(call: ScriptBehaviorCall) -> str:
    return call.canonical or call.callee.removeprefix("_G.").removeprefix("_ENV.")


def _call_text(call: ScriptBehaviorCall, index: int, wts: dict[int, str]) -> str | None:
    if index >= len(call.arguments):
        return None
    argument = call.arguments[index].strip()
    if call.language not in {"JASS", "Lua"} or (
        call.language == "JASS" and not argument.startswith('"')
    ):
        return None
    value = decode_script_literal(argument, lua=call.language == "Lua")
    return (
        _resolve_text(value.value, wts)
        if value.complete and value.value is not None
        else None
    )


def _unresolved_text_call(call: ScriptBehaviorCall, role: str) -> tuple[str, ...]:
    notes = "; ".join(call.diagnostics) or "文本实参不是完整已知字面量"
    return (
        f"- 未确认{role}调用〔{call.source}:{call.line} / 偏移{call.offset}〕：{call.raw}",
        "  诊断：" + notes,
    )
