"""只读地图审计：把 MapData 汇总为可展示的健康提示。"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from .api import GameObject, MapData

MIN_CATEGORY_CUSTOM: Final = 10
HIGH_ORPHAN_RATIO: Final = 0.50


class AuditSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class AuditItem:
    severity: AuditSeverity
    code: str
    title: str
    detail: str


@dataclass(frozen=True, slots=True)
class AuditReport:
    items: tuple[AuditItem, ...]

    @property
    def by_code(self) -> dict[str, AuditItem]:
        return {item.code: item for item in self.items}

    @property
    def warnings(self) -> tuple[AuditItem, ...]:
        return tuple(item for item in self.items if item.severity == AuditSeverity.WARNING)


def build_audit_report(md: MapData) -> AuditReport:
    """基于已解析 MapData 构建审计报告；不重新打开 MPQ，不修改 md。"""
    objects = _all_objects(md)
    items: list[AuditItem] = []
    items.append(_inventory_item(objects))

    script_item = _script_item(md)
    if script_item is not None:
        items.append(script_item)
    else:
        items.append(AuditItem(
            AuditSeverity.WARNING,
            "script.missing",
            "未发现主脚本",
            "未解析到 war3map.j 或 war3map.lua，隐藏指令、合成与脚本引用分析会缺失。",
        ))

    if getattr(md, "w3i", None) is None and getattr(md, "w3f", None) is None:
        items.append(AuditItem(
            AuditSeverity.WARNING,
            "map_info.missing",
            "缺少地图信息",
            "未解析到 war3map.w3i，地图名、作者、玩家、队伍和脚本语言可能不完整。",
        ))

    if getattr(md, "ref_low_coverage", False):
        items.append(AuditItem(
            AuditSeverity.WARNING,
            "reference.low_coverage",
            "引用覆盖偏低",
            "对象引用字段覆盖不足，孤立对象多为误报，仅适合作为人工排查线索。",
        ))

    items.extend(_script_diagnostic_items(md))
    items.extend(_crash_items(md))
    items.extend(_cheat_items(md))
    items.extend(_orphan_ratio_items(objects, getattr(md, "orphans", []) or []))
    items.extend(_order_items(md))
    items.extend(_resource_items(md))
    items.extend(_compat_items(md))
    items.extend(_gameplay_constant_items(md))
    file_item = _file_inventory_item(md)
    if file_item is not None:
        items.append(file_item)
    return AuditReport(tuple(items))


def _all_objects(md: MapData) -> list[GameObject]:
    return [obj for group in md.objects.values() for obj in group]


def _inventory_item(objects: list[GameObject]) -> AuditItem:
    custom_count = sum(1 for obj in objects if obj.is_custom)
    categories = Counter(obj.category for obj in objects)
    cat_text = "、".join(f"{cat}{count}" for cat, count in sorted(categories.items()))
    if not cat_text:
        cat_text = "无对象数据"
    return AuditItem(
        AuditSeverity.INFO,
        "inventory.objects",
        "对象覆盖",
        f"共 {len(objects)} 个对象，其中自定义 {custom_count} 个；分类：{cat_text}。",
    )


def _script_item(md: MapData) -> AuditItem | None:
    for name in ("war3map.j", "war3map.lua"):
        text = md.scripts.get(name)
        if text and text.strip("\x00\r\n\t "):
            return AuditItem(
                AuditSeverity.INFO,
                "script.primary",
                "主脚本",
                f"已解析 {name}，可用于隐藏指令、合成和脚本引用分析。",
            )
    return None


def _orphan_ratio_items(
    objects: list[GameObject],
    orphans: list[GameObject],
) -> tuple[AuditItem, ...]:
    custom_by_cat = Counter(obj.category for obj in objects if obj.is_custom)
    orphan_by_cat = Counter(obj.category for obj in orphans if obj.is_custom)
    items: list[AuditItem] = []
    for category, total in sorted(custom_by_cat.items()):
        orphan_count = orphan_by_cat.get(category, 0)
        if total < MIN_CATEGORY_CUSTOM or orphan_count / total <= HIGH_ORPHAN_RATIO:
            continue
        items.append(AuditItem(
            AuditSeverity.WARNING,
            f"orphan.high_ratio.{category}",
            "孤立对象比例偏高",
            f"{category} 自定义对象孤立 {orphan_count}/{total}，建议结合引用覆盖提示人工确认。",
        ))
    return tuple(items)


def _file_inventory_item(md: MapData) -> AuditItem | None:
    files = getattr(md, "all_files", []) or []
    if not files:
        return None
    return AuditItem(
        AuditSeverity.INFO,
        "inventory.files",
        "内部文件",
        f"已枚举 {len(files)} 个内部文件，可结合导出功能继续检查资源。",
    )


def _gameplay_constant_items(md: MapData) -> tuple[AuditItem, ...]:
    files = {str(name).lower() for name in getattr(md, "all_files", []) or []}
    if "war3mapmisc.txt" not in files:
        return ()
    return (AuditItem(
        AuditSeverity.INFO,
        "gameplay.constants",
        "自定义游戏平衡常数",
        "发现 war3mapMisc.txt，地图包含自定义游戏平衡常数；本工具只提示存在，不修改内容。",
    ),)


def _resource_items(md: MapData) -> tuple[AuditItem, ...]:
    from .resources import build_resource_report
    report = build_resource_report(md)
    if not report.unreferenced_assets:
        return ()
    return (AuditItem(
        AuditSeverity.WARNING,
        "resources.unreferenced",
        "发现未引用素材",
        f"内部素材中有 {len(report.unreferenced_assets)} 个未被对象字段或脚本字面量引用。",
    ),)


def _script_diagnostic_items(md: MapData) -> tuple[AuditItem, ...]:
    from .diagnostics import build_script_diagnostics
    report = build_script_diagnostics(md)
    if not report.warnings:
        return ()
    return (AuditItem(
        AuditSeverity.WARNING,
        "script.diagnostics",
        "脚本诊断警告",
        f"发现 {len(report.warnings)} 个异步/本地状态/JASS 风险调用提示。",
    ),)


def _crash_items(md: MapData) -> tuple[AuditItem, ...]:
    from .crash import build_crash_report
    report = build_crash_report(md)
    if not report.items:
        return ()
    return (AuditItem(
        AuditSeverity.WARNING,
        "crash.risks",
        "发现崩溃风险配置",
        f"发现 {len(report.items)} 个已知崩溃风险配置，建议优先人工检查。",
    ),)


def _cheat_items(md: MapData) -> tuple[AuditItem, ...]:
    from .cheats import build_cheat_report
    report = build_cheat_report(md)
    if not report.items:
        return ()
    return (AuditItem(
        AuditSeverity.WARNING,
        "cheats.residue",
        "发现秘籍/调试口令残留",
        f"脚本中发现 {len(report.items)} 处官方秘籍或调试口令字符串，建议确认是否为遗留入口。",
    ),)


def _order_items(md: MapData) -> tuple[AuditItem, ...]:
    from .orders import build_order_report
    report = build_order_report(md)
    if not report.collisions:
        return ()
    return (AuditItem(
        AuditSeverity.WARNING,
        "orders.collisions",
        "命令串冲突",
        f"发现 {len(report.collisions)} 个重复命令串，可能导致技能施放互相抢命令。",
    ),)


def _compat_items(md: MapData) -> tuple[AuditItem, ...]:
    from .compat import build_compat_report
    report = build_compat_report(md)
    if not report.warnings:
        return ()
    return (AuditItem(
        AuditSeverity.WARNING,
        "compat.warnings",
        "存在版本兼容风险",
        f"按 {report.target_patch} 检查发现 {len(report.warnings)} 个兼容风险。",
    ),)
