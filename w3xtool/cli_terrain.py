"""CLI rendering for terrain summaries."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

from . import terrain
from .scene_bounds import build_scene_bounds_report
from .terrain_tiles import format_terrain_tile_list

if TYPE_CHECKING:
    from .api import MapData


def iter_terrain_summary_lines(md: "MapData") -> Iterator[str]:
    """Render terrain metadata discovered from war3map.w3e."""
    if md.archive_source is None:
        info = terrain.terrain_info_from_map_path(md.path)
    else:
        from .knowledge_terrain_exports import build_terrain_export_data

        info = build_terrain_export_data(md).terrain
    if info is None:
        return
    custom = "是" if info.custom_tilesets else "否"
    yield "  地形:"
    yield (f"    网格: {info.width}×{info.height}  基础地形: {info.base_tileset}"
           f"  自定义地形集: {custom}")
    if info.bounds is not None:
        yield _bounds_line(info.bounds)
    if info.ground_tiles:
        yield f"    地表纹理: {format_terrain_tile_list(info.ground_tiles)}"
    if info.cliff_tiles:
        yield f"    悬崖纹理: {format_terrain_tile_list(info.cliff_tiles)}"
    if info.point_summary is not None:
        yield _point_height_line(info.point_summary)
        yield _point_flag_line(info.point_summary)
        if info.point_summary.texture_counts:
            yield "    地表使用: " + _format_index_counts(
                info.point_summary.texture_counts,
                info.ground_tiles,
            )
        if info.point_summary.cliff_texture_counts:
            yield "    悬崖纹理使用: " + _format_index_counts(
                info.point_summary.cliff_texture_counts,
                info.cliff_tiles,
            )
        if info.point_summary.cliff_level_counts:
            yield "    悬崖层级: " + _format_plain_counts(info.point_summary.cliff_level_counts)
    report = build_scene_bounds_report(md, info)
    if report is not None and report.issues:
        yield (
            f"    场景边界: 越界单位 {report.unit_issue_count}/{report.unit_count}"
            f"  越界装饰物 {report.doodad_issue_count}/{report.doodad_count}"
        )
        for issue in report.issues[:5]:
            yield f"    - 越界{issue.kind}: {issue.type_id} ({_fmt(issue.x)}, {_fmt(issue.y)})"
        if len(report.issues) > 5:
            yield f"    …… 另有 {len(report.issues) - 5} 个越界放置物"


def _point_height_line(summary: terrain.TerrainPointSummary) -> str:
    return (
        f"    地形点: {summary.cells}  高度: {_fmt(summary.min_height)}~{_fmt(summary.max_height)}"
        f"  水位: {_fmt(summary.min_water_height)}~{_fmt(summary.max_water_height)}"
    )


def _bounds_line(bounds: terrain.TerrainBounds) -> str:
    return (
        f"    坐标范围: X {_fmt(bounds.left)}~{_fmt(bounds.right)}"
        f"  Y {_fmt(bounds.bottom)}~{_fmt(bounds.top)}"
    )


def _point_flag_line(summary: terrain.TerrainPointSummary) -> str:
    return (
        f"    地形标志: 水域: {summary.water}  坡道: {summary.ramp}"
        f"  荒芜地: {summary.blighted}  边界: {summary.boundary}  边缘: {summary.edge}"
    )


def _format_index_counts(counts: tuple[tuple[int, int], ...], labels: tuple[str, ...]) -> str:
    return "、".join(f"{_label_for_index(index, labels)}:{count}" for index, count in counts[:8])


def _format_plain_counts(counts: tuple[tuple[int, int], ...]) -> str:
    return "、".join(f"{index}:{count}" for index, count in counts[:8])


def _label_for_index(index: int, labels: tuple[str, ...]) -> str:
    if 0 <= index < len(labels):
        return labels[index]
    return f"#{index}"


def _fmt(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")
