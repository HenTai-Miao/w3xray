"""GUI 工作台总览与分析报告格式化。"""

from __future__ import annotations

from dataclasses import dataclass

from .api import MapData
from .wtg_diagnostics import format_summary_diagnostics


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
    script_lines = [
        f"脚本文件 {len(md.scripts)}",
        f"聊天指令 {command_count}",
        f"合成配方 {recipe_count}",
    ]
    trigger_summary = getattr(md, "trigger_summary", None)
    if trigger_summary is not None:
        script_lines.append(f"触发器树 {trigger_summary.trigger_count}")
    if md.script_features:
        script_lines.append("脚本特征 " + "、".join(md.script_features))
    scene_lines = [f"预放置单位 {len(md.units)}", f"装饰物/可破坏物 {len(md.doodads)}"]
    if getattr(md, "game_configs", None):
        scene_lines.append(f"游戏配置 {len(md.game_configs)}")
    preview_icons = getattr(md, "preview_icons", None)
    if preview_icons is not None:
        scene_lines.append(f"小地图标记 {preview_icons.icon_count}")
    if md.w3i is not None:
        width = getattr(md.w3i, "width", "?")
        height = getattr(md.w3i, "height", "?")
        script_type = getattr(md.w3i, "script_type", "") or "?"
        scene_lines.append(f"地图尺寸 {width}×{height}")
        scene_lines.append(f"脚本语言 {script_type}")
    warning_count = sum(block.warning_count for block in build_analysis_blocks(md))
    risk_line = (
        "未发现高优先级风险"
        if warning_count == 0
        else f"发现 {warning_count} 项风险/警告"
    )
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
    from .gui_script_mechanics_reports import build_script_mechanics_block

    blocks.append(build_script_mechanics_block(md))
    from .gui_ui_text_reports import build_ui_text_block

    blocks.append(build_ui_text_block(md))
    blocks.append(_crash_block(md))
    blocks.append(_cheat_block(md))
    blocks.append(_order_block(md))
    blocks.append(_resource_block(md))
    from .gui_resource_reports import build_resource_inventory_block

    blocks.append(build_resource_inventory_block(md))
    from .gui_extraction_reports import build_extraction_completeness_block

    blocks.append(build_extraction_completeness_block(md))
    blocks.append(_save_id_block(md))
    blocks.append(_compat_block(md))
    blocks.append(_trigger_tree_block(md))
    blocks.append(_preview_icon_block(md))
    blocks.append(_game_config_block(md))
    from .gui_archive_reports import build_archive_blocks

    blocks.extend(build_archive_blocks(md))
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
    lines = tuple(
        f"[{_severity_label(item.severity)}] {item.title}: {item.detail}"
        for item in report.items
    )
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
    lines = tuple(
        f"[警告] {item.phrase}: {item.source} · {item.script}" for item in report.items
    )
    return GuiReportBlock("秘籍/调试口令", lines, len(report.items))


def _order_block(md: MapData) -> GuiReportBlock:
    from .orders import build_order_report

    report = build_order_report(md)
    lines: list[str] = []
    if report.uses:
        lines.append(f"命令引用 {len(report.uses)}")
    for collision in report.collisions:
        sources = "、".join(use.source for use in collision.uses)
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
    lines.extend(f"[警告] 未引用素材: {path}" for path in report.unreferenced_assets)
    return GuiReportBlock("资源", tuple(lines), len(report.unreferenced_assets))


def _save_id_block(md: MapData) -> GuiReportBlock:
    from .save_analysis import build_save_report

    report = build_save_report(md)
    if report.total == 0:
        return GuiReportBlock("存档/ID线索", ())
    counts = "、".join(
        f"{name} {count}" for name, count in sorted(report.mechanism_counts.items())
    )
    lines = [f"线索 {report.total}", f"机制 {counts}"]
    if report.object_codes:
        lines.append("对象码 " + "、".join(report.object_codes))
    lines.extend(row.summary for row in report.rows)
    return GuiReportBlock("存档/ID线索", tuple(lines))


def _game_config_block(md: MapData) -> GuiReportBlock:
    configs = getattr(md, "game_configs", None) or []
    if not configs:
        return GuiReportBlock("游戏配置", ())
    lines: list[str] = []
    for entry in configs:
        cfg = entry.config
        lines.append(
            f"{entry.source}: {cfg.map_path or '(未指定地图)'} · "
            f"速度 {cfg.speed_label} · 玩家槽 {len(cfg.players)}"
        )
        rule_tags = []
        if cfg.fog_of_war_disabled:
            rule_tags.append("禁用战争迷雾")
        if cfg.victory_defeat_disabled:
            rule_tags.append("禁用胜负条件")
        if rule_tags:
            lines.append("规则: " + "、".join(rule_tags))
        custom_ai = [p for p in cfg.players if p.load_custom_ai and p.custom_ai_path]
        for player in custom_ai:
            lines.append(f"自定义AI: P{player.slot_id + 1} {player.custom_ai_path}")
    return GuiReportBlock("游戏配置", tuple(lines))


def _trigger_tree_block(md: MapData) -> GuiReportBlock:
    summary = getattr(md, "trigger_summary", None)
    if summary is None:
        return GuiReportBlock("触发器树", ())
    kind = "重制版" if summary.is_reforged else "经典"
    lines = [
        f"格式 {kind} v{summary.version}",
        f"触发器 {summary.trigger_count} · 变量 {summary.variable_count} · 分类 {summary.category_count}",
    ]
    if summary.comment_count or summary.script_count:
        lines.append(
            f"注释 {summary.comment_count} · 自定义脚本块 {summary.script_count}"
        )
    if summary.categories:
        lines.append("分类 " + _join_names(cat.name for cat in summary.categories))
    if summary.variables:
        lines.append("变量 " + _join_names(var.name for var in summary.variables))
    for trigger in summary.triggers:
        tags = _trigger_tags(trigger)
        suffix = f" · {'/'.join(tags)}" if tags else ""
        lines.append(f"{trigger.name or '(未命名触发器)'}{suffix}")
    lines.extend(format_summary_diagnostics(summary))
    return GuiReportBlock("触发器树", tuple(lines))


def _preview_icon_block(md: MapData) -> GuiReportBlock:
    summary = getattr(md, "preview_icons", None)
    if summary is None:
        return GuiReportBlock("小地图标记", ())
    lines = [
        f"总数 {summary.icon_count}",
        (
            f"玩家出生点 {summary.player_start_count} · 金矿 {summary.gold_mine_count}"
            f" · 中立建筑 {summary.neutral_building_count}"
        ),
    ]
    for icon in summary.icons:
        lines.append(f"{icon.type_label} ({icon.x}, {icon.y})")
    return GuiReportBlock("小地图标记", tuple(lines))


def _compat_block(md: MapData) -> GuiReportBlock:
    from .compat import CompatSeverity, build_compat_report

    report = build_compat_report(md)
    lines = tuple(
        f"[{_severity_label(item.severity)}] {item.title}: {item.detail}"
        for item in report.items
    )
    warnings = sum(
        1 for item in report.items if item.severity is CompatSeverity.WARNING
    )
    return GuiReportBlock("兼容", lines, warnings)


def _severity_label(severity) -> str:
    return "警告" if severity.name == "WARNING" else "提示"


def _join_names(names) -> str:
    values = [name for name in names if name]
    return "、".join(values)


def _trigger_tags(trigger) -> list[str]:
    tags = []
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
