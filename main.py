"""魔兽地图提取器 — 程序入口。

直接运行启动 GUI；带参数 `cli <地图路径>` 时走命令行快速查看。
"""
from __future__ import annotations

from collections.abc import Iterator
import sys
from typing import TYPE_CHECKING, assert_never

if TYPE_CHECKING:
    from w3xtool.api import MapData
    from w3xtool.gameconfig import GameConfiguration, GameConfigPlayer

from w3xtool.wtg_diagnostics import format_summary_diagnostics


def iter_cli_summary_lines(md: MapData) -> Iterator[str]:
    """把已解析地图渲染成 CLI 摘要行，便于测试与复用。"""
    yield f"地图: {md.name}"
    if md.w3i:
        w = md.w3i
        yield (f"  作者: {w.author or '未知'}  脚本: {w.script_type or '?'}"
               f"  玩家: {len(w.players)}  队伍: {len(w.forces)}  尺寸: {w.width}×{w.height}")
    for cat, objs in md.objects.items():
        yield f"  {cat}: {len(objs)}"
    if md.units or md.doodads:
        yield f"  预放置单位: {len(md.units)}  装饰物/可破坏物: {len(md.doodads)}"
    if md.regions or md.cameras or md.sounds:
        yield f"  区域: {len(md.regions)}  镜头: {len(md.cameras)}  声音: {len(md.sounds)}"
    if getattr(md, "game_configs", None):
        yield f"  游戏配置: {len(md.game_configs)}"
    trigger_summary = getattr(md, "trigger_summary", None)
    if trigger_summary is not None:
        yield (f"  触发器: {trigger_summary.trigger_count}  "
               f"变量: {trigger_summary.variable_count}  分类: {trigger_summary.category_count}")
    preview_icons = getattr(md, "preview_icons", None)
    if preview_icons is not None:
        yield f"  小地图标记: {preview_icons.icon_count}"
    import_summary = getattr(md, "import_summary", None)
    if import_summary is not None:
        yield f"  导入资源: {import_summary.entry_count}"
    if getattr(md, "script_features", None):
        yield f"  脚本特征: {'、'.join(md.script_features)}"

    refs = getattr(md, "references", {}) or {}
    orphans = getattr(md, "orphans", []) or []
    if refs or orphans:
        edges = sum(len(codes) for entries in refs.values()
                    for _label, codes in entries)
        yield f"  引用关系: {len(refs)} 个对象有引用 · {edges} 条引用边"
        if getattr(md, "ref_low_coverage", False):
            yield ("  孤立自定义对象: "
                   f"{len(orphans)}（注意：引用覆盖低，疑为 SLK 优化图，"
                   "多为误报，仅供参考）")
        else:
            suffix = "（无人引用，可能是废弃对象）" if orphans else ""
            yield f"  孤立自定义对象: {len(orphans)}{suffix}"
        for orphan in orphans[:10]:
            yield f"    - [{orphan.category}] {orphan.name}({orphan.obj_id})"
        if len(orphans) > 10:
            yield f"    …… 另有 {len(orphans) - 10} 个"

    from w3xtool.cli_terrain import iter_terrain_summary_lines
    yield from iter_terrain_summary_lines(md)
    yield from _trigger_tree_summary_lines(md)
    yield from _preview_icon_summary_lines(md)
    yield from _game_config_summary_lines(md)
    from w3xtool.cli_structure import iter_map_structure_summary_lines
    yield from iter_map_structure_summary_lines(md)
    yield from _slk_summary_lines(md)
    yield from _gameplay_constant_summary_lines(md)
    yield from _script_diagnostic_lines(md)
    yield from _crash_risk_lines(md)
    yield from _cheat_residue_lines(md)
    yield from _order_summary_lines(md)
    yield from _import_summary_lines(md)
    yield from _resource_summary_lines(md)
    yield from _compat_summary_lines(md)

    from w3xtool.audit import AuditSeverity, build_audit_report
    report = build_audit_report(md)
    if not report.items:
        return
    yield "  审计:"
    for item in report.items:
        match item.severity:
            case AuditSeverity.WARNING:
                level = "警告"
            case AuditSeverity.INFO:
                level = "提示"
            case unreachable:
                assert_never(unreachable)
        yield f"    [{level}] {item.title}: {item.detail}"


def iter_game_config_summary_lines(source: str, config: GameConfiguration) -> Iterator[str]:
    """Render a standalone .wgc file summary."""
    yield f"游戏配置: {source}"
    yield f"  地图路径: {config.map_path or '(未指定)'}"
    yield f"  速度: {config.speed_label}  玩家槽: {len(config.players)}"
    rule_tags = _game_config_rule_tags(config)
    if rule_tags:
        yield f"  规则: {'、'.join(rule_tags)}"
    yield (
        f"  用户: {config.human_count}  电脑: {config.computer_count}"
        f"  观察者: {config.observer_count}"
    )
    for player in config.players[:12]:
        yield "    - " + _format_game_config_player(player)
    if len(config.players) > 12:
        yield f"    …… 另有 {len(config.players) - 12} 个玩家槽"


