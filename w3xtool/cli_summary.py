"""Map-level CLI summary composition."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

from .cli_detail_summary import (
    iter_audit_summary_lines,
    iter_cheat_residue_lines,
    iter_compat_summary_lines,
    iter_crash_risk_lines,
    iter_gameplay_constant_summary_lines,
    iter_order_summary_lines,
    iter_resource_summary_lines,
    iter_script_diagnostic_lines,
    iter_slk_summary_lines,
)
from .game_config_summary import iter_embedded_game_config_summary_lines
from .wtg_diagnostics import format_summary_diagnostics

if TYPE_CHECKING:
    from .api import MapData
    from .wtg import TriggerHeader


def iter_cli_summary_lines(md: MapData) -> Iterator[str]:
    """Render a loaded map as stable CLI summary lines."""
    yield f"地图: {md.name}"
    if md.w3i:
        info = md.w3i
        yield (
            f"  作者: {info.author or '未知'}  脚本: {info.script_type or '?'}"
            f"  玩家: {len(info.players)}  队伍: {len(info.forces)}"
            f"  尺寸: {info.width}×{info.height}"
        )
    for category, objects in md.objects.items():
        yield f"  {category}: {len(objects)}"
    if md.units or md.doodads:
        yield f"  预放置单位: {len(md.units)}  装饰物/可破坏物: {len(md.doodads)}"
    if md.regions or md.cameras or md.sounds:
        yield f"  区域: {len(md.regions)}  镜头: {len(md.cameras)}  声音: {len(md.sounds)}"
    if getattr(md, "game_configs", None):
        yield f"  游戏配置: {len(md.game_configs)}"
    trigger_summary = getattr(md, "trigger_summary", None)
    if trigger_summary is not None:
        yield (
            f"  触发器: {trigger_summary.trigger_count}  "
            f"变量: {trigger_summary.variable_count}  分类: {trigger_summary.category_count}"
        )
    preview_icons = getattr(md, "preview_icons", None)
    if preview_icons is not None:
        yield f"  小地图标记: {preview_icons.icon_count}"
    import_summary = getattr(md, "import_summary", None)
    if import_summary is not None:
        yield f"  导入资源: {import_summary.entry_count}"
    if getattr(md, "script_features", None):
        yield f"  脚本特征: {'、'.join(md.script_features)}"

    yield from _reference_summary_lines(md)
    from .cli_terrain import iter_terrain_summary_lines

    yield from iter_terrain_summary_lines(md)
    yield from _trigger_tree_summary_lines(md)
    yield from _preview_icon_summary_lines(md)
    yield from iter_embedded_game_config_summary_lines(md)
    from .cli_structure import iter_map_structure_summary_lines

    yield from iter_map_structure_summary_lines(md)
    yield from iter_slk_summary_lines(md)
    yield from iter_gameplay_constant_summary_lines(md)
    yield from iter_script_diagnostic_lines(md)
    yield from iter_crash_risk_lines(md)
    yield from iter_cheat_residue_lines(md)
    yield from iter_order_summary_lines(md)
    yield from _import_summary_lines(md)
    yield from iter_resource_summary_lines(md)
    yield from iter_compat_summary_lines(md)
    yield from iter_audit_summary_lines(md)


def _reference_summary_lines(md: MapData) -> Iterator[str]:
    refs = getattr(md, "references", {}) or {}
    orphans = getattr(md, "orphans", []) or []
    if not refs and not orphans:
        return
    edges = sum(len(codes) for entries in refs.values() for _label, codes in entries)
    yield f"  引用关系: {len(refs)} 个对象有引用 · {edges} 条引用边"
    if getattr(md, "ref_low_coverage", False):
        yield (
            f"  孤立自定义对象: {len(orphans)}（注意：引用覆盖低，疑为 SLK 优化图，"
            "多为误报，仅供参考）"
        )
    else:
        suffix = "（无人引用，可能是废弃对象）" if orphans else ""
        yield f"  孤立自定义对象: {len(orphans)}{suffix}"
    for orphan in orphans[:10]:
        yield f"    - [{orphan.category}] {orphan.name}({orphan.obj_id})"
    if len(orphans) > 10:
        yield f"    …… 另有 {len(orphans) - 10} 个"


def _import_summary_lines(md: MapData) -> Iterator[str]:
    summary = getattr(md, "import_summary", None)
    if summary is None:
        return
    yield "  导入资源:"
    yield (
        f"    记录: {summary.entry_count}  标准路径: {summary.standard_count}"
        f"  自定义路径: {summary.custom_count}  疑似缺失: {len(summary.missing_paths)}"
    )
    if summary.unknown_count:
        yield f"    未知标志: {summary.unknown_count}"
    if summary.extension_counts:
        extension_text = "、".join(
            f"{extension}:{count}" for extension, count in summary.extension_counts[:6]
        )
        yield f"    类型: {extension_text}"
    for path in summary.missing_paths[:5]:
        yield f"    - 疑似缺失: {path}"
    if len(summary.missing_paths) > 5:
        yield f"    …… 另有 {len(summary.missing_paths) - 5} 个疑似缺失资源"


def _trigger_tree_summary_lines(md: MapData) -> Iterator[str]:
    summary = getattr(md, "trigger_summary", None)
    if summary is None:
        return
    yield "  触发器树:"
    kind = "重制版" if summary.is_reforged else "经典"
    yield (
        f"    格式: {kind} v{summary.version}  触发器: {summary.trigger_count}"
        f"  变量: {summary.variable_count}  分类: {summary.category_count}"
    )
    if summary.comment_count or summary.script_count:
        yield f"    注释: {summary.comment_count}  自定义脚本块: {summary.script_count}"
    if summary.categories:
        names = tuple(category.name for category in summary.categories if category.name)
        yield f"    分类: {_format_summary_list(names)}"
    if summary.variables:
        names = tuple(variable.name for variable in summary.variables if variable.name)
        yield f"    变量: {_format_summary_list(names)}"
    for trigger in summary.triggers[:6]:
        tags = _trigger_tags(trigger)
        suffix = f"  ·  {'/'.join(tags)}" if tags else ""
        yield f"    - {trigger.name or '(未命名触发器)'}{suffix}"
    if len(summary.triggers) > 6:
        yield f"    …… 另有 {len(summary.triggers) - 6} 个已解析触发器头"
    for diagnostic in format_summary_diagnostics(summary):
        yield f"    {diagnostic}"


def _preview_icon_summary_lines(md: MapData) -> Iterator[str]:
    summary = getattr(md, "preview_icons", None)
    if summary is None:
        return
    yield "  小地图标记:"
    yield (
        f"    总数: {summary.icon_count}  玩家出生点: {summary.player_start_count}"
        f"  金矿: {summary.gold_mine_count}  中立建筑: {summary.neutral_building_count}"
    )
    for icon in summary.icons[:8]:
        yield f"    - {icon.type_label} ({icon.x}, {icon.y})  RGB{icon.color_rgb}"
    if len(summary.icons) > 8:
        yield f"    …… 另有 {len(summary.icons) - 8} 个标记"


def _trigger_tags(trigger: TriggerHeader) -> list[str]:
    tags: list[str] = []
    if not trigger.is_enabled:
        tags.append("禁用")
    if trigger.is_custom_text:
        tags.append("自定义脚本")
    if trigger.is_initially_off:
        tags.append("初始关闭")
    if trigger.run_on_init:
        tags.append("开局运行")
    if trigger.is_comment:
        tags.append("注释")
    return tags


def _format_summary_list(items: tuple[str, ...]) -> str:
    shown = "、".join(items[:5])
    if len(items) <= 5:
        return shown
    return f"{shown} …… 另有 {len(items) - 5} 个"
