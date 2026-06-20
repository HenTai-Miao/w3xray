"""魔兽地图提取器 — 程序入口。

直接运行启动 GUI；带参数 `cli <地图路径>` 时走命令行快速查看。
"""
from __future__ import annotations

from collections.abc import Iterator
import sys
from typing import TYPE_CHECKING, assert_never

if TYPE_CHECKING:
    from w3xtool.api import MapData


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

    yield from _terrain_summary_lines(md)
    yield from _map_structure_summary_lines(md)
    yield from _slk_summary_lines(md)
    yield from _gameplay_constant_summary_lines(md)
    yield from _script_diagnostic_lines(md)
    yield from _crash_risk_lines(md)
    yield from _cheat_residue_lines(md)
    yield from _order_summary_lines(md)
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


def _terrain_summary_lines(md: MapData) -> Iterator[str]:
    from w3xtool.terrain_tiles import format_terrain_tile_list
    from w3xtool.terrain import terrain_info_from_map_path
    info = terrain_info_from_map_path(md.path)
    if info is None:
        return
    custom = "是" if info.custom_tilesets else "否"
    yield "  地形:"
    yield (f"    网格: {info.width}×{info.height}  基础地形: {info.base_tileset}"
           f"  自定义地形集: {custom}")
    if info.ground_tiles:
        yield f"    地表纹理: {format_terrain_tile_list(info.ground_tiles)}"
    if info.cliff_tiles:
        yield f"    悬崖纹理: {format_terrain_tile_list(info.cliff_tiles)}"


def _map_structure_summary_lines(md: MapData) -> Iterator[str]:
    from w3xtool.mapmeta import map_structure_report_from_map_path
    report = map_structure_report_from_map_path(md.path)
    if not report.has_data:
        return
    yield "  地图结构:"
    parts: list[str] = []
    if report.regions is not None:
        parts.append(f"区域: {report.regions}")
    if report.cameras is not None:
        parts.append(f"镜头: {report.cameras}")
    if report.sounds is not None:
        parts.append(f"声音: {report.sounds}")
    if parts:
        yield "    " + "  ".join(parts)
    if report.pathing is not None:
        p = report.pathing
        yield f"    路径图: {p.width}×{p.height}  单元: {p.cells}"
    if report.region_strings:
        yield f"    区域条目: {_format_summary_list(report.region_strings)}"
    if report.camera_strings:
        yield f"    镜头条目: {_format_summary_list(report.camera_strings)}"
    if report.sound_strings:
        yield f"    声音条目: {_format_summary_list(report.sound_strings)}"


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
        try:
            md = load_map(sys.argv[2])
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
