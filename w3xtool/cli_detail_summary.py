"""Domain-specific detail blocks for the map CLI summary."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, assert_never

if TYPE_CHECKING:
    from .api import MapData


def iter_resource_summary_lines(md: MapData) -> Iterator[str]:
    from .resources import build_resource_report

    report = build_resource_report(md)
    if not report.nodes and not report.archive_assets:
        return
    yield "  资源:"
    yield (
        f"    引用素材: {len(report.nodes)}  内部素材: {len(report.archive_assets)}"
        f"  未引用素材: {len(report.unreferenced_assets)}"
    )
    for path in report.unreferenced_assets[:5]:
        yield f"    - 未引用素材: {path}"
    if len(report.unreferenced_assets) > 5:
        yield f"    …… 另有 {len(report.unreferenced_assets) - 5} 个"


def iter_slk_summary_lines(md: MapData) -> Iterator[str]:
    from .slkmeta import slk_inventory_from_map_path

    report = slk_inventory_from_map_path(md.path)
    if not report.has_data:
        return
    yield "  SLK:"
    yield f"    表文件: {len(report.files)}"
    for item in report.files[:6]:
        yield f"    - {item.path}: {item.rows} 行 · {item.columns} 列"
    if len(report.files) > 6:
        yield f"    …… 另有 {len(report.files) - 6} 个"


def iter_gameplay_constant_summary_lines(md: MapData) -> Iterator[str]:
    from .gameplay import gameplay_constants_from_map_path

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


def iter_order_summary_lines(md: MapData) -> Iterator[str]:
    from .orders import build_order_report

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


def iter_script_diagnostic_lines(md: MapData) -> Iterator[str]:
    from .diagnostics import build_script_diagnostics

    report = build_script_diagnostics(md)
    if not report.items:
        return
    yield "  脚本诊断:"
    for item in report.items:
        yield f"    [警告] {item.title}: {item.detail}"


def iter_crash_risk_lines(md: MapData) -> Iterator[str]:
    from .crash import build_crash_report

    report = build_crash_report(md)
    if not report.items:
        return
    yield "  崩溃风险:"
    for item in report.items[:6]:
        location = item.source or f"{item.object_name}({item.object_id})"
        yield f"    [警告] {item.title}: {location} · {item.detail}"
    if len(report.items) > 6:
        yield f"    …… 另有 {len(report.items) - 6} 个"


def iter_cheat_residue_lines(md: MapData) -> Iterator[str]:
    from .cheats import build_cheat_report

    report = build_cheat_report(md)
    if not report.items:
        return
    yield "  秘籍/调试口令:"
    for item in report.items[:6]:
        yield f"    [警告] {item.phrase}: {item.source} · {item.script}"
    if len(report.items) > 6:
        yield f"    …… 另有 {len(report.items) - 6} 个"


def iter_compat_summary_lines(md: MapData) -> Iterator[str]:
    from .compat import CompatSeverity, build_compat_report

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


def iter_audit_summary_lines(md: MapData) -> Iterator[str]:
    from .audit import AuditSeverity, build_audit_report

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
