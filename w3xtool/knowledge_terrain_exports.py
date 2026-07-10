"""Terrain and pathing exports for knowledge packs."""

from __future__ import annotations

import os
import struct
from contextlib import nullcontext
from dataclasses import dataclass
from typing import TYPE_CHECKING, ContextManager, Protocol

from .campaign_sources import open_map_source
from .knowledge_io import tsv, write_text
from .mapmeta import MapStructureReport, build_map_structure_report
from .terrain import TerrainInfo, parse_w3e_header
from .terrain_tiles import describe_terrain_tile

if TYPE_CHECKING:
    from .api import MapData


class _ReadableSource(Protocol):
    def read_file(self, name: str) -> bytes: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class TerrainExportData:
    terrain: TerrainInfo | None
    structure: MapStructureReport


class _DirectorySource:
    def __init__(self, root: str) -> None:
        self._root = os.path.realpath(root)
        self._files = _index_directory(self._root)

    def read_file(self, name: str) -> bytes:
        path = self._files.get(_normalize_path(name))
        if path is None:
            raise KeyError(name)
        with open(path, "rb") as handle:
            return handle.read()

    def close(self) -> None:
        return


def write_terrain_exports(md: "MapData", out_dir: str) -> int:
    """Write terrain, texture usage and pathing tables."""
    data = build_terrain_export_data(md)
    count = write_text(out_dir, "地形摘要.tsv", format_terrain_summary_tsv(data.terrain))
    count += write_text(out_dir, "地形纹理.tsv", format_terrain_textures_tsv(data.terrain))
    count += write_text(out_dir, "路径网格.tsv", format_pathing_tsv(data.structure))
    return count


def build_terrain_export_data(md: "MapData") -> TerrainExportData:
    """Read W3E/WPM/SHD from a map source or source-like directory."""
    source_context = _open_source(md)
    if source_context is None:
        return TerrainExportData(None, MapStructureReport())
    try:
        with source_context as source:
            terrain = _read_terrain(source)
            structure = _read_structure(source)
    except (OSError, ValueError, struct.error):
        return TerrainExportData(None, MapStructureReport())
    return TerrainExportData(terrain, structure)


def format_terrain_summary_tsv(info: TerrainInfo | None) -> str:
    """Format W3E terrain metadata as key/value TSV."""
    rows = ["项目\t值"]
    if info is None:
        rows.append("状态\t未读取")
        return "\n".join(rows) + "\n"
    rows.extend((
        f"版本\t{info.version}",
        f"网格\t{info.width}×{info.height}",
        f"基础地形集\t{tsv(info.base_tileset)}",
        f"自定义地形集\t{'是' if info.custom_tilesets else '否'}",
    ))
    if info.bounds is not None:
        rows.extend((
            f"左边界\t{_fmt(info.bounds.left)}",
            f"右边界\t{_fmt(info.bounds.right)}",
            f"下边界\t{_fmt(info.bounds.bottom)}",
            f"上边界\t{_fmt(info.bounds.top)}",
        ))
    if info.point_summary is not None:
        summary = info.point_summary
        rows.extend((
            f"地形点\t{summary.cells}",
            f"高度范围\t{_fmt(summary.min_height)}~{_fmt(summary.max_height)}",
            f"水位范围\t{_fmt(summary.min_water_height)}~{_fmt(summary.max_water_height)}",
            f"水域\t{summary.water}",
            f"坡道\t{summary.ramp}",
            f"荒芜地\t{summary.blighted}",
            f"边界\t{summary.boundary}",
            f"边缘\t{summary.edge}",
        ))
    return "\n".join(rows) + "\n"


def format_terrain_textures_tsv(info: TerrainInfo | None) -> str:
    """Format ground/cliff tile IDs and usage counts."""
    rows = ["类型\t索引\tID\t名称\t贴图\t使用次数"]
    if info is None:
        return "\n".join(rows) + "\n"
    ground_usage = dict(info.point_summary.texture_counts) if info.point_summary else {}
    cliff_usage = dict(info.point_summary.cliff_texture_counts) if info.point_summary else {}
    rows.extend(_tile_rows("地表", info.ground_tiles, ground_usage))
    rows.extend(_tile_rows("悬崖", info.cliff_tiles, cliff_usage))
    return "\n".join(rows) + "\n"


def format_pathing_tsv(report: MapStructureReport) -> str:
    """Format WPM pathing and SHD shadow summaries."""
    rows = ["项目\t值"]
    if report.pathing is None:
        rows.append("状态\t未读取")
    else:
        pathing = report.pathing
        rows.extend((
            f"宽度\t{pathing.width}",
            f"高度\t{pathing.height}",
            f"单元\t{pathing.cells}",
            f"禁止行走\t{pathing.no_walk}",
            f"禁止飞行\t{pathing.no_fly}",
            f"禁止建造\t{pathing.no_build}",
            f"荒芜地\t{pathing.blight}",
            f"禁水\t{pathing.no_water}",
            f"未知标志\t{pathing.unknown}",
        ))
    if report.shadow is not None:
        shadow = report.shadow
        rows.extend((
            f"阴影单元\t{shadow.cells}",
            f"阴影格\t{shadow.shadowed}",
            f"透明格\t{shadow.unshadowed}",
            f"阴影未知值\t{shadow.unknown}",
        ))
    return "\n".join(rows) + "\n"


def _tile_rows(kind: str, tile_ids: tuple[str, ...], usage: dict[int, int]) -> list[str]:
    rows: list[str] = []
    for index, tile_id in enumerate(tile_ids):
        tile = describe_terrain_tile(tile_id)
        rows.append("\t".join((
            kind,
            str(index),
            tsv(tile.tile_id),
            tsv(tile.label),
            tsv(tile.path),
            str(usage.get(index, 0)),
        )))
    return rows


def _read_terrain(source: _ReadableSource) -> TerrainInfo | None:
    try:
        return parse_w3e_header(source.read_file("war3map.w3e"))
    except (KeyError, OSError, ValueError, struct.error):
        return None


def _read_structure(source: _ReadableSource) -> MapStructureReport:
    files: dict[str, bytes] = {}
    for name in ("war3map.w3r", "war3map.w3c", "war3map.w3s", "war3map.wpm", "war3map.shd"):
        try:
            files[name] = source.read_file(name)
        except (KeyError, OSError, ValueError, struct.error):
            continue
    return build_map_structure_report(files)


def _open_source(md: MapData) -> ContextManager[_ReadableSource] | None:
    if md.path and os.path.isdir(md.path):
        return nullcontext(_DirectorySource(md.path))
    try:
        return open_map_source(md)
    except (OSError, ValueError, struct.error):
        return None


def _index_directory(root: str) -> dict[str, str]:
    files: dict[str, str] = {}
    for current, _dirnames, names in os.walk(root):
        for name in names:
            full_path = os.path.realpath(os.path.join(current, name))
            if os.path.commonpath([root, full_path]) != root:
                continue
            files[_normalize_path(os.path.relpath(full_path, root))] = full_path
    return files


def _normalize_path(path: str) -> str:
    normalized = path.strip().strip('"').strip("'").replace("/", "\\").lower()
    while "\\\\" in normalized:
        normalized = normalized.replace("\\\\", "\\")
    return normalized


def _fmt(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")