def _resource_summary_lines(md: MapData) -> Iterator[str]:
    from w3xtool.resources import build_resource_report
    report = build_resource_report(md)
    if not report.nodes and not report.archive_assets:
        return
    yield "  资源:"
    yield (f"    引用素材: {len(report.nodes)}  内部素材: {len(report.archive_assets)}"
           f"  未引用素材: {len(report.unreferenced_assets)}")
    for path in report.unreferenced_assets[:5]:
        yield f"    - 未引用素材: {path}"
    if len(report.unreferenced_assets) > 5:
        yield f"    …… 另有 {len(report.unreferenced_assets) - 5} 个"


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
        ext_text = "、".join(f"{ext}:{count}" for ext, count in summary.extension_counts[:6])
        yield f"    类型: {ext_text}"
    for path in summary.missing_paths[:5]:
        yield f"    - 疑似缺失: {path}"
    if len(summary.missing_paths) > 5:
        yield f"    …… 另有 {len(summary.missing_paths) - 5} 个疑似缺失资源"


def _game_config_summary_lines(md: MapData) -> Iterator[str]:
    configs = getattr(md, "game_configs", None) or []
    if not configs:
        return
    yield "  游戏配置:"
    for entry in configs[:4]:
        cfg = entry.config
        yield (
            f"    - {entry.source}: {cfg.map_path or '(未指定地图)'}"
            f"  速度: {cfg.speed_label}  玩家槽: {len(cfg.players)}"
        )
        rule_tags = _game_config_rule_tags(cfg)
        if rule_tags:
            yield f"      规则: {'、'.join(rule_tags)}"
        ai_players = [p for p in cfg.players if p.load_custom_ai and p.custom_ai_path]
        for player in ai_players[:3]:
            yield f"      自定义AI: P{player.slot_id + 1} {player.custom_ai_path}"
        if len(ai_players) > 3:
            yield f"      …… 另有 {len(ai_players) - 3} 个自定义AI"
    if len(configs) > 4:
        yield f"    …… 另有 {len(configs) - 4} 个配置"


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
        yield f"    分类: {_format_summary_list(tuple(cat.name for cat in summary.categories if cat.name))}"
    if summary.variables:
        yield f"    变量: {_format_summary_list(tuple(var.name for var in summary.variables if var.name))}"
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


def _game_config_rule_tags(config: GameConfiguration) -> list[str]:
    tags = []
    if config.fog_of_war_disabled:
        tags.append("禁用战争迷雾")
    if config.victory_defeat_disabled:
        tags.append("禁用胜负条件")
    return tags


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


def _format_game_config_player(player: GameConfigPlayer) -> str:
    parts = [
        f"P{player.slot_id + 1}",
        player.kind_label,
        f"队伍{player.team + 1}",
        player.race_label,
        player.color_label,
        f"让分{player.handicap}%",
    ]
    if not player.is_user and not player.is_observer:
        parts.append(f"AI:{player.ai_difficulty_label}")
    if player.load_custom_ai and player.custom_ai_path:
        path_kind = "绝对" if player.ai_path_is_absolute else "相对"
        parts.append(f"自定义AI({path_kind}):{player.custom_ai_path}")
    return "  ".join(parts)


def _slk_summary_lines(md: MapData) -> Iterator[str]:
    from w3xtool.slkmeta import slk_inventory_from_map_path
    report = slk_inventory_from_map_path(md.path)
    if not report.has_data:
        return
    yield "  SLK:"
    yield f"    表文件: {len(report.files)}"
    for item in report.files[:6]:
        yield f"    - {item.path}: {item.rows} 行 · {item.columns} 列"
    if len(report.files) > 6:
        yield f"    …… 另有 {len(report.files) - 6} 个"


def _gameplay_constant_summary_lines(md: MapData) -> Iterator[str]:
    from w3xtool.gameplay import gameplay_constants_from_map_path
    constants = gameplay_constants_from_map_path(md.path)
    if not constants:
        return
    yield "  游戏常数:"
    yield f"    覆盖项: {len(constants)}"
    for item in constants[:6]:
        prefix = f"{item.section}." if item.section else ""
        yield f"    - {prefix}{item.key}={item.value}"
    if len(constants) > 6:
        yield f"    …… 另有 {len(constants) - 6} 项"


def _format_summary_list(items: tuple[str, ...]) -> str:
    shown = "、".join(items[:5])
    if len(items) <= 5:
        return shown
    return f"{shown} …… 另有 {len(items) - 5} 个"


