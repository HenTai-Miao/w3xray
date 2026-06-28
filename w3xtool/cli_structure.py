"""CLI rendering for internal map structure summaries."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

from . import mapmeta

if TYPE_CHECKING:
    from .api import MapData


def iter_map_structure_summary_lines(md: "MapData") -> Iterator[str]:
    """Render structure metadata discovered from internal map files."""
    report = mapmeta.map_structure_report_from_map_path(md.path)
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
        yield (
            f"    路径标志: 禁止行走: {p.no_walk}  禁止飞行: {p.no_fly}"
            f"  禁止建造: {p.no_build}  荒芜地: {p.blight}  禁水: {p.no_water}"
        )
    if report.shadow is not None:
        yield _shadow_line(report.shadow)
    if report.region_strings:
        yield f"    区域条目: {_format_summary_list(report.region_strings)}"
    if report.camera_strings:
        yield f"    镜头条目: {_format_summary_list(report.camera_strings)}"
    if report.sound_strings:
        yield f"    声音条目: {_format_summary_list(report.sound_strings)}"


def _shadow_line(shadow: mapmeta.ShadowSummary) -> str:
    prefix = "阴影图"
    if shadow.width is not None and shadow.height is not None:
        prefix += f": {shadow.width}×{shadow.height}"
    else:
        prefix += f": {shadow.cells} 单元"
    line = f"    {prefix}  阴影格: {shadow.shadowed}  透明格: {shadow.unshadowed}"
    if shadow.unknown:
        line += f"  未知值: {shadow.unknown}"
    return line


def _format_summary_list(items: tuple[str, ...]) -> str:
    shown = "、".join(items[:5])
    if len(items) <= 5:
        return shown
    return f"{shown} …… 另有 {len(items) - 5} 个"
