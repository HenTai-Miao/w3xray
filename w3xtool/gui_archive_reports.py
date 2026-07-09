"""Archive-backed GUI report blocks."""

from __future__ import annotations

import os

from .api import MapData
from .gui_reports import GuiReportBlock


def build_archive_blocks(md: MapData) -> tuple[GuiReportBlock, ...]:
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