def _order_summary_lines(md: MapData) -> Iterator[str]:
    from w3xtool.orders import build_order_report
    report = build_order_report(md)
    if not report.uses:
        return
    yield "  命令:"
    yield f"    命令引用: {len(report.uses)}  冲突: {len(report.collisions)}"
    for collision in report.collisions[:5]:
        sources = "、".join(use.source for use in collision.uses[:4])
        yield f"    - 冲突 {collision.order}: {sources}"
    if len(report.collisions) > 5:
        yield f"    …… 另有 {len(report.collisions) - 5} 个"
    by_order = report.by_order
    for order, uses in list(by_order.items())[:5]:
        sources = "、".join(use.source for use in uses[:4])
        yield f"    - {order}: {sources}"
    if len(by_order) > 5:
        yield f"    …… 另有 {len(by_order) - 5} 种命令"


def _script_diagnostic_lines(md: MapData) -> Iterator[str]:
    from w3xtool.diagnostics import build_script_diagnostics
    report = build_script_diagnostics(md)
    if not report.items:
        return
    yield "  脚本诊断:"
    for item in report.items:
        yield f"    [警告] {item.title}: {item.detail}"


def _crash_risk_lines(md: MapData) -> Iterator[str]:
    from w3xtool.crash import build_crash_report
    report = build_crash_report(md)
    if not report.items:
        return
    yield "  崩溃风险:"
    for item in report.items[:6]:
        location = item.source or f"{item.object_name}({item.object_id})"
        yield f"    [警告] {item.title}: {location} · {item.detail}"
    if len(report.items) > 6:
        yield f"    …… 另有 {len(report.items) - 6} 个"


def _cheat_residue_lines(md: MapData) -> Iterator[str]:
    from w3xtool.cheats import build_cheat_report
    report = build_cheat_report(md)
    if not report.items:
        return
    yield "  秘籍/调试口令:"
    for item in report.items[:6]:
        yield f"    [警告] {item.phrase}: {item.source} · {item.script}"
    if len(report.items) > 6:
        yield f"    …… 另有 {len(report.items) - 6} 个"


def _compat_summary_lines(md: MapData) -> Iterator[str]:
    from w3xtool.compat import CompatSeverity, build_compat_report
    report = build_compat_report(md)
    yield "  兼容:"
    for item in report.items:
        match item.severity:
            case CompatSeverity.WARNING:
                level = "警告"
            case CompatSeverity.INFO:
                level = "提示"
            case unreachable:
                assert_never(unreachable)
        yield f"    [{level}] {item.title}: {item.detail}"


def main():
    if len(sys.argv) >= 3 and sys.argv[1] in {"wgc", "gameconfig"}:
        from w3xtool.gameconfig import read_game_configuration_file
        try:
            config = read_game_configuration_file(sys.argv[2])
        except Exception as e:
            print(f"无法解析游戏配置：{type(e).__name__}: {e}")
            return
        for line in iter_game_config_summary_lines(sys.argv[2], config):
            print(line)
        return
    if len(sys.argv) >= 3 and sys.argv[1] == "cli":
        # 控制台输出编码处理：
        #  - 交互控制台(isatty)：保留原编码(中文 Windows 多为 cp936，中文照常显示)，
        #    仅把不可编码字符(如 emoji)降级为占位，避免 print 硬崩。
        #  - 重定向/管道(非 tty)：统一用 UTF-8，便于现代工具/文件读取(否则打包 exe 重定向
        #    时会写出 cp936 字节，UTF-8 读者看到乱码)。
        try:
            out = sys.stdout
            if out is not None:
                if out.isatty():
                    out.reconfigure(errors="replace")
                else:
                    out.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
        from w3xtool.api import load_map
        path = sys.argv[2]
        if path.lower().endswith(".wgc"):
            from w3xtool.gameconfig import read_game_configuration_file
            try:
                config = read_game_configuration_file(path)
            except Exception as e:
                print(f"无法解析游戏配置：{type(e).__name__}: {e}")
                return
            for line in iter_game_config_summary_lines(path, config):
                print(line)
            return
        try:
            md = load_map(path)
        except Exception as e:
            # 非法/损坏/空文件等：给一句友好提示，而非抛裸 traceback(GUI 已优雅处理，CLI 也对齐)
            print(f"无法解析地图：{type(e).__name__}: {e}")
            return
        for line in iter_cli_summary_lines(md):
            print(line)
        return
    from w3xtool.single_instance import ensure_single_instance
    ensure_single_instance()          # 单实例：先关掉上一个实例再启动，不允许多开
    from w3xtool.gui import main as gui_main
    gui_main()


if __name__ == "__main__":
    main()
