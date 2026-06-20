"""GUI 工作台总览与分析报告格式化。"""
from __future__ import annotations

from dataclasses import dataclass
import os

from .api import MapData


@dataclass(frozen=True, slots=True)
class GuiReportBlock:
    title: str
    lines: tuple[str, ...]
    warning_count: int = 0


def build_overview_blocks(
    md: MapData,
    *,
    command_count: int = 0,
    recipe_count: int = 0,
) -> tuple[GuiReportBlock, ...]:
    """构建编辑器首页的短摘要。"""
    counts = md.category_counts()
    object_lines = tuple(_format_counts(counts))
    script_lines = [f"脚本文件 {len(md.scripts)}", f"聊天指令 {command_count}", f"合成配方 {recipe_count}"]
    if md.script_features:
        script_lines.append("脚本特征 " + "、".join(md.script_features))
    scene_lines = [f"预放置单位 {len(md.units)}", f"装饰物/可破坏物 {len(md.doodads)}"]
    if md.w3i is not None:
        width = getattr(md.w3i, "width", "?")
        height = getattr(md.w3i, "height", "?")
        script_type = getattr(md.w3i, "script_type", "") or "?"
        scene_lines.append(f"地图尺寸 {width}×{height}")
        scene_lines.append(f"脚本语言 {script_type}")
    warning_count = sum(block.warning_count for block in build_analysis_blocks(md))
    risk_line = "未发现高优先级风险" if warning_count == 0 else f"发现 {warning_count} 项风险/警告"
    return (
        GuiReportBlock("地图", (f"地图: {md.name}", f"路径: {md.path}")),
        GuiReportBlock("对象编辑器", object_lines or ("无对象数据",)),
        GuiReportBlock("触发与脚本", tuple(script_lines)),
        GuiReportBlock("场景", tuple(scene_lines)),
        GuiReportBlock("风险快照", (risk_line,), warning_count),
    )


def build_analysis_blocks(md: MapData) -> tuple[GuiReportBlock, ...]:
    """构建完整分析报告块，供 GUI 文本面板展示。"""
    blocks: list[GuiReportBlock] = []
    blocks.append(_audit_block(md))
    blocks.append(_script_diagnostic_block(md))
    blocks.append(_crash_block(md))
    blocks.append(_cheat_block(md))
    blocks.append(_order_block(md))
    blocks.append(_resource_block(md))
    blocks.append(_compat_block(md))
    blocks.extend(_archive_blocks(md))
    return tuple(block for block in blocks if block.lines)


def format_blocks(blocks: tuple[GuiReportBlock, ...]) -> str:
    """把报告块格式化成适合 CTkTextbox 的只读文本。"""
    chunks: list[str] = []
    for block in blocks:
        marker = f"【{block.title}】"
        chunks.append("\n".join((marker, *block.lines)))
    return "\n\n".join(chunks)


def _format_counts(counts: dict[str, int]) -> tuple[str, ...]:
    order = ("单位", "物品", "技能", "科技", "可破坏物", "装饰物", "增益")
    lines = [f"{cat} {counts[cat]}" for cat in order if cat in counts]
    lines.extend(f"{cat} {count}" for cat, count in counts.items() if cat not in order)
    return tuple(lines)


def _audit_block(md: MapData) -> GuiReportBlock:
    from .audit import AuditSeverity, build_audit_report

    report = build_audit_report(md)
    lines = tuple(f"[{_severity_label(item.severity)}] {item.title}: {item.detail}" for item in report.items)
    warnings = sum(1 for item in report.items if item.severity is AuditSeverity.WARNING)
    return GuiReportBlock("审计", lines, warnings)


def _script_diagnostic_block(md: MapData) -> GuiReportBlock:
    from .diagnostics import build_script_diagnostics

    report = build_script_diagnostics(md)
    lines = tuple(f"[警告] {item.title}: {item.detail}" for item in report.items)
    return GuiReportBlock("脚本诊断", lines, len(report.items))


def _crash_block(md: MapData) -> GuiReportBlock:
    from .crash import build_crash_report

    report = build_crash_report(md)
    lines = tuple(_format_crash_line(item) for item in report.items)
    return GuiReportBlock("崩溃风险", lines, len(report.items))


