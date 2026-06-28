"""war3map.w3e 地形元数据解析。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct
from typing import Final

W3E_FILE: Final = "war3map.w3e"
_MAGIC: Final = b"W3E!"
_ID_SIZE: Final = 4
_MAX_TILE_IDS: Final = 256
_TILE_SIZE_V11: Final = 7
_TILE_SIZE_V12: Final = 8
_HEIGHT_BASE: Final = 8192
_HEIGHT_SCALE: Final = 512
_WATER_MASK: Final = 0x3FFF
_TILE_WORLD_SIZE: Final = 128.0
_FLAG_RAMP: Final = 0x01
_FLAG_BLIGHTED: Final = 0x02
_FLAG_WATER: Final = 0x04
_FLAG_BOUNDARY: Final = 0x08


@dataclass(frozen=True, slots=True)
class TerrainBounds:
    left: float
    bottom: float
    right: float
    top: float


@dataclass(frozen=True, slots=True)
class TerrainPointSummary:
    cells: int
    min_height: float
    max_height: float
    min_water_height: float
    max_water_height: float
    ramp: int = 0
    blighted: int = 0
    water: int = 0
    boundary: int = 0
    edge: int = 0
    texture_counts: tuple[tuple[int, int], ...] = ()
    cliff_texture_counts: tuple[tuple[int, int], ...] = ()
    cliff_level_counts: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True, slots=True)
class TerrainInfo:
    version: int
    base_tileset: str
    custom_tilesets: bool
    ground_tiles: tuple[str, ...]
    cliff_tiles: tuple[str, ...]
    width: int
    height: int
    bounds: TerrainBounds | None = None
    point_summary: TerrainPointSummary | None = None


def parse_w3e_header(data: bytes) -> TerrainInfo | None:
    """解析 W3E 头部里的地形集和网格尺寸；失败返回 None。"""
    try:
        return _parse_w3e_header(data)
    except ValueError:
        return None


def terrain_info_from_map_path(path: str) -> TerrainInfo | None:
    """从地图 MPQ 中读取 war3map.w3e 并返回地形摘要；失败时静默降级。"""
    from .mpq import MPQArchive

    if not Path(path).is_file():
        return None
    try:
        with MPQArchive(path) as archive:
            if not archive.has_file(W3E_FILE):
                return None
            return parse_w3e_header(archive.read_file(W3E_FILE))
    except (OSError, ValueError, KeyError):
        return None


def _parse_w3e_header(data: bytes) -> TerrainInfo:
    if data[:4] != _MAGIC:
        raise ValueError("不是 W3E 地形文件")
    version, offset = _read_i32(data, 4)
    base_tileset = _read_tileset(data, offset)
    offset += 1
    custom_tileset_flag, offset = _read_i32(data, offset)
    ground_count, offset = _read_i32(data, offset)
    ground_tiles, offset = _read_tile_ids(data, offset, ground_count)
    cliff_count, offset = _read_i32(data, offset)
    cliff_tiles, offset = _read_tile_ids(data, offset, cliff_count)
    width, height = _read_size(data, offset)
    offset += 8
    bounds = _read_bounds(data, offset, width, height)
    point_summary = _read_point_summary(data, offset, version, width, height)
    return TerrainInfo(
        version=version,
        base_tileset=base_tileset,
        custom_tilesets=bool(custom_tileset_flag),
        ground_tiles=ground_tiles,
        cliff_tiles=cliff_tiles,
        width=width,
        height=height,
        bounds=bounds,
        point_summary=point_summary,
    )


def _read_i32(data: bytes, offset: int) -> tuple[int, int]:
    if offset + 4 > len(data):
        raise ValueError("W3E 头部被截断")
    return struct.unpack_from("<i", data, offset)[0], offset + 4


def _read_tileset(data: bytes, offset: int) -> str:
    if offset >= len(data):
        raise ValueError("W3E 缺少基础地形集")
    value = data[offset:offset + 1].decode("ascii", errors="replace")
    return value or "?"


def _read_tile_ids(data: bytes, offset: int, count: int) -> tuple[tuple[str, ...], int]:
    if count < 0 or count > _MAX_TILE_IDS:
        raise ValueError("W3E 纹理数量异常")
    end = offset + count * _ID_SIZE
    if end > len(data):
        raise ValueError("W3E 纹理表被截断")
    ids = tuple(_decode_id(data[i:i + _ID_SIZE]) for i in range(offset, end, _ID_SIZE))
    return ids, end


def _read_size(data: bytes, offset: int) -> tuple[int, int]:
    if offset + 8 > len(data):
        raise ValueError("W3E 缺少网格尺寸")
    width, height = struct.unpack_from("<ii", data, offset)
    if width <= 0 or height <= 0:
        raise ValueError("W3E 网格尺寸异常")
    return width, height


def _read_bounds(data: bytes, offset: int, width: int, height: int) -> TerrainBounds | None:
    if offset + 8 > len(data):
        return None
    left, bottom = struct.unpack_from("<ff", data, offset)
    return TerrainBounds(
        left=left,
        bottom=bottom,
        right=left + (width - 1) * _TILE_WORLD_SIZE,
        top=bottom + (height - 1) * _TILE_WORLD_SIZE,
    )


def _read_point_summary(
    data: bytes,
    offset: int,
    version: int,
    width: int,
    height: int,
) -> TerrainPointSummary | None:
    tile_size = _TILE_SIZE_V12 if version >= 12 else _TILE_SIZE_V11
    cells = width * height
    start = offset + 8
    end = start + cells * tile_size
    if end > len(data):
        return None
    heights = []
    water_heights = []
    ramp = blighted = water = boundary = edge = 0
    texture_counts: dict[int, int] = {}
    cliff_texture_counts: dict[int, int] = {}
    cliff_level_counts: dict[int, int] = {}
    for pos in range(start, end, tile_size):
        raw_height, raw_water = struct.unpack_from("<HH", data, pos)
        flags = _read_tile_flags(data, pos, version)
        texture = _read_texture_index(data, pos, version)
        cliff_texture, cliff_level = _read_cliff_data(data, pos, version)
        heights.append(_decode_height(raw_height))
        water_heights.append(_decode_height(raw_water & _WATER_MASK))
        ramp += 1 if flags & _FLAG_RAMP else 0
        blighted += 1 if flags & _FLAG_BLIGHTED else 0
        water += 1 if flags & _FLAG_WATER else 0
        boundary += 1 if flags & _FLAG_BOUNDARY else 0
        edge += 1 if raw_water & 0x4000 else 0
        _increment_count(texture_counts, texture)
        _increment_count(cliff_texture_counts, cliff_texture)
        _increment_count(cliff_level_counts, cliff_level)
    return TerrainPointSummary(
        cells=cells,
        min_height=min(heights),
        max_height=max(heights),
        min_water_height=min(water_heights),
        max_water_height=max(water_heights),
        ramp=ramp,
        blighted=blighted,
        water=water,
        boundary=boundary,
        edge=edge,
        texture_counts=_sorted_counts(texture_counts),
        cliff_texture_counts=_sorted_counts(cliff_texture_counts),
        cliff_level_counts=_sorted_counts(cliff_level_counts),
    )


def _read_tile_flags(data: bytes, offset: int, version: int) -> int:
    texture_and_flags = data[offset + 4]
    if version >= 12:
        remaining_flags = data[offset + 5]
        return ((texture_and_flags & 0xC0) >> 6) | ((remaining_flags & 0x03) << 2)
    return (texture_and_flags & 0xF0) >> 4


def _read_texture_index(data: bytes, offset: int, version: int) -> int:
    texture_and_flags = data[offset + 4]
    if version >= 12:
        return texture_and_flags & 0x3F
    return texture_and_flags & 0x0F


def _read_cliff_data(data: bytes, offset: int, version: int) -> tuple[int, int]:
    cliff_data = data[offset + 7] if version >= 12 else data[offset + 6]
    return (cliff_data & 0xF0) >> 4, cliff_data & 0x0F


def _increment_count(counts: dict[int, int], key: int) -> None:
    counts[key] = counts.get(key, 0) + 1


def _sorted_counts(counts: dict[int, int]) -> tuple[tuple[int, int], ...]:
    return tuple(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _decode_height(raw: int) -> float:
    return (raw - _HEIGHT_BASE) / _HEIGHT_SCALE


def _decode_id(raw: bytes) -> str:
    return raw.decode("ascii", errors="replace").rstrip("\x00") or "?"