def _format_crash_line(item) -> str:
    location = item.source or f"{item.object_name}({item.object_id})"
    return f"[警告] {item.title}: {location} · {item.detail}"


def _cheat_block(md: MapData) -> GuiReportBlock:
    from .cheats import build_cheat_report

    report = build_cheat_report(md)
    lines = tuple(f"[警告] {item.phrase}: {item.source} · {item.script}" for item in report.items)
    return GuiReportBlock("秘籍/调试口令", lines, len(report.items))


def _order_block(md: MapData) -> GuiReportBlock:
    from .orders import build_order_report

    report = build_order_report(md)
    lines: list[str] = []
    if report.uses:
        lines.append(f"命令引用 {len(report.uses)}")
    for collision in report.collisions:
        sources = "、".join(use.source for use in collision.uses[:4])
        lines.append(f"[警告] 冲突 {collision.order}: {sources}")
    return GuiReportBlock("命令", tuple(lines), len(report.collisions))


def _resource_block(md: MapData) -> GuiReportBlock:
    from .resources import build_resource_report

    report = build_resource_report(md)
    if not report.nodes and not report.archive_assets:
        return GuiReportBlock("资源", ())
    lines = [
        f"引用素材 {len(report.nodes)}",
        f"内部素材 {len(report.archive_assets)}",
        f"未引用素材 {len(report.unreferenced_assets)}",
    ]
    lines.extend(f"[警告] 未引用素材: {path}" for path in report.unreferenced_assets[:10])
    return GuiReportBlock("资源", tuple(lines), len(report.unreferenced_assets))


def _compat_block(md: MapData) -> GuiReportBlock:
    from .compat import CompatSeverity, build_compat_report

    report = build_compat_report(md)
    lines = tuple(f"[{_severity_label(item.severity)}] {item.title}: {item.detail}" for item in report.items)
    warnings = sum(1 for item in report.items if item.severity is CompatSeverity.WARNING)
    return GuiReportBlock("兼容", lines, warnings)


def _archive_blocks(md: MapData) -> tuple[GuiReportBlock, ...]:
    lines = [f"内部文件 {len(md.all_files)}", f"子地图 {len(md.sub_maps)}"]
    blocks = [GuiReportBlock("内部结构", tuple(lines))]
    if not os.path.exists(md.path):
        return tuple(blocks)
    terrain = _terrain_block(md)
    slk = _slk_block(md)
    gameplay = _gameplay_block(md)
    return tuple(block for block in (*blocks, terrain, slk, gameplay) if block.lines)


def _terrain_block(md: MapData) -> GuiReportBlock:
    from .terrain import terrain_info_from_map_path
    from .terrain_tiles import format_terrain_tile_list

    info = terrain_info_from_map_path(md.path)
    if info is None:
        return GuiReportBlock("地形", ())
    lines = [
        f"网格 {info.width}×{info.height}",
        f"基础地形 {info.base_tileset}",
        f"自定义地形集 {'是' if info.custom_tilesets else '否'}",
    ]
    if info.ground_tiles:
        lines.append("地表纹理 " + format_terrain_tile_list(info.ground_tiles))
    if info.cliff_tiles:
        lines.append("悬崖纹理 " + format_terrain_tile_list(info.cliff_tiles))
    return GuiReportBlock("地形", tuple(lines))


def _slk_block(md: MapData) -> GuiReportBlock:
    from .slkmeta import slk_inventory_from_map_path

    report = slk_inventory_from_map_path(md.path)
    if not report.has_data:
        return GuiReportBlock("SLK", ())
    lines = [f"表文件 {len(report.files)}"]
    lines.extend(f"{item.path}: {item.rows} 行 · {item.columns} 列" for item in report.files[:10])
    return GuiReportBlock("SLK", tuple(lines))


def _gameplay_block(md: MapData) -> GuiReportBlock:
    from .gameplay import gameplay_constants_from_map_path

    constants = gameplay_constants_from_map_path(md.path)
    if not constants:
        return GuiReportBlock("游戏常数", ())
    lines = [f"覆盖项 {len(constants)}"]
    lines.extend(f"{item.section + '.' if item.section else ''}{item.key}={item.value}" for item in constants[:10])
    return GuiReportBlock("游戏常数", tuple(lines))


def _severity_label(severity) -> str:
    return "警告" if severity.name == "WARNING" else "提示"
